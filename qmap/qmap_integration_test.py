# coding=utf-8
"""End-to-end smoke test for the QMAP pipeline."""

import os
import sys

import torch
from torch.utils.data import DataLoader


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from policy_learning.cache_model import embed
from policy_learning.cache_model import model
from policy_learning.cache_model import qmap_data
from policy_learning.cache_model import qmap_loss


def _assert_finite_gradients(modules, max_norm=1e6):
  """Checks gradients are finite and not obviously exploding."""
  total_norm = torch.tensor(0.0)
  for module in modules:
    for parameter in module.parameters():
      if parameter.grad is None:
        continue
      if not torch.all(torch.isfinite(parameter.grad)):
        raise RuntimeError("Detected non-finite gradient.")
      total_norm = total_norm + parameter.grad.detach().norm(2) ** 2

  total_norm = torch.sqrt(total_norm)
  if total_norm.item() > max_norm:
    raise RuntimeError("Gradient norm is too large: {}".format(
        total_norm.item()))


def main():
  torch.manual_seed(0)

  # 1. 输入层：全局访存序列，不包含 Cache Set / Cache Way。
  dataset = qmap_data.QMAPAccessSequenceDataset(
      physical_address_sequences=[
          [0x1000, 0x2000, 0x3000, 0x4000],
          [0x2000, 0x3000, 0x5000, 0x8000],
          [0x1000, 0x6000, 0x7000, 0x9000],
          [0x1100, 0x2100, 0x3100, 0x4100],
      ],
      pc_sequences=[
          [0x10, 0x11, 0x12, 0x13],
          [0x20, 0x21, 0x22, 0x23],
          [0x30, 0x31, 0x32, 0x33],
          [0x40, 0x41, 0x42, 0x43],
      ],
      rw_flag_sequences=[
          [0, 1, 0, 1],
          [1, 0, 0, 1],
          [0, 0, 1, 1],
          [1, 1, 0, 0],
      ])
  dataloader = DataLoader(dataset, batch_size=2, shuffle=False)
  batch = next(iter(dataloader))

  feature_embedder = embed.QMAPAccessFeatureEmbedder(
      address_embedder=embed.DynamicVocabEmbedder(
          embed_dim=8, max_vocab_size=1024),
      pc_embedder=embed.DynamicVocabEmbedder(embed_dim=8, max_vocab_size=1024),
      rw_embedder=embed.RWFlagEmbedder(embed_dim=2))

  access_features = feature_embedder(
      batch["physical_address"], batch["pc"], batch["rw"])

  # 2. 宏观模式提取：Transformer Encoder + Q-Former。
  pattern_extractor = model.QMAPMacroscopicPatternExtractor(
      hidden_dim=18,
      num_queries=4,
      num_layers=1,
      num_heads=2,
      use_qformer=False,
      pooling_strategy="mean")
  z = pattern_extractor(access_features)

  # 3. 64 页面候选池打分。
  candidate_scorer = model.QMAPCandidateScorer(
      hidden_dim=18,
      page_state_dim=3,
      num_heads=2)
  candidate_pages = torch.randint(1, 4096, (2, 64))
  candidate_state_features = torch.randn(2, 64, 3)
  candidate_mask = torch.ones(2, 64)
  eviction_scores = candidate_scorer(
      z, candidate_pages, candidate_state_features, candidate_mask)

  # 4. 代价感知 ListNet 排序损失。
  loss_fn = qmap_loss.QMAPCostAwareRankingLoss()
  inactivity = torch.randn(2, 64)
  coldness = torch.randn(2, 64)
  write_sensitivity = torch.randn(2, 64)
  migration_cost = torch.randn(2, 64)

  # 5. 完整 forward + backward。
  loss = loss_fn(
      eviction_scores,
      inactivity,
      coldness,
      write_sensitivity,
      migration_cost,
      candidate_mask)
  loss.backward()

  _assert_finite_gradients(
      [feature_embedder, pattern_extractor, candidate_scorer])

  print("access_features shape:", tuple(access_features.shape))
  print("Z shape:", tuple(z.shape))
  print("eviction_scores shape:", tuple(eviction_scores.shape))
  print("loss:", loss.item())
  print("QMAP Pipeline Integration Successful!")


if __name__ == "__main__":
  main()
