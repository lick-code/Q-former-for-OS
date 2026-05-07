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

"""QMAP data utilities for global memory-page migration.

本文件是 QMAP 的新数据入口，不再构造 PARROT 的 Cache Set / Cache Way /
Cache Line 替换样本。每个样本是一段全局访存序列：
  - physical_addresses: 物理地址序列
  - pcs: 程序计数器序列
  - rw_flags: 读写标志序列，0 表示读，1 表示写
"""

import torch
from torch.utils.data import DataLoader
from torch.utils.data import Dataset

try:
  from cache_replacement.policy_learning.cache_model import embed
except ImportError:
  # 允许直接执行本文件：python policy_learning/cache_model/qmap_data.py
  import embed


class QMAPAccessSequenceDataset(Dataset):
  """Dataset for QMAP memory-access sequences."""

  def __init__(self, physical_address_sequences, pc_sequences,
               rw_flag_sequences):
    if not (len(physical_address_sequences) == len(pc_sequences) ==
            len(rw_flag_sequences)):
      raise ValueError("Address, PC, and RW sequence counts must match.")

    self._physical_address_sequences = physical_address_sequences
    self._pc_sequences = pc_sequences
    self._rw_flag_sequences = rw_flag_sequences

  def __len__(self):
    return len(self._physical_address_sequences)

  def __getitem__(self, index):
    physical_addresses = torch.tensor(
        self._physical_address_sequences[index], dtype=torch.long)
    pcs = torch.tensor(self._pc_sequences[index], dtype=torch.long)
    rw_flags = torch.tensor(self._rw_flag_sequences[index], dtype=torch.long)

    if not (physical_addresses.shape == pcs.shape == rw_flags.shape):
      raise ValueError("Address, PC, and RW sequences must have same length.")
    if torch.any((rw_flags < 0) | (rw_flags > 1)):
      raise ValueError("RW flags must be 0 for read or 1 for write.")

    return {
        "physical_address": physical_addresses,
        "pc": pcs,
        "rw": rw_flags,
    }


if __name__ == "__main__":
  # 构造一组最小假数据：3 条样本，每条样本长度为 4。
  dataset = QMAPAccessSequenceDataset(
      physical_address_sequences=[
          [0x1000, 0x2000, 0x3000, 0x4000],
          [0x2000, 0x3000, 0x5000, 0x8000],
          [0x1000, 0x6000, 0x7000, 0x9000],
      ],
      pc_sequences=[
          [0x10, 0x11, 0x12, 0x13],
          [0x20, 0x21, 0x22, 0x23],
          [0x30, 0x31, 0x32, 0x33],
      ],
      rw_flag_sequences=[
          [0, 1, 0, 1],
          [1, 0, 0, 1],
          [0, 0, 1, 1],
      ])

  dataloader = DataLoader(dataset, batch_size=2, shuffle=False)
  batch = next(iter(dataloader))

  # 三路 Embedding 维度均可配置；这里用小维度方便肉眼检查。
  feature_embedder = embed.QMAPAccessFeatureEmbedder(
      address_embedder=embed.DynamicVocabEmbedder(
          embed_dim=8, max_vocab_size=1024),
      pc_embedder=embed.DynamicVocabEmbedder(embed_dim=8, max_vocab_size=1024),
      rw_embedder=embed.RWFlagEmbedder(embed_dim=2))

  joint_features = feature_embedder(
      batch["physical_address"], batch["pc"], batch["rw"])

  print("First batch:")
  print(batch)
  print("physical_address shape:", tuple(batch["physical_address"].shape))
  print("pc shape:", tuple(batch["pc"].shape))
  print("rw shape:", tuple(batch["rw"].shape))
  print("joint feature shape:", tuple(joint_features.shape))
