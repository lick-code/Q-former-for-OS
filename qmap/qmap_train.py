# coding=utf-8
"""Train the QMAP reranker, including the strict CAPD finals_v2 path."""

from __future__ import print_function

import argparse
import json
import math
import os
import random
import shlex
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
from qmap import finals_config


ABLATION_CHOICES = (
    "full", "cross_attention", "no_pc", "no_rw", "mean_pool",
    "no_qformer", "no_cost")


class QMAPAccessSequenceDataset(Dataset):
  """Loads and validates complete QMAP JSONL samples."""

  REQUIRED_FIELDS = (
      "physical_address", "pc", "rw", "inactivity", "coldness",
      "write_sensitivity", "migration_cost")

  def __init__(self, jsonl_path, expected_shape=None):
    self._samples = []
    self._expected_shape = expected_shape
    with open(jsonl_path, "r", encoding="utf-8") as input_file:
      for line_number, line in enumerate(input_file, start=1):
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
    state_features = sample.get(
        "candidate_state_features", sample.get("candidates_features"))
    candidate_count = len(state_features)
    return {
        "physical_address": torch.tensor(
            sample["physical_address"], dtype=torch.long),
        "pc": torch.tensor(sample["pc"], dtype=torch.long),
        "rw": torch.tensor(sample["rw"], dtype=torch.long),
        "candidate_pages": torch.tensor(
            sample.get("candidate_pages", [0] * candidate_count),
            dtype=torch.long),
        "candidate_state_features": torch.tensor(
            state_features, dtype=torch.float32),
        "candidate_mask": torch.tensor(
            sample.get("candidate_mask", [1] * candidate_count),
            dtype=torch.float32),
        "legacy_candidates": torch.tensor(
            0 if "candidate_state_features" in sample else 1,
            dtype=torch.long),
        "inactivity": torch.tensor(
            sample["inactivity"], dtype=torch.float32),
        "coldness": torch.tensor(sample["coldness"], dtype=torch.float32),
        "write_sensitivity": torch.tensor(
            sample["write_sensitivity"], dtype=torch.float32),
        "migration_cost": torch.tensor(
            sample["migration_cost"], dtype=torch.float32),
    }

  def _validate_sample(self, sample, line_number):
    missing = [field for field in self.REQUIRED_FIELDS if field not in sample]
    if missing:
      raise ValueError("Line {} missing fields: {}".format(
          line_number, missing))
    sequence_length = len(sample["physical_address"])
    if not (len(sample["pc"]) == sequence_length and
            len(sample["rw"]) == sequence_length):
      raise ValueError("Line {} has inconsistent sequence lengths.".format(
          line_number))

    state_features = sample.get(
        "candidate_state_features", sample.get("candidates_features"))
    if state_features is None or not state_features:
      raise ValueError("Line {} has no candidate features.".format(
          line_number))
    candidate_count = len(state_features)
    state_dim = len(state_features[0])
    if any(len(row) != state_dim for row in state_features):
      raise ValueError("Line {} has ragged candidate features.".format(
          line_number))
    if "candidate_state_features" in sample:
      if len(sample.get("candidate_pages", [])) != candidate_count:
        raise ValueError("Line {} candidate_pages length mismatch.".format(
            line_number))
      if len(sample.get("candidate_mask", [])) != candidate_count:
        raise ValueError("Line {} candidate_mask length mismatch.".format(
            line_number))
    for field in ("inactivity", "coldness", "write_sensitivity",
                  "migration_cost"):
      if len(sample[field]) != candidate_count:
        raise ValueError("Line {} field {} length mismatch.".format(
            line_number, field))

    if self._expected_shape:
      expected = self._expected_shape
      actual = {"H": sequence_length, "K": candidate_count,
                "page_state_dim": state_dim}
      finals_config.assert_contract_matches(expected, actual,
                                             "JSONL line {}".format(
                                                 line_number))
      if sample.get("schema_version") != finals_config.SCHEMA_VERSION:
        raise ValueError("Line {} is not a finals_v2 sample.".format(
            line_number))


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Train QMAP.")
  parser.add_argument("--train_data", required=True)
  parser.add_argument("--valid_data", default=None)
  parser.add_argument("--config", default=None,
                      help="Resolved CAPD finals_v2 config.")
  parser.add_argument("--selector_params", default=None)
  parser.add_argument("--output_dir", default="qmap_checkpoints")
  parser.add_argument("--epochs", type=int, default=10)
  parser.add_argument("--batch_size", type=int, default=32)
  parser.add_argument("--num_workers", type=int, default=0)
  parser.add_argument("--lr", type=float, default=1e-4)
  parser.add_argument("--weight_decay", type=float, default=0.0)
  parser.add_argument("--inactivity_weight", type=float, default=1.0)
  parser.add_argument("--coldness_weight", type=float, default=1.0)
  parser.add_argument("--write_sensitivity_weight", type=float, default=4.0)
  parser.add_argument("--migration_cost_weight", type=float, default=2.0)
  parser.add_argument("--hidden_dim", type=int, default=18)
  parser.add_argument("--address_embed_dim", type=int, default=8)
  parser.add_argument("--pc_embed_dim", type=int, default=8)
  parser.add_argument("--rw_embed_dim", type=int, default=2)
  parser.add_argument("--address_vocab_size", type=int, default=100000)
  parser.add_argument("--pc_vocab_size", type=int, default=50000)
  parser.add_argument("--page_dim", type=int, default=21)
  parser.add_argument("--page_state_dim", type=int, default=4)
  parser.add_argument("--page_embed_dim", type=int, default=8)
  parser.add_argument("--page_vocab_size", type=int, default=100000)
  parser.add_argument("--num_queries", type=int, default=4)
  parser.add_argument("--num_layers", type=int, default=1)
  parser.add_argument("--num_heads", type=int, default=2)
  parser.add_argument("--feedforward_dim", type=int, default=None)
  parser.add_argument("--dropout", type=float, default=0.0)
  parser.add_argument("--device", default=None)
  parser.add_argument("--seed", type=int, default=3136859)
  parser.add_argument("--ablation", choices=ABLATION_CHOICES,
                      default="cross_attention")
  return parser


