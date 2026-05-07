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
import torch
from torch import distributions as td
from torch import nn
from torch.nn import functional as F

try:
  from cache_replacement.policy_learning.cache_model import embed
  from cache_replacement.policy_learning.cache_model import loss as L
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

  def forward(self, encoded_accesses):
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
    attended, _ = self._cross_attention(
        query=query_seq, key=key_value_seq, value=key_value_seq)
    attended = attended.transpose(0, 1)
    return self._norm(attended + queries)


class QMAPMacroscopicPatternExtractor(nn.Module):
  """QMAP 第二阶段：TransformerEncoder + Q-Former 宏观模式提取。

  输入来自第一阶段的联合访存特征：
    [batch_size, sequence_length, hidden_dim]

  输出为 K 个宏观模式向量：
    [batch_size, num_queries, hidden_dim]
  """

  def __init__(self, hidden_dim=18, num_queries=4, num_layers=1, num_heads=2,
               feedforward_dim=None, dropout=0.0):
    """Constructs the QMAP macroscopic pattern extractor.

    Args:
      hidden_dim (int): 输入特征维度，默认匹配第一阶段测试中的 18。
      num_queries (int): Q-Former 可学习 Query 数量 K。
      num_layers (int): TransformerEncoder 层数。
      num_heads (int): Transformer 和 Q-Former 的 attention head 数。
      feedforward_dim (int | None): Transformer FFN 中间维度。
      dropout (float): dropout rate。
    """
    super(QMAPMacroscopicPatternExtractor, self).__init__()
    if hidden_dim % num_heads != 0:
      raise ValueError("hidden_dim must be divisible by num_heads.")

    if feedforward_dim is None:
      feedforward_dim = hidden_dim * 4

    encoder_layer = nn.TransformerEncoderLayer(
        d_model=hidden_dim,
        nhead=num_heads,
        dim_feedforward=feedforward_dim,
        dropout=dropout,
        activation="gelu")
    self._transformer_encoder = nn.TransformerEncoder(
        encoder_layer, num_layers=num_layers)
    self._qformer = QFormer(
        hidden_dim=hidden_dim,
        num_queries=num_queries,
        num_heads=num_heads,
        dropout=dropout)

  def forward(self, access_features):
    """Extracts macroscopic access patterns.

    Args:
      access_features (torch.FloatTensor): 第一阶段输出，
        形状为 [batch_size, sequence_length, hidden_dim]。

    Returns:
      torch.FloatTensor: Q-Former 输出 Z，
        形状为 [batch_size, num_queries, hidden_dim]。
    """
    sequence_length = access_features.shape[1]
    causal_mask = self._causal_mask(
        sequence_length, device=access_features.device)

    # TransformerEncoder 默认接收 [sequence_length, batch_size, hidden_dim]。
    sequence_first = access_features.transpose(0, 1)
    encoded = self._transformer_encoder(sequence_first, mask=causal_mask)
    encoded = encoded.transpose(0, 1)
    return self._qformer(encoded)

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

  This implementation follows the QMAP method section: each candidate page is
  represented by a learned page-id embedding concatenated with lightweight
  page-state features, then matched against the Q-Former global access
  representations and scored by a small MLP.
  """

  def __init__(self, hidden_dim=18, page_state_dim=3, page_embed_dim=8,
               page_vocab_size=100000, num_heads=2, mlp_hidden_dim=None,
               dropout=0.0, page_dim=None):
    super(QMAPCandidateScorer, self).__init__()
    if hidden_dim % num_heads != 0:
      raise ValueError("hidden_dim must be divisible by num_heads.")

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
    self._scoring_mlp = nn.Sequential(
        nn.Linear(hidden_dim * 2, mlp_hidden_dim),
        nn.ReLU(),
        nn.Dropout(dropout),
        nn.Linear(mlp_hidden_dim, mlp_hidden_dim // 2),
        nn.ReLU(),
        nn.Linear(mlp_hidden_dim // 2, 1))

  def forward(self, z, candidate_pages, candidate_state_features=None,
              candidate_mask=None):
    """Scores candidates.

    Args:
      z: Q-Former output with shape [batch_size, K, hidden_dim].
      candidate_pages: candidate page ids [batch_size, num_candidates]. If
        candidate_state_features is None, this is treated as a legacy
        handcrafted feature tensor.
      candidate_state_features: [recent frequency, dirty flag, residency
        duration] features with shape [batch_size, num_candidates, 3].
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
      page_embeddings = self._page_embedder(candidate_pages.long())
      candidate_inputs = torch.cat(
          (page_embeddings, candidate_state_features), dim=-1)
      u = self._candidate_projector(candidate_inputs)

    query_seq = u.transpose(0, 1)
    key_value_seq = z.transpose(0, 1)
    g, _ = self._cross_attention(
        query=query_seq, key=key_value_seq, value=key_value_seq)
    g = g.transpose(0, 1)
    g = self._context_norm(g + u)

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
      num_heads=2)
  z = extractor(access_features)
  print("input shape:", tuple(access_features.shape))
  print("Z shape:", tuple(z.shape))

  # 第三阶段最小测试：64 个候选页面来自 LRU 不活跃链表尾部采样。
  candidates = torch.randn(2, 64, 21)
  candidate_scorer = QMAPCandidateScorer(
      hidden_dim=18,
      page_dim=21,
      num_heads=2)
  eviction_scores = candidate_scorer(z, candidates)
  print("candidates shape:", tuple(candidates.shape))
  print("eviction_scores shape:", tuple(eviction_scores.shape))
