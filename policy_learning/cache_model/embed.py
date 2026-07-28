# coding=utf-8
# Copyright 2026 The Google Research Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Defines embedders for memory-access features."""

import abc
import torch
from torch import nn


def from_config(config):
  """Creates an embedder specified by the config.

  Args:
    config (cfg.Config): specifies embedder type and constructor args.

  Returns:
    Embedder: embedder specified by the config.
  """
  embedder_type = config.get("type")
  if embedder_type == "byte":
    return ByteEmbedder(config.get("bytes_per_entry"), config.get("embed_dim"))
  elif embedder_type == "dynamic-vocab":
    return DynamicVocabEmbedder(
        config.get("embed_dim"), config.get("max_vocab_size"))
  elif embedder_type == "positional":
    return PositionalEmbedder(config.get("embed_dim"))
  elif embedder_type == "rw-flag":
    return RWFlagEmbedder(config.get("embed_dim"))
  elif embedder_type == "qmap-access":
    return QMAPAccessFeatureEmbedder(
        from_config(config.get("address_embedder")),
        from_config(config.get("pc_embedder")),
        from_config(config.get("rw_embedder")),
        use_page_id_embedding=config.get("use_page_id_embedding", True))
  else:
    raise ValueError("{} not a supported embedding type.".format(embedder_type))


class Embedder(nn.Module):
  """Embeds a batch of objects into an embedding space.

  Subclasses of Embedder should register with the from_config method.
  """

  __metaclass__ = abc.ABCMeta

  def __init__(self, embed_dim):
    """Sets the output embedding dimension to be embed_dim.

    Args:
      embed_dim (int): dimension of output of forward call.
    """
    super(Embedder, self).__init__()
    self._embed_dim = embed_dim

  @property
  def embed_dim(self):
    return self._embed_dim


class ByteEmbedder(Embedder):
  """Embeds each byte and concatenates."""

  def __init__(self, bytes_per_entry, embed_dim):
    """Embeds entries that have bytes_per_entry many bytes.

    Args:
      bytes_per_entry (int): number of bytes per input.
      embed_dim (int): see parent class.
    """
    super(ByteEmbedder, self).__init__(embed_dim)

    if embed_dim % bytes_per_entry != 0:
      raise ValueError(
          "Embed dim ({}) must be an even multiple of bytes per entry ({})"
          .format(embed_dim, bytes_per_entry))

    embed_dim_per_byte = embed_dim // bytes_per_entry
    # 256 possible byte values
    self._byte_embedding = nn.Embedding(256, embed_dim_per_byte)
    self._bytes_per_entry = bytes_per_entry
    self._final_layer = nn.Linear(embed_dim, embed_dim)

  def forward(self, ints):
    """Returns embeddings for each int interpretted as a byte array.

    Args:
      ints (list[int]): batch of inputs of length batch_size.

    Returns:
      embeddings (torch.FloatTensor): batch of embeddings of shape
        (batch_size, embed_dim). Each int is interpretted as bytes_per_entry
        bytes and each byte is embedded separately.
    """
    def int_to_byte_tensor(ints, num_bytes):
      """Converts ints to tensor of shape (num_bytes).

      Args:
        ints (list[int]): ints to convert.
        num_bytes (int): number of bytes to convert to.

      Returns:
        byte_tensor (torch.LongTensor): shape (len(ints), num_bytes).
          byte_tensor[i][j] = value of jth byte of ints[i].
      """
      # Byte order doesn't matter as long as it's consistent.
      return torch.tensor(
          [int(x).to_bytes(num_bytes, byteorder="big") for x in ints]).long()

    # (batch_size, bytes_per_entry, embed_dim_per_byte)
    byte_tensors = int_to_byte_tensor(ints, self._bytes_per_entry)
    byte_embeddings = self._byte_embedding(byte_tensors)
    return self._final_layer(byte_embeddings.view(-1, self.embed_dim))