def set_random_seed(seed):
  random.seed(seed)
  torch.manual_seed(seed)
  if torch.cuda.is_available():
    torch.cuda.manual_seed_all(seed)


def move_batch_to_device(batch, device):
  return {key: value.to(device) for key, value in batch.items()}


def apply_batch_ablation(batch, ablation):
  if ablation == "no_pc":
    batch["pc"] = torch.zeros_like(batch["pc"])
  elif ablation == "no_rw":
    batch["rw"] = torch.zeros_like(batch["rw"])
  return batch


def uses_qformer(ablation):
  return ablation == "full"


def extractor_pooling_strategy(ablation):
  return "none" if ablation in (
      "cross_attention", "no_pc", "no_rw", "no_cost") else "mean"


def scorer_scoring_input(ablation):
  return "context" if ablation in (
      "cross_attention", "no_pc", "no_rw", "no_cost") else "concat"


def _command_text():
  return " ".join(shlex.quote(value) for value in sys.argv)


def _validate_finals_artifacts(config, config_path, selector_path,
                               train_path, valid_path):
  if not selector_path or not valid_path:
    raise ValueError(
        "--selector_params and --valid_data are required with --config.")
  selector_params = finals_config.load_json(selector_path)
  expected_config_fingerprint = finals_config.config_fingerprint(config)
  if selector_params.get("config_fingerprint") != expected_config_fingerprint:
    raise ValueError("selector_params/config fingerprint mismatch.")
  if selector_params.get("workload") != config["run"]["workload"]:
    raise ValueError("selector_params/workload mismatch.")
  selector_fingerprint = finals_config.selector_fingerprint(selector_params)
  contract = finals_config.contract_from_config(config)
  expected_shape = {
      "H": contract["H"], "K": contract["K"],
      "page_state_dim": contract["page_state_dim"]}
  metadata_by_split = {}
  for split, path in (("train", train_path), ("valid", valid_path)):
    metadata = finals_config.load_jsonl_metadata(path)
    if metadata.get("split") != split:
      raise ValueError("{} JSONL split metadata mismatch.".format(split))
    if metadata.get("workload") != config["run"]["workload"]:
      raise ValueError("{} JSONL workload mismatch.".format(split))
    if metadata.get("config_fingerprint") != expected_config_fingerprint:
      raise ValueError("{} JSONL config fingerprint mismatch.".format(split))
    if metadata.get("selector_fingerprint") != selector_fingerprint:
      raise ValueError("{} JSONL selector fingerprint mismatch.".format(
          split))
    finals_config.assert_contract_matches(
        contract, metadata.get("experiment_contract", {}),
        "{} JSONL".format(split))
    finals_config.assert_contract_matches(
        expected_shape, metadata.get("shape", {}),
        "{} JSONL shape".format(split))
    metadata_by_split[split] = metadata
  return {
      "config": config,
      "config_path": os.path.abspath(config_path),
      "config_fingerprint": expected_config_fingerprint,
      "contract": contract,
      "selector_params": selector_params,
      "selector_fingerprint": selector_fingerprint,
      "metadata": metadata_by_split,
      "expected_shape": expected_shape,
  }


