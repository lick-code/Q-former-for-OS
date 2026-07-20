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

"""Defines QMAP models for page-migration policy learning."""

import abc
import logging
import math
import torch
from torch import distributions as td
from torch import nn
from torch.nn import functional as F

try:
  from policy_learning.cache_model import embed
  from policy_learning.cache_model import loss as L
except ImportError:
  # 允许直接执行本文件：python policy_learning/cache_model/model.py
  import embed
  import loss as L


class QMAPFeatureModel(nn.Module):
  """QMAP 第一阶段：多维访存特征嵌入。

  该模块只处理全局访存序列，不再依赖 PARROT 的 Cache Set、Cache Way
  或 set 内 cache line 候选列表。输出会作为后续 Transformer Encoder
  和 Q-Former 的输入。
  """

  @classmethod
  def from_config(cls, config):
    """Creates a QMAP feature model from config."""
    qmap_feature_embedder = embed.QMAPAccessFeatureEmbedder(
        embed.from_config(config.get("address_embedder")),
        embed.from_config(config.get("pc_embedder")),
        embed.from_config(config.get("rw_embedder")))
    return cls(qmap_feature_embedder)

  def __init__(self, qmap_feature_embedder):
    super(QMAPFeatureModel, self).__init__()
    self._qmap_feature_embedder = qmap_feature_embedder
    self.hidden_dim = qmap_feature_embedder.embed_dim

  def forward(self, physical_addresses, pcs, rw_flags):
    """Embeds QMAP access sequences.

    Args:
      physical_addresses (torch.LongTensor): 物理地址序列，
        形状为 [batch_size, sequence_length]。
      pcs (torch.LongTensor): 程序计数器序列，
        形状为 [batch_size, sequence_length]。
      rw_flags (torch.LongTensor): 读写标志序列，0 表示读，1 表示写，
        形状为 [batch_size, sequence_length]。

    Returns:
      torch.FloatTensor: 拼接后的统一访存表示，
        形状为 [batch_size, sequence_length, hidden_dim]。
    """
    return self._qmap_feature_embedder(physical_addresses, pcs, rw_flags)


class SinusoidalPositionEncoding(nn.Module):
  """Fixed Vaswani-style position encoding for oldest-to-newest history."""

  def __init__(self, hidden_dim, max_sequence_length=4096):
    super(SinusoidalPositionEncoding, self).__init__()
    if hidden_dim <= 0 or max_sequence_length <= 0:
      raise ValueError("Position-encoding dimensions must be positive.")
    positions = torch.arange(max_sequence_length, dtype=torch.float32).unsqueeze(1)
    frequencies = torch.exp(
        torch.arange(0, hidden_dim, 2, dtype=torch.float32) *
        (-math.log(10000.0) / hidden_dim))
    encoding = torch.zeros(max_sequence_length, hidden_dim, dtype=torch.float32)
    encoding[:, 0::2] = torch.sin(positions * frequencies)
    encoding[:, 1::2] = torch.cos(
        positions * frequencies[:encoding[:, 1::2].shape[1]])
    self.register_buffer("encoding", encoding.unsqueeze(0), persistent=True)

  def forward(self, inputs):
    if inputs.ndim != 3:
      raise ValueError("Position encoding expects [batch, sequence, hidden].")
    sequence_length = inputs.shape[1]
    if sequence_length > self.encoding.shape[1]:
      raise ValueError("Input sequence exceeds fixed position-encoding size.")
    position = self.encoding[:, :sequence_length, :].to(
        device=inputs.device, dtype=inputs.dtype)
    return inputs + position


class QFormer(nn.Module):
  """QMAP Q-Former：用 K 个可学习 Query 提取宏观访存模式。"""

  def __init__(self, hidden_dim, num_queries=4, num_heads=2, dropout=0.0):
    """Constructs the Q-Former cross-attention block.

    Args:
      hidden_dim (int): 输入/输出特征维度。
      num_queries (int): 可学习 Query 数量 K。
      num_heads (int): cross-attention 的多头数量。
      dropout (float): attention dropout。
    """
    super(QFormer, self).__init__()
    self._query_tokens = nn.Parameter(torch.randn(1, num_queries, hidden_dim))
    self._cross_attention = nn.MultiheadAttention(
        embed_dim=hidden_dim, num_heads=num_heads, dropout=dropout)
    self._norm = nn.LayerNorm(hidden_dim)

  def forward(self, encoded_accesses, history_mask=None):
    """Runs cross-attention from learnable queries to encoded accesses.

    Args:
      encoded_accesses (torch.FloatTensor): TransformerEncoder 输出，
        形状为 [batch_size, sequence_length, hidden_dim]。

    Returns:
      torch.FloatTensor: 宏观模式表征 Z，
        形状为 [batch_size, num_queries, hidden_dim]。
    """
    batch_size = encoded_accesses.shape[0]
    queries = self._query_tokens.expand(batch_size, -1, -1)

    # nn.MultiheadAttention 默认使用 [sequence_length, batch_size, hidden_dim]。
    query_seq = queries.transpose(0, 1)
    key_value_seq = encoded_accesses.transpose(0, 1)
    key_padding_mask = None
    if history_mask is not None:
      key_padding_mask = history_mask <= 0
    attended, _ = self._cross_attention(
        query=query_seq, key=key_value_seq, value=key_value_seq,
        key_padding_mask=key_padding_mask)
    attended = attended.transpose(0, 1)
    return self._norm(attended + queries)


