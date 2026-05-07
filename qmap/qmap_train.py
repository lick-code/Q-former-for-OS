# coding=utf-8
"""Training script for QMAP page-migration policy."""

import argparse
import json
import os
import sys

import torch
from torch import optim
from torch.utils.data import DataLoader
from torch.utils.data import Dataset


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from policy_learning.cache_model import embed
from policy_learning.cache_model import model
from policy_learning.cache_model import qmap_loss


class QMAPAccessSequenceDataset(Dataset):
  """Loads complete QMAP training samples from a JSONL file.

  每一行是一个 JSON object，字段如下：
    physical_address: [sequence_length]
    pc: [sequence_length]
    rw: [sequence_length]，0 表示读，1 表示写
    candidates_features: [64, page_dim]
    inactivity: [64]
    coldness: [64]
    write_sensitivity: [64]
    migration_cost: [64]
  """

  REQUIRED_FIELDS = (
      "physical_address",
      "pc",
      "rw",
      "inactivity",
      "coldness",
      "write_sensitivity",
      "migration_cost",
  )

  def __init__(self, jsonl_path):
    self._samples = []
    with open(jsonl_path, "r") as f:
      for line_number, line in enumerate(f, start=1):
        line = line.strip()
        if not line:
          continue
        sample = json.loads(line)
        self._validate_sample(sample, line_number)
        self._samples.append(sample)

    if not self._samples:
      raise ValueError("No QMAP training samples found in {}.".format(
          jsonl_path))

  def __len__(self):
    return len(self._samples)

  def __getitem__(self, index):
    sample = self._samples[index]
    return {
        "physical_address": torch.tensor(
            sample["physical_address"], dtype=torch.long),
        "pc": torch.tensor(sample["pc"], dtype=torch.long),
        "rw": torch.tensor(sample["rw"], dtype=torch.long),
        "candidate_pages": torch.tensor(
            sample.get("candidate_pages", [0] * 64), dtype=torch.long),
        "candidate_state_features": torch.tensor(
            sample.get("candidate_state_features",
                       sample.get("candidates_features")), dtype=torch.float32),
        "candidate_mask": torch.tensor(
            sample.get("candidate_mask", [1] * 64), dtype=torch.float32),
        "legacy_candidates": torch.tensor(
            0 if "candidate_state_features" in sample else 1,
            dtype=torch.long),
        "inactivity": torch.tensor(sample["inactivity"], dtype=torch.float32),
        "coldness": torch.tensor(sample["coldness"], dtype=torch.float32),
        "write_sensitivity": torch.tensor(
            sample["write_sensitivity"], dtype=torch.float32),
        "migration_cost": torch.tensor(
            sample["migration_cost"], dtype=torch.float32),
    }

  @classmethod
  def _validate_sample(cls, sample, line_number):
    missing = [field for field in cls.REQUIRED_FIELDS if field not in sample]
    if missing:
      raise ValueError("Line {} missing fields: {}".format(
          line_number, missing))

    sequence_length = len(sample["physical_address"])
    if not (len(sample["pc"]) == sequence_length and
            len(sample["rw"]) == sequence_length):
      raise ValueError("Line {} has inconsistent sequence lengths.".format(
          line_number))

    if "candidate_state_features" in sample:
      if len(sample.get("candidate_pages", [])) != 64:
        raise ValueError("Line {} must contain exactly 64 candidate pages."
                         .format(line_number))
      if len(sample["candidate_state_features"]) != 64:
        raise ValueError("Line {} must contain exactly 64 candidate states."
                         .format(line_number))
      if len(sample.get("candidate_mask", [])) != 64:
        raise ValueError("Line {} must contain exactly 64 mask values."
                         .format(line_number))
    elif "candidates_features" in sample:
      if len(sample["candidates_features"]) != 64:
        raise ValueError("Line {} must contain exactly 64 candidates.".format(
            line_number))
    else:
      raise ValueError(
          "Line {} must contain candidate_state_features or candidates_features."
          .format(line_number))

    for field in ("inactivity", "coldness", "write_sensitivity",
                  "migration_cost"):
      if len(sample[field]) != 64:
        raise ValueError("Line {} field {} must have length 64.".format(
            line_number, field))


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Train QMAP.")
  parser.add_argument("--train_data", required=True,
                      help="Path to QMAP training JSONL file.")
  parser.add_argument("--output_dir", default="qmap_checkpoints",
                      help="Directory to save .pth checkpoints.")
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--num_workers", type=int, default=0)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--hidden_dim", type=int, default=18)
  parser.add_argument("--address_embed_dim", type=int, default=8)
  parser.add_argument("--pc_embed_dim", type=int, default=8)
  parser.add_argument("--rw_embed_dim", type=int, default=2)
  parser.add_argument("--address_vocab_size", type=int, default=100000)
  parser.add_argument("--pc_vocab_size", type=int, default=50000)
  parser.add_argument("--page_dim", type=int, default=21)
  parser.add_argument("--page_state_dim", type=int, default=3)
  parser.add_argument("--page_embed_dim", type=int, default=8)
  parser.add_argument("--page_vocab_size", type=int, default=100000)
  parser.add_argument("--num_queries", type=int, default=4)
  parser.add_argument("--num_layers", type=int, default=1)
  parser.add_argument("--num_heads", type=int, default=2)
  parser.add_argument("--device", default=None,
                      help="cpu, cuda, or omitted for auto selection.")
  return parser