def apply_finals_config(args):
  if not args.config:
    return None
  config = finals_config.load_config(args.config, require_resolved=True)
  training = config["training"]
  labels = config["labels"]
  args.seed = int(training["seed"])
  args.epochs = int(training.get("epochs", args.epochs))
  args.batch_size = int(training.get("batch_size", args.batch_size))
  args.lr = float(training.get("learning_rate", args.lr))
  args.page_state_dim = int(config["features"]["page_state_dim"])
  args.inactivity_weight = float(labels["lambda_d"])
  args.coldness_weight = float(labels["lambda_q"])
  args.write_sensitivity_weight = float(labels["lambda_w"])
  args.migration_cost_weight = 0.0
  if args.ablation != "cross_attention":
    raise ValueError("Finals direction-1 training requires cross_attention.")
  return _validate_finals_artifacts(
      config, args.config, args.selector_params, args.train_data,
      args.valid_data)


def _forward_loss(batch, feature_embedder, extractor, scorer, loss_fn,
                  ablation):
  batch = apply_batch_ablation(batch, ablation)
  access_features = feature_embedder(
      batch["physical_address"], batch["pc"], batch["rw"])
  z = extractor(access_features)
  if (batch["legacy_candidates"] != 0).any():
    eviction_scores = scorer(
        z, batch["candidate_state_features"],
        candidate_mask=batch["candidate_mask"])
  else:
    eviction_scores = scorer(
        z, batch["candidate_pages"], batch["candidate_state_features"],
        batch["candidate_mask"])
  return loss_fn(
      eviction_scores, batch["inactivity"], batch["coldness"],
      batch["write_sensitivity"], batch["migration_cost"],
      batch["candidate_mask"])


def evaluate_loss(dataloader, device, feature_embedder, extractor, scorer,
                  loss_fn, ablation):
  feature_embedder.eval()
  extractor.eval()
  scorer.eval()
  loss_sum = 0.0
  iterations = 0
  with torch.no_grad():
    for batch in dataloader:
      batch = move_batch_to_device(batch, device)
      loss = _forward_loss(
          batch, feature_embedder, extractor, scorer, loss_fn, ablation)
      loss_sum += loss.item()
      iterations += 1
  return loss_sum / max(1, iterations)


