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

"""QMAP-specific cost-aware ranking losses."""

import torch
from torch import nn


class QMAPCostAwareRankingLoss(nn.Module):
  """Cost-aware ApproxNDCG ranking loss for QMAP page migration.

  The reference relevance score follows the method section:

    y = lambda_1 * inactivity + lambda_2 * coldness
        - lambda_3 * write_sensitivity - lambda_4 * migration_cost

  Scores are optimized with a differentiable NDCG approximation so that the
  whole candidate list, not just the top-1 page, contributes to training.
  """

  def __init__(self, lambda_1=1.0, lambda_2=1.0, lambda_3=1.0, lambda_4=1.0,
               alpha=10.0):
    super(QMAPCostAwareRankingLoss, self).__init__()
    self._lambda_1 = lambda_1
    self._lambda_2 = lambda_2
    self._lambda_3 = lambda_3
    self._lambda_4 = lambda_4
    self._alpha = alpha

  def forward(self, eviction_scores, inactivity, coldness, write_sensitivity,
              migration_cost, candidate_mask=None):
    """Computes the scalar ApproxNDCG loss.

    Args:
      eviction_scores: model scores, shape [batch_size, num_candidates].
      inactivity: future inactivity degree, same shape as eviction_scores.
      coldness: coldness score, same shape as eviction_scores.
      write_sensitivity: write-sensitivity score, same shape as scores.
      migration_cost: cross-tier migration cost, same shape as scores.
      candidate_mask: optional 1/0 mask for real/padded candidates.

    Returns:
      A scalar tensor. Lower is better.
    """
    expected_shape = eviction_scores.shape
    for name, tensor in (
        ("inactivity", inactivity),
        ("coldness", coldness),
        ("write_sensitivity", write_sensitivity),
        ("migration_cost", migration_cost)):
      if tensor.shape != expected_shape:
        raise ValueError("{} shape {} must match eviction_scores shape {}."
                         .format(name, tensor.shape, expected_shape))

    if candidate_mask is None:
      candidate_mask = torch.ones_like(eviction_scores)
    candidate_mask = candidate_mask.to(eviction_scores.device).float()
    if candidate_mask.shape != expected_shape:
      raise ValueError("candidate_mask shape {} must match scores shape {}."
                       .format(candidate_mask.shape, expected_shape))

    relevance = (
        self._lambda_1 * inactivity +
        self._lambda_2 * coldness -
        self._lambda_3 * write_sensitivity -
        self._lambda_4 * migration_cost)
    relevance = self._normalize_relevance(relevance, candidate_mask)

    masked_scores = eviction_scores.masked_fill(
        candidate_mask <= 0, torch.finfo(eviction_scores.dtype).min)
    return self._approx_ndcg_loss(masked_scores, relevance, candidate_mask)

  @staticmethod
  def _normalize_relevance(relevance, mask):
    """Normalizes each sample's valid relevance values into [0, 1]."""
    large = torch.finfo(relevance.dtype).max
    valid_min = relevance.masked_fill(mask <= 0, large).min(
        dim=1, keepdim=True).values
    valid_max = relevance.masked_fill(mask <= 0, -large).max(
        dim=1, keepdim=True).values
    denom = torch.clamp(valid_max - valid_min, min=1e-8)
    normalized = (relevance - valid_min) / denom
    return normalized.masked_fill(mask <= 0, 0.0)

  def _approx_ndcg_loss(self, scores, relevance, mask):
    """Differentiable NDCG approximation with soft item positions."""
    score_i = scores.unsqueeze(2)
    score_j = scores.unsqueeze(1)
    pair_mask = mask.unsqueeze(2) * mask.unsqueeze(1)

    # 1-based approximate position: one plus the expected number of valid
    # candidates with a higher score than item i.
    higher_prob = torch.sigmoid(self._alpha * (score_j - score_i)) * pair_mask
    approx_pos = 1.0 + higher_prob.sum(dim=2)

    gains = torch.expm1(relevance) * mask
    dcg = (gains / torch.log1p(approx_pos)).sum(dim=1)

    sorted_gains, _ = torch.sort(gains, dim=1, descending=True)
    positions = torch.arange(
        1, scores.shape[1] + 1, device=scores.device,
        dtype=scores.dtype).unsqueeze(0)
    idcg = (sorted_gains / torch.log1p(positions)).sum(dim=1)
    ndcg = dcg / (idcg + 1e-8)
    return -ndcg.mean()


if __name__ == "__main__":
  eviction_scores = torch.randn(2, 64)
  inactivity = torch.randn(2, 64)
  coldness = torch.randn(2, 64)
  write_sensitivity = torch.randn(2, 64)
  migration_cost = torch.randn(2, 64)
  candidate_mask = torch.ones(2, 64)

  loss_fn = QMAPCostAwareRankingLoss()
  loss = loss_fn(
      eviction_scores,
      inactivity,
      coldness,
      write_sensitivity,
      migration_cost,
      candidate_mask)
  print("loss:", loss)
  print("loss shape:", tuple(loss.shape))