def move_batch_to_device(batch, device):
  return {key: value.to(device) for key, value in batch.items()}


def save_checkpoint(path, feature_embedder, extractor, scorer, optimizer, epoch,
                    args):
  torch.save({
      "epoch": epoch,
      "model_args": vars(args),
      "feature_embedder": feature_embedder.state_dict(),
      "extractor": extractor.state_dict(),
      "scorer": scorer.state_dict(),
      "optimizer": optimizer.state_dict(),
  }, path)


def main():
  args = build_arg_parser().parse_args()
  os.makedirs(args.output_dir, exist_ok=True)

  device = args.device
  if device is None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
  device = torch.device(device)

  dataset = QMAPAccessSequenceDataset(args.train_data)
  dataloader = DataLoader(
      dataset,
      batch_size=args.batch_size,
      shuffle=True,
      num_workers=args.num_workers,
      drop_last=False)

  print("QMAP training configuration:")
  print("  train_data path:", args.train_data)
  print("  number of training samples:", len(dataset))
  print("  batch_size:", args.batch_size)
  print("  epochs:", args.epochs)
  print("  learning rate:", args.lr)
  print("  device:", device, flush=True)

  feature_embedder = embed.QMAPAccessFeatureEmbedder(
      address_embedder=embed.DynamicVocabEmbedder(
          embed_dim=args.address_embed_dim,
          max_vocab_size=args.address_vocab_size),
      pc_embedder=embed.DynamicVocabEmbedder(
          embed_dim=args.pc_embed_dim,
          max_vocab_size=args.pc_vocab_size),
      rw_embedder=embed.RWFlagEmbedder(embed_dim=args.rw_embed_dim)).to(device)

  if feature_embedder.embed_dim != args.hidden_dim:
    raise ValueError("hidden_dim ({}) must equal embedding concat dim ({})."
                     .format(args.hidden_dim, feature_embedder.embed_dim))

  extractor = model.QMAPMacroscopicPatternExtractor(
      hidden_dim=args.hidden_dim,
      num_queries=args.num_queries,
      num_layers=args.num_layers,
      num_heads=args.num_heads).to(device)
  scorer = model.QMAPCandidateScorer(
      hidden_dim=args.hidden_dim,
      page_state_dim=args.page_state_dim,
      page_embed_dim=args.page_embed_dim,
      page_vocab_size=args.page_vocab_size,
      num_heads=args.num_heads,
      page_dim=args.page_dim).to(device)
  loss_fn = qmap_loss.QMAPCostAwareRankingLoss().to(device)

  parameters = (
      list(feature_embedder.parameters()) +
      list(extractor.parameters()) +
      list(scorer.parameters()))
  optimizer = optim.Adam(parameters, lr=args.lr)

  global_iteration = 0
  for epoch in range(1, args.epochs + 1):
    feature_embedder.train()
    extractor.train()
    scorer.train()

    epoch_loss_sum = 0.0
    epoch_iterations = 0
    for batch in dataloader:
      batch = move_batch_to_device(batch, device)

      access_features = feature_embedder(
          batch["physical_address"], batch["pc"], batch["rw"])
      z = extractor(access_features)
      if torch.any(batch["legacy_candidates"]):
        eviction_scores = scorer(
            z, batch["candidate_state_features"],
            candidate_mask=batch["candidate_mask"])
      else:
        eviction_scores = scorer(
            z,
            batch["candidate_pages"],
            batch["candidate_state_features"],
            batch["candidate_mask"])

      loss = loss_fn(
          eviction_scores,
          batch["inactivity"],
          batch["coldness"],
          batch["write_sensitivity"],
          batch["migration_cost"],
          batch["candidate_mask"])

      optimizer.zero_grad()
      loss.backward()
      torch.nn.utils.clip_grad_norm_(parameters, max_norm=10.0)
      optimizer.step()

      global_iteration += 1
      epoch_iterations += 1
      epoch_loss_sum += loss.item()

      if epoch_iterations == 1:
        print("Epoch [{}/{}] iter={} loss={:.6f}".format(
            epoch, args.epochs, global_iteration, loss.item()), flush=True)
      if global_iteration % 100 == 0:
        print("Epoch [{}/{}] iter={} loss={:.6f}".format(
            epoch, args.epochs, global_iteration, loss.item()), flush=True)

    avg_loss = epoch_loss_sum / max(1, epoch_iterations)
    print("Epoch [{}/{}] avg_loss={:.6f}".format(
        epoch, args.epochs, avg_loss), flush=True)

    checkpoint_path = os.path.join(
        args.output_dir, "qmap_epoch_{}.pth".format(epoch))
    save_checkpoint(
        checkpoint_path, feature_embedder, extractor, scorer, optimizer, epoch,
        args)
    print("Saved checkpoint:", checkpoint_path, flush=True)

  print("Training finished.", flush=True)


if __name__ == "__main__":
  main()