def checkpoint_payload(feature_embedder, extractor, scorer, optimizer, epoch,
                       validation_loss, args, finals_context):
  payload = {
      "epoch": epoch,
      "validation_loss": validation_loss,
      "model_args": vars(args).copy(),
      "feature_embedder": feature_embedder.state_dict(),
      "extractor": extractor.state_dict(),
      "scorer": scorer.state_dict(),
      "optimizer": optimizer.state_dict(),
  }
  if finals_context:
    payload.update({
        "schema_version": finals_config.SCHEMA_VERSION,
        "experiment_contract": finals_context["contract"],
        "config_fingerprint": finals_context["config_fingerprint"],
        "selector_params": finals_context["selector_params"],
        "selector_fingerprint": finals_context["selector_fingerprint"],
        "workload": finals_context["config"]["run"]["workload"],
        "seed": args.seed,
        "jsonl_fingerprints": {
            split: metadata["data_fingerprint"]
            for split, metadata in finals_context["metadata"].items()
        },
        "git_commit": finals_context["config"].get(
            "run", {}).get("git_commit", "unknown"),
        "command": _command_text(),
    })
  return payload


def main():
  args = build_arg_parser().parse_args()
  finals_context = apply_finals_config(args)
  os.makedirs(args.output_dir, exist_ok=True)
  if finals_context:
    finals_config.write_json(
        os.path.join(args.output_dir, "resolved_config.json"),
        finals_context["config"])
  set_random_seed(args.seed)

  device_name = args.device
  if device_name is None:
    device_name = "cuda" if torch.cuda.is_available() else "cpu"
  device = torch.device(device_name)
  expected_shape = finals_context["expected_shape"] if finals_context else None
  train_dataset = QMAPAccessSequenceDataset(
      args.train_data, expected_shape=expected_shape)
  valid_dataset = (QMAPAccessSequenceDataset(
      args.valid_data, expected_shape=expected_shape)
                   if args.valid_data else None)
  train_loader = DataLoader(
      train_dataset, batch_size=args.batch_size, shuffle=True,
      num_workers=args.num_workers, drop_last=False)
  valid_loader = (DataLoader(
      valid_dataset, batch_size=args.batch_size, shuffle=False,
      num_workers=args.num_workers, drop_last=False)
                  if valid_dataset else None)

  args.pooling_strategy = extractor_pooling_strategy(args.ablation)
  args.scoring_input = scorer_scoring_input(args.ablation)
  print("QMAP training: train={} valid={} samples={}/{} device={}".format(
      args.train_data, args.valid_data, len(train_dataset),
      len(valid_dataset) if valid_dataset else 0, device), flush=True)

  feature_embedder = embed.QMAPAccessFeatureEmbedder(
      address_embedder=embed.DynamicVocabEmbedder(
          embed_dim=args.address_embed_dim,
          max_vocab_size=args.address_vocab_size),
      pc_embedder=embed.DynamicVocabEmbedder(
          embed_dim=args.pc_embed_dim, max_vocab_size=args.pc_vocab_size),
      rw_embedder=embed.RWFlagEmbedder(embed_dim=args.rw_embed_dim)).to(device)
  if feature_embedder.embed_dim != args.hidden_dim:
    raise ValueError("hidden_dim ({}) must equal embedding dimension ({})."
                     .format(args.hidden_dim, feature_embedder.embed_dim))
  extractor = model.QMAPMacroscopicPatternExtractor(
      hidden_dim=args.hidden_dim, num_queries=args.num_queries,
      num_layers=args.num_layers, num_heads=args.num_heads,
      feedforward_dim=args.feedforward_dim, dropout=args.dropout,
      use_qformer=uses_qformer(args.ablation),
      pooling_strategy=args.pooling_strategy).to(device)
  scorer = model.QMAPCandidateScorer(
      hidden_dim=args.hidden_dim, page_state_dim=args.page_state_dim,
      page_embed_dim=args.page_embed_dim,
      page_vocab_size=args.page_vocab_size, num_heads=args.num_heads,
      dropout=args.dropout, page_dim=args.page_dim,
      scoring_input=args.scoring_input).to(device)
  loss_fn = qmap_loss.QMAPCostAwareRankingLoss(
      lambda_1=args.inactivity_weight,
      lambda_2=args.coldness_weight,
      lambda_3=0.0 if args.ablation == "no_cost" else (
          args.write_sensitivity_weight),
      lambda_4=0.0 if args.ablation == "no_cost" else (
          args.migration_cost_weight)).to(device)
  parameters = (list(feature_embedder.parameters()) +
                list(extractor.parameters()) + list(scorer.parameters()))
  optimizer = optim.AdamW(
      parameters, lr=args.lr, weight_decay=args.weight_decay)

  best_loss = float("inf")
  best_epoch = None
  global_iteration = 0
  last_path = os.path.join(args.output_dir, "qmap_last.pth")
  best_path = os.path.join(args.output_dir, "qmap_best.pth")
  for epoch in range(1, args.epochs + 1):
    feature_embedder.train()
    extractor.train()
    scorer.train()
    loss_sum = 0.0
    iterations = 0
    for batch in train_loader:
      batch = move_batch_to_device(batch, device)
      loss = _forward_loss(
          batch, feature_embedder, extractor, scorer, loss_fn, args.ablation)
      optimizer.zero_grad()
      loss.backward()
      torch.nn.utils.clip_grad_norm_(parameters, max_norm=10.0)
      optimizer.step()
      global_iteration += 1
      iterations += 1
      loss_sum += loss.item()
      if global_iteration == 1 or global_iteration % 100 == 0:
        print("epoch={}/{} iter={} loss={:.6f}".format(
            epoch, args.epochs, global_iteration, loss.item()), flush=True)
    train_loss = loss_sum / max(1, iterations)
    validation_loss = (evaluate_loss(
        valid_loader, device, feature_embedder, extractor, scorer, loss_fn,
        args.ablation) if valid_loader else train_loss)
    if not math.isfinite(train_loss) or not math.isfinite(validation_loss):
      raise ValueError("Non-finite training or validation loss detected.")
    payload = checkpoint_payload(
        feature_embedder, extractor, scorer, optimizer, epoch,
        validation_loss, args, finals_context)
    torch.save(payload, last_path)
    if finals_context is None:
      # Preserve historical experiment-script checkpoint names outside the
      # isolated finals_v2 path.
      torch.save(payload, os.path.join(
          args.output_dir, "qmap_epoch_{}.pth".format(epoch)))
    if validation_loss < best_loss:
      best_loss = validation_loss
      best_epoch = epoch
      torch.save(payload, best_path)
    print("epoch={}/{} train_loss={:.6f} valid_loss={:.6f}".format(
        epoch, args.epochs, train_loss, validation_loss), flush=True)

  manifest = {
      "schema_version": (finals_config.SCHEMA_VERSION
                         if finals_context else "legacy_qmap"),
      "best_epoch": best_epoch,
      "best_validation_loss": best_loss,
      "checkpoints": {
          "last": {"path": os.path.abspath(last_path),
                   "fingerprint": finals_config.fingerprint_file(last_path)},
          "best": {"path": os.path.abspath(best_path),
                   "fingerprint": finals_config.fingerprint_file(best_path)},
      },
      "config_fingerprint": (finals_context["config_fingerprint"]
                             if finals_context else None),
      "git_commit": (finals_context["config"].get("run", {}).get(
          "git_commit", "unknown") if finals_context else
                     finals_config.current_git_commit(PROJECT_ROOT)),
      "command": _command_text(),
  }
  finals_config.write_json(
      os.path.join(args.output_dir, "checkpoint_manifest.json"), manifest)
  print("Training finished. best={} last={}".format(
      best_path, last_path), flush=True)


if __name__ == "__main__":
  main()
