# coding=utf-8
"""Train QMAP with strict, versioned CAPD finals artifact contracts."""

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
from qmap.qmap_generator import read_trace


ABLATION_CHOICES = (
    "full", "cross_attention", "no_pc", "no_rw", "mean_pool",
    "no_qformer", "no_cost")


class QMAPAccessSequenceDataset(Dataset):
  """Loads and validates complete QMAP JSONL samples."""

  LEGACY_REQUIRED_FIELDS = (
      "physical_address", "pc", "rw", "inactivity", "coldness",
      "write_sensitivity", "migration_cost")
  V3_REQUIRED_FIELDS = (
      "schema_version", "contract_id", "workload_id", "decision_index",
      "history_page_ids", "history_mask", "pc", "rw", "candidate_pages",
      "candidate_state_features", "candidate_mask", "original_pool_ranks",
      "inactivity", "coldness", "write_sensitivity", "migration_cost")

  def __init__(self, jsonl_path, expected_shape=None, expected_identity=None):
    self._samples = []
    self._expected_shape = expected_shape
    self._expected_identity = expected_identity
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
        "history_page_ids": torch.tensor(
            sample.get("history_page_ids", sample.get("physical_address")),
            dtype=torch.long),
        "history_mask": torch.tensor(
            sample.get("history_mask", [1] * len(sample.get(
                "history_page_ids", sample.get("physical_address", [])))),
            dtype=torch.float32),
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
    schema = sample.get("schema_version")
    is_v3 = schema == finals_config.SCHEMA_VERSION
    required = (self.V3_REQUIRED_FIELDS if is_v3 else
                self.LEGACY_REQUIRED_FIELDS)
    missing = [field for field in required if field not in sample]
    if missing:
      raise ValueError("Line {} missing fields: {}".format(
          line_number, missing))
    if is_v3 and "physical_address" in sample:
      raise ValueError(
          "Line {} v3 rejects legacy field physical_address.".format(
              line_number))
    history_field = "history_page_ids" if is_v3 else "physical_address"
    sequence_length = len(sample[history_field])
    if not (len(sample["pc"]) == sequence_length and
            len(sample["rw"]) == sequence_length):
      raise ValueError("Line {} has inconsistent sequence lengths.".format(
          line_number))
    if is_v3:
      if len(sample["history_mask"]) != sequence_length:
        raise ValueError("Line {} history_mask length mismatch.".format(
            line_number))
      if any(value not in (0, 1) for value in sample["history_mask"]):
        raise ValueError("Line {} history_mask must be binary.".format(
            line_number))
      if sample["contract_id"] != finals_config.CONTRACT_ID:
        raise ValueError("Line {} contract_id mismatch.".format(line_number))
      if self._expected_identity:
        for key, expected in self._expected_identity.items():
          if sample.get(key) != expected:
            raise ValueError(
                "Line {} {} mismatch.".format(line_number, key))

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
      expected_schema = (self._expected_identity or {}).get(
          "schema_version", finals_config.SCHEMA_VERSION)
      if sample.get("schema_version") != expected_schema:
        raise ValueError("Line {} schema_version mismatch.".format(
            line_number))

  def page_vocab_values(self):
    """Yields train-only history and real candidate page IDs."""
    for sample in self._samples:
      history = sample.get(
          "history_page_ids", sample.get("physical_address", []))
      history_mask = sample.get("history_mask", [1] * len(history))
      for page, valid in zip(history, history_mask):
        if valid:
          yield page
      pages = sample.get("candidate_pages", [])
      mask = sample.get("candidate_mask", [1] * len(pages))
      for page, valid in zip(pages, mask):
        if valid:
          yield page

  def pc_vocab_values(self):
    for sample in self._samples:
      history_mask = sample.get("history_mask", [1] * len(sample["pc"]))
      for pc, valid in zip(sample["pc"], history_mask):
        if valid:
          yield pc


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Train QMAP.")
  parser.add_argument("--train_data", required=True)
  parser.add_argument("--valid_data", default=None)
  parser.add_argument("--config", default=None,
                      help="Resolved, versioned CAPD finals config.")
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
  finals_config.validate_selector_params(config, selector_params)
  expected_config_fingerprint = finals_config.config_fingerprint(config)
  selector_fingerprint = finals_config.selector_fingerprint(selector_params)
  selector_holdout = selector_params.get("decision_holdout")
  holdout_fingerprint = selector_params.get("decision_holdout_fingerprint")
  is_v3_official = (
      config["schema_version"] == finals_config.SCHEMA_VERSION and
      config["run_profile"] == finals_config.OFFICIAL_PROFILE)
  if is_v3_official:
    if selector_holdout is not None or holdout_fingerprint is not None:
      raise ValueError("Official v3 rejects decision-holdout artifacts.")
  else:
    if not selector_holdout:
      raise ValueError("selector_params has no decision holdout plan.")
    finals_config.validate_decision_holdout(selector_holdout, config)
    if holdout_fingerprint != selector_holdout["fingerprint"]:
      raise ValueError("selector_params decision holdout fingerprint mismatch.")
  contract = finals_config.contract_from_config(config)
  expected_shape = {
      "H": contract["H"], "K": contract["K"],
      "page_state_dim": contract["page_state_dim"]}
  metadata_by_split = {}
  for split, path in (("train", train_path), ("valid", valid_path)):
    metadata = finals_config.load_jsonl_metadata(
        path, config=config, split=split, selector_params=selector_params)
    expected_partition = (
        "independent_{}_trace".format(split) if is_v3_official else
        "train_trace_decision_holdout")
    if metadata.get("source_partition") != expected_partition:
      raise ValueError("{} JSONL has the wrong source partition.".format(
          split))
    expected_trace_key = (
        "{}_trace_fingerprint".format(split) if is_v3_official else
        "train_trace_fingerprint")
    if metadata.get("source_trace_fingerprint") != selector_params.get(
        expected_trace_key):
      raise ValueError("{} JSONL source trace mismatch.".format(split))
    if not is_v3_official:
      if metadata.get("decision_holdout_fingerprint") != holdout_fingerprint:
        raise ValueError("{} JSONL decision holdout mismatch.".format(split))
      finals_config.validate_decision_holdout(
          metadata.get("decision_holdout", {}), config)
      if metadata["decision_holdout"] != selector_holdout:
        raise ValueError("{} JSONL decision holdout plan mismatch.".format(
            split))
    if int(metadata.get("sample_count", 0)) <= 0:
      raise ValueError("{} JSONL must contain validation-ready samples.".format(
          split))
    if not is_v3_official and config["schema_version"] != finals_config.SCHEMA_VERSION:
      expected_count_key = (
          "train_decision_points" if split == "train"
          else "validation_decision_points")
      if int(metadata["sample_count"]) != int(
          selector_params["decision_holdout"].get(expected_count_key, -1)):
        raise ValueError("{} JSONL sample count/split plan mismatch.".format(
            split))
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
      "decision_holdout": selector_holdout,
      "decision_holdout_fingerprint": holdout_fingerprint,
      "metadata": metadata_by_split,
      "expected_shape": expected_shape,
      "sample_identity": ({
          "schema_version": config["schema_version"],
          "contract_id": finals_config.CONTRACT_ID,
          "workload_id": config["run"]["workload"],
      } if config["schema_version"] == finals_config.SCHEMA_VERSION else {
          "schema_version": config["schema_version"],
      }),
  }