class QMAPMacroscopicPatternExtractor(nn.Module):
  """QMAP 第二阶段：TransformerEncoder 访存序列编码。

  输入来自第一阶段的联合访存特征：
    [batch_size, sequence_length, hidden_dim]

  主路径输出完整编码序列 X_enc：
    [batch_size, sequence_length, hidden_dim]

  历史实验仍可选择 Q-Former 或 mean/last pooling 输出。
  """

  def __init__(self, hidden_dim=18, num_queries=4, num_layers=1, num_heads=2,
               feedforward_dim=None, dropout=0.0, use_qformer=True,
               pooling_strategy="mean", position_encoding="none",
               max_sequence_length=4096):
    """Constructs the QMAP macroscopic pattern extractor.

    Args:
      hidden_dim (int): 输入特征维度，默认匹配第一阶段测试中的 18。
      num_queries (int): Q-Former 可学习 Query 数量 K。
      num_layers (int): TransformerEncoder 层数。
      num_heads (int): Transformer 和 Q-Former 的 attention head 数。
      feedforward_dim (int | None): Transformer FFN 中间维度。
      dropout (float): dropout rate。
      use_qformer (bool): 是否走历史 Q-Former 路径。
      pooling_strategy (str): "none" 返回完整 X_enc；"mean"/"last"
        保留历史 pooling 路径。
    """
    super(QMAPMacroscopicPatternExtractor, self).__init__()
    if hidden_dim % num_heads != 0:
      raise ValueError("hidden_dim must be divisible by num_heads.")
    if pooling_strategy not in ("mean", "last", "none"):
      raise ValueError("pooling_strategy must be 'mean', 'last' or 'none'.")
    if position_encoding not in ("sinusoidal", "none"):
      raise ValueError("position_encoding must be sinusoidal or none.")

    if feedforward_dim is None:
      feedforward_dim = hidden_dim * 4
    self._use_qformer = use_qformer
    self._pooling_strategy = pooling_strategy
    self._position_encoding_name = position_encoding
    self._position_encoding = (
        SinusoidalPositionEncoding(
            hidden_dim, max_sequence_length=max_sequence_length)
        if position_encoding == "sinusoidal" else None)

    encoder_layer = nn.TransformerEncoderLayer(
        d_model=hidden_dim,
        nhead=num_heads,
        dim_feedforward=feedforward_dim,
        dropout=dropout,
        activation="gelu")
    self._transformer_encoder = nn.TransformerEncoder(
        encoder_layer, num_layers=num_layers)
    if use_qformer:
      self._qformer = QFormer(
          hidden_dim=hidden_dim,
          num_queries=num_queries,
          num_heads=num_heads,
          dropout=dropout)
    else:
      self._qformer = None

  def forward(self, access_features, history_mask=None):
    """Extracts macroscopic access patterns.

    Args:
      access_features (torch.FloatTensor): 第一阶段输出，
        形状为 [batch_size, sequence_length, hidden_dim]。

    Returns:
      torch.FloatTensor: 编码后的访存序列或历史聚合结果。
    """
    sequence_length = access_features.shape[1]
    if history_mask is not None:
      if history_mask.shape != access_features.shape[:2]:
        raise ValueError("history_mask must match [batch, sequence].")
      history_mask = history_mask.to(access_features.device)
    if self._position_encoding is not None:
      access_features = self._position_encoding(access_features)
    causal_mask = self._causal_mask(
        sequence_length, device=access_features.device)

    # TransformerEncoder 默认接收 [sequence_length, batch_size, hidden_dim]。
    sequence_first = access_features.transpose(0, 1)
    encoded = self._transformer_encoder(
        sequence_first, mask=causal_mask,
        src_key_padding_mask=(history_mask <= 0
                              if history_mask is not None else None))
    encoded = encoded.transpose(0, 1)
    if history_mask is not None:
      # Left-padding queries can be fully masked by causal + key padding masks
      # in some PyTorch versions. Replace any resulting padded-token NaNs and
      # make the no-contribution contract explicit before later attention.
      encoded = encoded.masked_fill(
          (history_mask <= 0).unsqueeze(-1), 0.0)
    if self._use_qformer:
      return self._qformer(encoded, history_mask=history_mask)
    if self._pooling_strategy == "none":
      return encoded
    if self._pooling_strategy == "last":
      if history_mask is None:
        pooled = encoded[:, -1:, :]
      else:
        last_indices = torch.clamp(
            history_mask.long().sum(dim=1) - 1, min=0)
        offsets = (history_mask.shape[1] - history_mask.long().sum(dim=1))
        last_indices = last_indices + offsets
        pooled = encoded[
            torch.arange(encoded.shape[0], device=encoded.device),
            last_indices].unsqueeze(1)
    else:
      if history_mask is None:
        pooled = encoded.mean(dim=1, keepdim=True)
      else:
        weights = history_mask.to(encoded.dtype).unsqueeze(-1)
        pooled = ((encoded * weights).sum(dim=1, keepdim=True) /
                  weights.sum(dim=1, keepdim=True).clamp_min(1.0))
    return pooled

  @staticmethod
  def _causal_mask(sequence_length, device):
    """Creates an additive causal mask for TransformerEncoder."""
    mask = torch.full(
        (sequence_length, sequence_length),
        float("-inf"),
        device=device)
    return torch.triu(mask, diagonal=1)