class DynamicVocabEmbedder(Embedder):
  """Train-fitted vocabulary embedder with reserved ``UNK=0``.

  Legacy callers may still grow the vocabulary before ``freeze`` is called.
  CAPD finals v3 explicitly fits on train data and freezes before any
  validation/test forward pass; unseen frozen inputs always map to index 0.
  """

  def __init__(self, embed_dim, max_vocab_size):
    super().__init__(embed_dim)

    self._max_vocab_size = max_vocab_size
    self._input_to_index = {}
    # Reserve index 0 for UNK
    self._vocab_size = 1
    self._frozen = False

    # Override default initialization of embeddings with Xavier
    weight = torch.zeros(max_vocab_size, embed_dim)
    nn.init.xavier_uniform_(weight)
    self._embedding = nn.Embedding(max_vocab_size, embed_dim, _weight=weight)

  @property
  def vocab_size(self):
    return self._vocab_size

  @property
  def frozen(self):
    return self._frozen

  @property
  def input_to_index(self):
    return dict(self._input_to_index)

  @staticmethod
  def _flatten_inputs(inputs):
    if torch.is_tensor(inputs):
      return inputs.detach().cpu().reshape(-1).tolist(), tuple(inputs.shape)
    values = list(inputs)
    return values, (len(values),)

  def _index_for(self, inp):
    if (not self._frozen and inp not in self._input_to_index and
        self._max_vocab_size > self._vocab_size):
      self._input_to_index[inp] = self._vocab_size
      self._vocab_size += 1
    return self._input_to_index.get(inp, 0)

  def fit(self, inputs):
    """Adds train-only values to the vocabulary before it is frozen."""
    if self._frozen:
      raise ValueError("Cannot fit a frozen vocabulary.")
    values = (inputs.detach().cpu().reshape(-1).tolist()
              if torch.is_tensor(inputs) else inputs)
    for inp in values:
      self._index_for(inp)
    return self

  def freeze(self):
    self._frozen = True
    return self

  def indices(self, inputs):
    """Maps inputs to indices without exposing or mutating embedding weights."""
    flat_inputs, input_shape = self._flatten_inputs(inputs)
    return torch.tensor(
        [self._index_for(inp) for inp in flat_inputs],
        dtype=torch.long,
        device=self._embedding.weight.device).view(*input_shape)

  def forward(self, inputs):
    """Returns embeddings for each int interpretted as a byte array.

    Args:
      inputs (list[Object] | torch.Tensor): batch of hashable inputs. QMAP
        uses this embedder for [batch_size, sequence_length] address/PC
        tensors, while the legacy PARROT path passes a flat list.

    Returns:
      embeddings (torch.FloatTensor): embeddings of shape
        (*input_shape, embed_dim).
    """
    flat_inputs, input_shape = self._flatten_inputs(inputs)
    indices = torch.tensor(
        [self._index_for(inp) for inp in flat_inputs], dtype=torch.long,
        device=self._embedding.weight.device)
    embeddings = self._embedding(indices)
    return embeddings.view(*input_shape, self.embed_dim)

  def state_dict(self, destination=None, prefix="", keep_vars=False):
    state_dict = super().state_dict(destination, prefix, keep_vars)
    state_dict[prefix + "vocab_size"] = self._vocab_size
    state_dict[prefix + "input_to_index"] = self._input_to_index
    state_dict[prefix + "vocab_frozen"] = self._frozen
    return state_dict

  def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict,
                            missing_keys, unexpected_keys, error_msgs):
    self._vocab_size = state_dict.pop(prefix + "vocab_size")
    self._input_to_index = state_dict.pop(prefix + "input_to_index")
    self._frozen = state_dict.pop(prefix + "vocab_frozen", False)
    super()._load_from_state_dict(
        state_dict, prefix, local_metadata, strict, missing_keys,
        unexpected_keys, error_msgs)