def apply_finals_config(args):
  if not args.config:
    return None
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT)
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
  args.approx_ndcg_alpha = float(config.get("loss", {}).get(
      "approx_ndcg_alpha", 10.0))
  args.position_encoding = config.get("model", {}).get(
      "position_encoding", "none")
  args.shared_page_embedding = (
      config.get("embedding", {}).get("page", {}).get("shared", False))
  if config["schema_version"] == finals_config.SCHEMA_VERSION:
    args.address_vocab_size = int(
        config["embedding"]["page"]["max_vocab_size"])
    args.page_vocab_size = args.address_vocab_size
    args.pc_vocab_size = int(config["embedding"]["pc"]["max_vocab_size"])
    if args.address_embed_dim != args.page_embed_dim:
      raise ValueError(
          "Shared history/candidate page embedding requires equal dimensions.")
  if args.ablation != "cross_attention":
    raise ValueError("Finals direction-1 training requires cross_attention.")
  return _validate_finals_artifacts(
      config, args.config, args.selector_params, args.train_data,
      args.valid_data)


def _forward_loss(batch, feature_embedder, extractor, scorer, loss_fn,
                  ablation):
  batch = apply_batch_ablation(batch, ablation)
  access_features = feature_embedder(
      batch["history_page_ids"], batch["pc"], batch["rw"])
  z = extractor(access_features, history_mask=batch["history_mask"])
  if (batch["legacy_candidates"] != 0).any():
    eviction_scores = scorer(
        z, batch["candidate_state_features"],
        candidate_mask=batch["candidate_mask"])
  else:
    candidate_page_embeddings = (
        feature_embedder.embed_pages(batch["candidate_pages"])
        if getattr(scorer, "_shared_page_embedding", False) else None)
    eviction_scores = scorer(
        z, batch["candidate_pages"], batch["candidate_state_features"],
        batch["candidate_mask"],
        candidate_page_embeddings=candidate_page_embeddings,
        history_mask=batch["history_mask"])
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
                       validation_loss, args, finals_context,
                       best_epoch=None, best_validation_loss=None):
  payload = {
      "epoch": epoch,
      "validation_loss": validation_loss,
      "best_epoch": best_epoch,
      "best_validation_loss": best_validation_loss,
      "model_args": vars(args).copy(),
      "feature_embedder": feature_embedder.state_dict(),
      "extractor": extractor.state_dict(),
      "scorer": scorer.state_dict(),
      "optimizer": optimizer.state_dict(),
  }
  if finals_context:
    config = finals_context["config"]
    payload.update({
        "schema_version": config["schema_version"],
        "experiment_contract": finals_context["contract"],
        "config_fingerprint": finals_context["config_fingerprint"],
        "selector_params": finals_context["selector_params"],
        "selector_fingerprint": finals_context["selector_fingerprint"],
        "decision_holdout": finals_context["decision_holdout"],
        "decision_holdout_fingerprint": finals_context[
            "decision_holdout_fingerprint"],
        "workload": config["run"]["workload"],
        "workload_id": config["run"]["workload"],
        "seed": args.seed,
        "jsonl_fingerprints": {
            split: metadata["data_fingerprint"]
            for split, metadata in finals_context["metadata"].items()
        },
        "git_commit": config.get(
            "run", {}).get("git_commit", "unknown"),
        "command": _command_text(),
    })
    if config["schema_version"] == finals_config.SCHEMA_VERSION:
      payload.update(finals_config.artifact_identity_from_config(config))
      page_vocab = feature_embedder.page_embedder
      pc_vocab = feature_embedder.pc_embedder
      payload.update({
          "contract_id": finals_config.CONTRACT_ID,
          "run_profile": config["run_profile"],
          "artifact_class": config["validation"]["artifact_class"],
          "vocab_contract": {
              "page_frozen": page_vocab.frozen,
              "pc_frozen": pc_vocab.frozen,
              "unk_index": 0,
              "page_vocab_fingerprint": finals_config.fingerprint_value(
                  page_vocab.input_to_index),
              "pc_vocab_fingerprint": finals_config.fingerprint_value(
                  pc_vocab.input_to_index),
          },
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
  sample_identity = (finals_context["sample_identity"]
                     if finals_context else None)
  train_dataset = QMAPAccessSequenceDataset(
      args.train_data, expected_shape=expected_shape,
      expected_identity=sample_identity)
  valid_dataset = (QMAPAccessSequenceDataset(
      args.valid_data, expected_shape=expected_shape,
      expected_identity=sample_identity)
                   if args.valid_data else None)
  if finals_context:
    if len(train_dataset) != int(
        finals_context["metadata"]["train"]["sample_count"]):
      raise ValueError("Train JSONL row count/metadata mismatch.")
    if valid_dataset is not None and len(valid_dataset) != int(
        finals_context["metadata"]["valid"]["sample_count"]):
      raise ValueError("Valid JSONL row count/metadata mismatch.")
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
  is_v3 = bool(
      finals_context and finals_context["config"]["schema_version"] ==
      finals_config.SCHEMA_VERSION)
  if is_v3:
    # Both vocabularies are fitted from the complete train trace only, then
    # frozen before a validation batch can reach either embedder.
    train_trace, _ = read_trace(
        finals_context["config"]["data"]["train_trace"],
        int(finals_context["config"]["trace"]["page_shift"]))
    feature_embedder.page_embedder.fit(
        (access["page_id"] for access in train_trace)).freeze()
    feature_embedder.pc_embedder.fit(
        (access["pc"] for access in train_trace)).freeze()
    del train_trace
  if feature_embedder.embed_dim != args.hidden_dim:
    raise ValueError("hidden_dim ({}) must equal embedding dimension ({})."
                     .format(args.hidden_dim, feature_embedder.embed_dim))
  extractor = model.QMAPMacroscopicPatternExtractor(
      hidden_dim=args.hidden_dim, num_queries=args.num_queries,
      num_layers=args.num_layers, num_heads=args.num_heads,
      feedforward_dim=args.feedforward_dim, dropout=args.dropout,
      use_qformer=uses_qformer(args.ablation),
      pooling_strategy=args.pooling_strategy,
      position_encoding=getattr(args, "position_encoding", "none"),
      max_sequence_length=(expected_shape["H"] if expected_shape else
                           4096)).to(device)
  scorer = model.QMAPCandidateScorer(
      hidden_dim=args.hidden_dim, page_state_dim=args.page_state_dim,
      page_embed_dim=args.page_embed_dim,
      page_vocab_size=args.page_vocab_size, num_heads=args.num_heads,
      dropout=args.dropout, page_dim=args.page_dim,
      scoring_input=args.scoring_input,
      shared_page_embedding=getattr(
          args, "shared_page_embedding", False)).to(device)
  loss_fn = qmap_loss.QMAPCostAwareRankingLoss(
      lambda_1=args.inactivity_weight,
      lambda_2=args.coldness_weight,
      lambda_3=0.0 if args.ablation == "no_cost" else (
          args.write_sensitivity_weight),
      lambda_4=0.0 if args.ablation == "no_cost" else (
          args.migration_cost_weight),
      alpha=getattr(args, "approx_ndcg_alpha", 10.0)).to(device)
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
    is_best = validation_loss < best_loss
    if is_best:
      best_loss = validation_loss
      best_epoch = epoch
    payload = checkpoint_payload(
        feature_embedder, extractor, scorer, optimizer, epoch,
        validation_loss, args, finals_context,
        best_epoch=best_epoch, best_validation_loss=best_loss)
    torch.save(payload, last_path)
    if finals_context is None:
      # Preserve historical experiment-script checkpoint names outside the
      # isolated finals_v2.1 path.
      torch.save(payload, os.path.join(
          args.output_dir, "qmap_epoch_{}.pth".format(epoch)))
    if is_best:
      torch.save(payload, best_path)
    print("epoch={}/{} train_loss={:.6f} valid_loss={:.6f}".format(
        epoch, args.epochs, train_loss, validation_loss), flush=True)

  manifest = {
      "schema_version": (finals_context["config"]["schema_version"]
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
      "decision_holdout_fingerprint": (
          finals_context["decision_holdout_fingerprint"]
          if finals_context else None),
      "git_commit": (finals_context["config"].get("run", {}).get(
          "git_commit", "unknown") if finals_context else
                     finals_config.current_git_commit(PROJECT_ROOT)),
      "command": _command_text(),
  }
  if is_v3:
    manifest.update(finals_config.artifact_identity_from_config(
        finals_context["config"]))
    manifest["selector_fingerprint"] = finals_context[
        "selector_fingerprint"]
    manifest["jsonl_fingerprints"] = {
        split: metadata["data_fingerprint"]
        for split, metadata in finals_context["metadata"].items()
    }
  finals_config.write_json(
      os.path.join(args.output_dir, "checkpoint_manifest.json"), manifest)
  print("Training finished. best={} last={}".format(
      best_path, last_path), flush=True)


if __name__ == "__main__":
  main()