class _LegacyHandcraftedQMAPCandidateScorer(nn.Module):
  """QMAP 第三阶段：极低开销的 64 页面候选池打分模块。

  输入只来自全局页面迁移语义：
    - Z: Q-Former 输出的宏观访存模式 [batch_size, K, hidden_dim]
    - candidates_features: LRU 不活跃链表尾部 64 个候选页的特征
      [batch_size, 64, page_dim]

  输出为每个候选页的驱逐分数：
    [batch_size, 64]
  """

  def __init__(self, hidden_dim=18, page_dim=21, num_heads=2,
               mlp_hidden_dim=None, dropout=0.0):
    """Constructs the QMAP candidate scorer.

    Args:
      hidden_dim (int): Q-Former 宏观表征维度。
      page_dim (int): 候选页固有特征 + 状态特征维度。
      num_heads (int): 候选页到宏观表征 cross-attention 的 head 数量。
      mlp_hidden_dim (int | None): 页面打分 MLP 的隐藏层维度。
      dropout (float): attention 和 MLP dropout。
    """
    super(_LegacyHandcraftedQMAPCandidateScorer, self).__init__()
    if hidden_dim % num_heads != 0:
      raise ValueError("hidden_dim must be divisible by num_heads.")

    self._candidate_projector = (
        nn.Identity() if page_dim == hidden_dim else
        nn.Linear(page_dim, hidden_dim))
    self._cross_attention = nn.MultiheadAttention(
        embed_dim=hidden_dim, num_heads=num_heads, dropout=dropout)
    self._context_norm = nn.LayerNorm(hidden_dim)

    if mlp_hidden_dim is None:
      mlp_hidden_dim = hidden_dim * 2
    self._scoring_mlp = nn.Sequential(
        nn.Linear(hidden_dim * 2, mlp_hidden_dim),
        nn.ReLU(),
        nn.Dropout(dropout),
        nn.Linear(mlp_hidden_dim, mlp_hidden_dim // 2),
        nn.ReLU(),
        nn.Linear(mlp_hidden_dim // 2, 1))

  def forward(self, z, candidates_features):
    """Scores the fixed 64-page candidate pool.

    Args:
      z (torch.FloatTensor): 宏观访存模式表征，
        形状为 [batch_size, K, hidden_dim]。
      candidates_features (torch.FloatTensor): 64 个候选页特征，
        形状为 [batch_size, 64, page_dim]。

    Returns:
      torch.FloatTensor: 64 个候选页的驱逐分数，
        形状为 [batch_size, 64]。
    """
    # U: 对齐后的候选页表征 [batch_size, 64, hidden_dim]。
    u = self._candidate_projector(candidates_features)

    # 让候选页作为 Query，去读取宏观访存模式 Z 作为 Key/Value。
    query_seq = u.transpose(0, 1)
    key_value_seq = z.transpose(0, 1)
    g, _ = self._cross_attention(
        query=query_seq, key=key_value_seq, value=key_value_seq)
    g = g.transpose(0, 1)
    g = self._context_norm(g + u)

    # 拼接候选页自身状态和其从宏观模式中读出的上下文，再逐页并行打分。
    scoring_features = torch.cat((u, g), dim=-1)
    eviction_scores = self._scoring_mlp(scoring_features).squeeze(-1)
    return eviction_scores


class QMAPCandidateScorer(nn.Module):
  """Scores candidate pages using page-id embeddings and page-state features.

  In the main QMAP path, each candidate page is projected into a page feature
  vector and used as the Query. The Transformer encoded access sequence X_enc
  is used as Key/Value. The resulting per-page context vector is scored by a
  small MLP.
  """

  def __init__(self, hidden_dim=18, page_state_dim=4, page_embed_dim=8,
               page_vocab_size=100000, num_heads=2, mlp_hidden_dim=None,
               dropout=0.0, page_dim=None, scoring_input="concat",
               shared_page_embedding=False):
    super(QMAPCandidateScorer, self).__init__()
    if hidden_dim % num_heads != 0:
      raise ValueError("hidden_dim must be divisible by num_heads.")
    if scoring_input not in ("concat", "context"):
      raise ValueError("scoring_input must be 'concat' or 'context'.")

    self._scoring_input = scoring_input
    self._shared_page_embedding = bool(shared_page_embedding)
    self._page_embedder = None
    if not self._shared_page_embedding:
      self._page_embedder = embed.DynamicVocabEmbedder(
          embed_dim=page_embed_dim, max_vocab_size=page_vocab_size)
    self._candidate_projector = nn.Linear(
        page_embed_dim + page_state_dim, hidden_dim)
    self._legacy_candidate_projector = None
    if page_dim is not None:
      self._legacy_candidate_projector = (
          nn.Identity() if page_dim == hidden_dim else
          nn.Linear(page_dim, hidden_dim))

    self._cross_attention = nn.MultiheadAttention(
        embed_dim=hidden_dim, num_heads=num_heads, dropout=dropout)
    self._context_norm = nn.LayerNorm(hidden_dim)

    if mlp_hidden_dim is None:
      mlp_hidden_dim = hidden_dim * 2
    mlp_input_dim = hidden_dim if scoring_input == "context" else hidden_dim * 2
    self._scoring_mlp = nn.Sequential(
        nn.Linear(mlp_input_dim, mlp_hidden_dim),
        nn.ReLU(),
        nn.Dropout(dropout),
        nn.Linear(mlp_hidden_dim, mlp_hidden_dim // 2),
        nn.ReLU(),
        nn.Linear(mlp_hidden_dim // 2, 1))

  def forward(self, z, candidate_pages, candidate_state_features=None,
              candidate_mask=None, candidate_page_embeddings=None,
              history_mask=None):
    """Scores candidates.

    Args:
      z: Transformer encoded sequence X_enc [batch_size, sequence_length,
        hidden_dim], or a historical pooled/Q-Former context
        [batch_size, K, hidden_dim].
      candidate_pages: candidate page ids [batch_size, num_candidates]. If
        candidate_state_features is None, this is treated as a legacy
        handcrafted feature tensor.
      candidate_state_features: [recent frequency, dirty flag, residency,
        original pool LRU rank], shape [batch_size, num_candidates, 4].
      candidate_mask: 1 for real candidates and 0 for padding, with shape
        [batch_size, num_candidates].

    Returns:
      Eviction scores with shape [batch_size, num_candidates].
    """
    if candidate_state_features is None:
      if self._legacy_candidate_projector is None:
        raise ValueError(
            "candidate_state_features is required for QMAP candidate scoring.")
      u = self._legacy_candidate_projector(candidate_pages)
    else:
      if self._shared_page_embedding:
        if candidate_page_embeddings is None:
          raise ValueError(
              "Shared page embedding mode requires candidate embeddings.")
        page_embeddings = candidate_page_embeddings
      else:
        if candidate_page_embeddings is not None:
          raise ValueError(
              "External page embeddings require shared_page_embedding=True.")
        page_embeddings = self._page_embedder(candidate_pages.long())
      candidate_inputs = torch.cat(
          (page_embeddings, candidate_state_features), dim=-1)
      u = self._candidate_projector(candidate_inputs)

    query_seq = u.transpose(0, 1)
    key_value_seq = z.transpose(0, 1)
    key_padding_mask = None
    if history_mask is not None and z.shape[1] == history_mask.shape[1]:
      key_padding_mask = history_mask <= 0
    g, _ = self._cross_attention(
        query=query_seq, key=key_value_seq, value=key_value_seq,
        key_padding_mask=key_padding_mask)
    g = g.transpose(0, 1)
    g = self._context_norm(g + u)

    if self._scoring_input == "context":
      scoring_features = g
    else:
      scoring_features = torch.cat((u, g), dim=-1)
    eviction_scores = self._scoring_mlp(scoring_features).squeeze(-1)
    if candidate_mask is not None:
      eviction_scores = eviction_scores.masked_fill(
          candidate_mask <= 0, torch.finfo(eviction_scores.dtype).min)
    return eviction_scores


class LossFunction(abc.ABC):
  """The interface for loss functions used by QMAP training."""

  @abc.abstractmethod
  def __call__(self, probs, predicted_log_reuse_distances,
               true_log_reuse_distances, mask):
    """Computes the value of the loss.

    Args:
      probs (torch.FloatTensor): probability of each evicting line of shape
        (batch_size, num_lines).
      predicted_log_reuse_distances (torch.FloatTensor): log of the model
        predicted reuse distance of each line of shape (batch_size, num_lines).
      true_log_reuse_distances (torch.FloatTensor): log of the true reuse
        distance of each line of shape (batch_size, num_lines).
      mask (torch.ByteTensor): masks out elements if the value is 0 of shape
        (batch_size, num_lines).

    Returns:
      loss (torch.FloatTensor): loss for each batch of shape (batch_size,).
    """
    raise NotImplementedError


class LogProbLoss(LossFunction):
  """LossFunction wrapper around top_1_log_likelihood."""

  def __call__(self, probs, predicted_log_reuse_distances,
               true_log_reuse_distances, mask):
    del predicted_log_reuse_distances
    del true_log_reuse_distances
    del mask

    return L.top_1_log_likelihood(probs)


class KLLoss(LossFunction):
  """Loss equal to D_KL(pi^opt || pi^learned).

  pi^opt is approximated by softmax(temperature * reuse distance).
  """

  def __init__(self, temperature=1):
    super().__init__()
    self._temperature = temperature

  def __call__(self, probs, predicted_log_reuse_distances,
               true_log_reuse_distances, mask):
    approx_oracle_policy = td.Categorical(
        logits=self._temperature * true_log_reuse_distances)
    learned_policy = td.Categorical(probs=probs)
    loss = td.kl.kl_divergence(approx_oracle_policy, learned_policy)
    return loss


class ApproxNDCGLoss(LossFunction):
  """LossFunction wrapper around plackett_luce."""

  def __init__(self):
    super().__init__()
    logging.warning("Expects that all calls to loss are labeled with Belady's")

  def __call__(self, probs, predicted_log_reuse_distances,
               true_log_reuse_distances, mask):
    del predicted_log_reuse_distances

    return L.approx_ndcg(probs, true_log_reuse_distances, mask=mask)


class ReuseDistanceLoss(LossFunction):
  """Computes the MSE loss between predicted and true log reuse distances."""

  def __init__(self):
    super().__init__()
    logging.warning("Expects that all calls to loss are labeled with Belady's")

  def __call__(self, probs, predicted_log_reuse_distances,
               true_log_reuse_distances, mask):
    del probs

    return F.mse_loss(
        predicted_log_reuse_distances * mask.float(),
        true_log_reuse_distances * mask.float(), reduce=False).mean(-1)


if __name__ == "__main__":
  # 第二阶段最小测试：输入模拟第一阶段输出 [B, T, hidden_dim]。
  access_features = torch.randn(2, 4, 18)
  extractor = QMAPMacroscopicPatternExtractor(
      hidden_dim=18,
      num_queries=4,
      num_layers=1,
      num_heads=2,
      use_qformer=False,
      pooling_strategy="none")
  z = extractor(access_features)
  print("input shape:", tuple(access_features.shape))
  print("Z shape:", tuple(z.shape))

  # 第三阶段最小测试：64 个候选页面来自 LRU 不活跃链表尾部采样。
  candidates = torch.randn(2, 64, 21)
  candidate_scorer = QMAPCandidateScorer(
      hidden_dim=18,
      page_dim=21,
      num_heads=2,
      scoring_input="context")
  eviction_scores = candidate_scorer(z, candidates)
  print("candidates shape:", tuple(candidates.shape))
  print("eviction_scores shape:", tuple(eviction_scores.shape))