class RWFlagEmbedder(Embedder):
  """Embeds QMAP read/write flags.

  QMAP 约定：
    0 表示读访问（Read）
    1 表示写访问（Write）
  """

  def __init__(self, embed_dim):
    super(RWFlagEmbedder, self).__init__(embed_dim)
    self._embedding = nn.Embedding(2, embed_dim)

  def forward(self, rw_flags):
    """Embeds read/write flags.

    Args:
      rw_flags (list[int] | torch.Tensor): 读写标志，形状通常为
        [batch_size, sequence_length]。

    Returns:
      torch.FloatTensor: 形状为 [batch_size, sequence_length, embed_dim]。
    """
    if torch.is_tensor(rw_flags):
      indices = rw_flags.long().to(self._embedding.weight.device)
    else:
      indices = torch.tensor(
          rw_flags, dtype=torch.long, device=self._embedding.weight.device)

    if torch.any((indices < 0) | (indices > 1)):
      raise ValueError("RW flags must be 0 for read or 1 for write.")
    return self._embedding(indices)


class QMAPAccessFeatureEmbedder(Embedder):
  """Embeds and concatenates QMAP memory-access features.

  输入特征只包含全局访存信息：
    - page_ids: 按 page_shift 归一化后的页面 ID
    - pcs: 程序计数器
    - rw_flags: 读写标志，0 读、1 写

  这里不再接收 Cache Set、Cache Way 或 set 内 cache line 列表。
  """

  def __init__(self, address_embedder, pc_embedder, rw_embedder,
               use_page_id_embedding=True):
    embed_dim = (address_embedder.embed_dim + pc_embedder.embed_dim +
                 rw_embedder.embed_dim)
    super(QMAPAccessFeatureEmbedder, self).__init__(embed_dim)
    self._address_embedder = address_embedder
    self._pc_embedder = pc_embedder
    self._rw_embedder = rw_embedder
    self._use_page_id_embedding = bool(use_page_id_embedding)

  @property
  def page_embedder(self):
    """The single page vocabulary/embedding used by both model paths."""
    return self._address_embedder

  @property
  def pc_embedder(self):
    return self._pc_embedder

  def embed_pages(self, page_ids):
    page_embeddings = self._address_embedder(page_ids)
    if not self._use_page_id_embedding:
      # Keep the tensor shape and downstream architecture checkpoint-compatible
      # while severing every score/loss gradient path to absolute page identity.
      page_embeddings = torch.zeros_like(page_embeddings)
    return page_embeddings

  def forward(self, page_ids, pcs, rw_flags):
    """Returns unified QMAP access embeddings.

    Args:
      page_ids (torch.LongTensor): [batch_size, sequence_length]。
      pcs (torch.LongTensor): [batch_size, sequence_length]。
      rw_flags (torch.LongTensor): [batch_size, sequence_length]，0/1。

    Returns:
      torch.FloatTensor: [batch_size, sequence_length, hidden_dim]。
    """
    address_embeddings = self.embed_pages(page_ids)
    pc_embeddings = self._pc_embedder(pcs)
    rw_embeddings = self._rw_embedder(rw_flags)

    # 沿最后一维拼接三类访存特征，作为后续 Transformer Encoder 的输入。
    return torch.cat(
        (address_embeddings, pc_embeddings, rw_embeddings), dim=-1)


class PositionalEmbedder(Embedder):
  """Takes position index and returns a simple fixed embedding."""

  def forward(self, position_indices):
    """Returns a fixed embedding for each input index.

    Embeds positions according to Vaswani, et. al., 2017:
      embed_{2i} = sin(pos / 10000^(2i / embed_dim))
      embed_{2i + 1} = cos(pos / 10000^(2i / embed_dim))

    Args:
      position_indices (list[int]): batch of positions of length batch_size

    Returns:
      embeddings (torch.FloatTensor): of shape (batch_size, embed_dim)
    """
    batch_size = len(position_indices)

    # i's in above equation
    embed_indices = torch.arange(self.embed_dim).expand(batch_size, -1).float()
    position_tensor = torch.tensor(position_indices).unsqueeze(-1).float()
    embedding = position_tensor / 10000. ** (2 * embed_indices / self.embed_dim)
    embedding = torch.where(
        embed_indices % 2 == 0, torch.sin(embedding), torch.cos(embedding))
    return embedding
