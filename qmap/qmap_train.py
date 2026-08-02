# coding=utf-8
"""Train QMAP with strict, versioned CAPD finals artifact contracts."""

from __future__ import print_function

import argparse
import copy
import json
import math
import os
import random
import shlex
import sys
import time

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
from qmap import no_vpn_ablation
from qmap.qmap_generator import read_trace


PROACTIVE_STAGE4_SAMPLE_SCHEMA = "capd_proactive_stage4_sample_v1_0"
PROACTIVE_STAGE4_STAGE7_SAMPLE_SCHEMA = (
    "capd_proactive_stage4_stage7_sample_v1_0")
PROACTIVE_STAGE4_CONTRACT_ID = "CAPD-PROACTIVE-STAGE4-1.0"
PROACTIVE_STAGE4_STAGE7_CONTRACT_ID = "CAPD-PROACTIVE-STAGE4-STAGE7-1.0"
PROACTIVE_STAGE4_STAGE7_PROTOCOL_REPAIR_CONTRACT_ID = (
    "CAPD-PROACTIVE-STAGE4-STAGE7-1.1")
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
    is_proactive_stage4 = schema == PROACTIVE_STAGE4_SAMPLE_SCHEMA
    is_proactive_stage4_stage7 = (
        schema == PROACTIVE_STAGE4_STAGE7_SAMPLE_SCHEMA)
    is_structured = is_v3 or is_proactive_stage4 or is_proactive_stage4_stage7
    required = (self.V3_REQUIRED_FIELDS if is_structured else
                self.LEGACY_REQUIRED_FIELDS)
    missing = [field for field in required if field not in sample]
    if missing:
      raise ValueError("Line {} missing fields: {}".format(
          line_number, missing))
    if is_structured and "physical_address" in sample:
      raise ValueError(
          "Line {} structured sample rejects legacy field physical_address.".format(
              line_number))
    history_field = (
        "history_page_ids" if is_structured else "physical_address")
    sequence_length = len(sample[history_field])
    if not (len(sample["pc"]) == sequence_length and
            len(sample["rw"]) == sequence_length):
      raise ValueError("Line {} has inconsistent sequence lengths.".format(
          line_number))
    if is_structured:
      if len(sample["history_mask"]) != sequence_length:
        raise ValueError("Line {} history_mask length mismatch.".format(
            line_number))
      if any(value not in (0, 1) for value in sample["history_mask"]):
        raise ValueError("Line {} history_mask must be binary.".format(
            line_number))
      expected_contract_id = (
          finals_config.CONTRACT_ID if is_v3
          else PROACTIVE_STAGE4_STAGE7_CONTRACT_ID
          if is_proactive_stage4_stage7 else PROACTIVE_STAGE4_CONTRACT_ID)
      if sample["contract_id"] != expected_contract_id:
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
  parser.add_argument(
      "--proactive_stage4_contract", default=None,
      help=(
          "Strict capd_proactive_stage4 training identity. Mutually "
          "exclusive with --config/--selector_params."))
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
  parser.add_argument(
      "--save_every_epoch", action="store_true",
      help=(
          "Also save qmap_epoch_N.pth for validation-replay checkpoint "
          "selection. Defaults off, preserving the official Stage-5/6 path."))
  parser.add_argument(
      "--resume_checkpoint", default=None,
      help="Resume an interrupted run from qmap_last.pth.")
  parser.add_argument("--ablation", choices=ABLATION_CHOICES,
                      default="cross_attention")
  return parser


def set_random_seed(seed):
  random.seed(seed)
  torch.manual_seed(seed)
  if torch.cuda.is_available():
    torch.cuda.manual_seed_all(seed)


def enable_strict_determinism():
  """Enables the reproducibility contract used by proactive Stage 4."""
  os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
  torch.use_deterministic_algorithms(True)
  if hasattr(torch.backends, "cudnn"):
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


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


def _training_code_fingerprint():
  paths = (
      "qmap/qmap_train.py", "qmap/candidate_filter.py",
      "qmap/finals_generator.py", "policy_learning/cache_model/embed.py",
      "policy_learning/cache_model/model.py",
      "policy_learning/cache_model/qmap_loss.py",
      "qmap/finals_config.py", "qmap/no_vpn_ablation.py",
      "qmap/proactive_stage4.py", "qmap/proactive_replay.py",
      "qmap/qmap_eval.py")
  return finals_config.fingerprint_value({
      path: finals_config.fingerprint_file(os.path.join(PROJECT_ROOT, path))
      for path in paths})


def _validate_finals_artifacts(config, config_path, selector_path,
                               train_path, valid_path):
  if not selector_path or not valid_path:
    raise ValueError(
        "--selector_params and --valid_data are required with --config.")
  data_config = (
      no_vpn_ablation.load_data_config(
          train_path, PROJECT_ROOT, config)
      if "experiment_name" in config else config)
  selector_params = finals_config.load_json(selector_path)
  finals_config.validate_selector_params(data_config, selector_params)
  expected_config_fingerprint = finals_config.config_fingerprint(config)
  selector_fingerprint = finals_config.selector_fingerprint(selector_params)
  selector_holdout = selector_params.get("decision_holdout")
  holdout_fingerprint = selector_params.get("decision_holdout_fingerprint")
  uses_independent_validation = (
      config["schema_version"] == finals_config.SCHEMA_VERSION and
      finals_config.uses_independent_validation(config))
  if uses_independent_validation:
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
        path, config=data_config, split=split,
        selector_params=selector_params)
    expected_partition = (
        "independent_{}_trace".format(split)
        if uses_independent_validation else
        "train_trace_decision_holdout")
    if metadata.get("source_partition") != expected_partition:
      raise ValueError("{} JSONL has the wrong source partition.".format(
          split))
    expected_trace_key = (
        "{}_trace_fingerprint".format(split)
        if uses_independent_validation else
        "train_trace_fingerprint")
    if metadata.get("source_trace_fingerprint") != selector_params.get(
        expected_trace_key):
      raise ValueError("{} JSONL source trace mismatch.".format(split))
    if not uses_independent_validation:
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
    if config["schema_version"] != finals_config.SCHEMA_VERSION:
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
      "data_config": data_config,
      "data_config_fingerprint": finals_config.config_fingerprint(
          data_config),
      "expected_shape": expected_shape,
      "sample_identity": ({
          "schema_version": config["schema_version"],
          "contract_id": finals_config.CONTRACT_ID,
          "workload_id": config["run"]["workload"],
      } if config["schema_version"] == finals_config.SCHEMA_VERSION else {
          "schema_version": config["schema_version"],
      }),
  }


def apply_finals_config(args, explicit_seed=None):
  if not args.config:
    return None
  config = finals_config.load_config(
      args.config, require_resolved=True, project_root=PROJECT_ROOT,
      verify_manifest_files=False)
  training = config["training"]
  labels = config["labels"]
  if explicit_seed is None:
    args.seed = int(training["seed"])
    args.training_seed_source = "config_default"
  else:
    args.seed = int(explicit_seed)
    args.training_seed_source = "explicit_cli"
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
  # load_config(require_resolved=True) above is the single authoritative
  # schema/data-manifest validation boundary. Do not re-run the whole finals
  # schema validator merely to read this backward-compatible optional flag:
  # unit callers may replace the validated loader with a minimal projection,
  # and a second parse would incorrectly treat that projection as a raw v3
  # document. The default exactly matches finals_config.use_page_id_embedding.
  args.use_page_id_embedding = bool(
      config.get("model", {}).get("use_page_id_embedding", True))
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
  variant_id = config.get("stage5_variant", {}).get("variant_id")
  args.context_mode = (
      "history_mean_pool" if variant_id == "history_mean_pool"
      else "cross_attention")
  args.stage5_variant_id = variant_id
  return _validate_finals_artifacts(
      config, args.config, args.selector_params, args.train_data,
      args.valid_data)


def apply_proactive_stage4_contract(args, explicit_seed=None):
  """Applies the isolated proactive Stage-4 training contract."""
  if not args.proactive_stage4_contract:
    return None
  if args.config or args.selector_params:
    raise ValueError(
        "--proactive_stage4_contract is mutually exclusive with "
        "--config/--selector_params.")
  if not args.valid_data:
    raise ValueError(
        "Proactive Stage-4 training requires --valid_data.")
  contract_path = os.path.abspath(args.proactive_stage4_contract)
  with open(contract_path, "r", encoding="utf-8") as input_file:
    raw_value = json.load(input_file)
  if raw_value.get("contract_id") in {
      PROACTIVE_STAGE4_STAGE7_CONTRACT_ID,
      PROACTIVE_STAGE4_STAGE7_PROTOCOL_REPAIR_CONTRACT_ID}:
    from qmap import proactive_stage4_stage7 as contract_module
  else:
    from qmap import proactive_stage4 as contract_module
  value = contract_module.load_json(contract_path)
  context = contract_module.validate_training_contract(
      value, args.train_data, args.valid_data, explicit_seed=explicit_seed)
  training = context["training"]
  weights = context["weights"]
  args.seed = context["seed"]
  args.training_seed_source = (
      "explicit_cli_and_contract" if explicit_seed is not None
      else "proactive_stage4_contract")
  args.epochs = int(training["epochs"])
  args.batch_size = int(training["batch_size"])
  args.lr = float(training["learning_rate"])
  args.weight_decay = float(training.get("weight_decay", args.weight_decay))
  args.num_workers = int(training.get("num_workers", args.num_workers))
  args.inactivity_weight = float(weights[0])
  args.coldness_weight = float(weights[1])
  args.write_sensitivity_weight = float(weights[2])
  args.migration_cost_weight = 0.0
  args.page_state_dim = int(context["expected_shape"]["page_state_dim"])
  args.position_encoding = training.get("position_encoding", "none")
  args.use_page_id_embedding = bool(
      training.get("use_page_id_embedding", True))
  args.shared_page_embedding = bool(
      training.get("shared_page_embedding", False))
  args.context_mode = training.get("context_mode", "cross_attention")
  args.stage5_variant_id = None
  args.approx_ndcg_alpha = float(
      training.get("approx_ndcg_alpha", 10.0))
  args.deterministic_algorithms = bool(
      training.get("deterministic_algorithms", True))
  model_args = context.get("model_args", {})
  for field in (
      "hidden_dim", "address_embed_dim", "pc_embed_dim", "rw_embed_dim",
      "address_vocab_size", "pc_vocab_size", "page_dim", "page_state_dim",
      "page_embed_dim", "page_vocab_size", "num_queries", "num_layers",
      "num_heads", "feedforward_dim", "dropout"):
    if field in model_args:
      setattr(args, field, model_args[field])
  for field in ("position_encoding", "context_mode",
                "use_page_id_embedding", "shared_page_embedding"):
    if field in model_args:
      setattr(args, field, model_args[field])
  if "ablation" in model_args and model_args["ablation"] != args.ablation:
    raise ValueError("CLI ablation/training contract mismatch.")
  if context.get("stage7"):
    expected_device = value.get("execution", {}).get("actual_device")
    if not expected_device or args.device != expected_device:
      raise ValueError("CLI device/Stage7 training contract mismatch.")
  if args.ablation != "cross_attention":
    raise ValueError(
        "Proactive Stage-4 training requires cross_attention.")
  context["contract_path"] = contract_path
  return context


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
                       best_epoch=None, best_validation_loss=None,
                       loss_curve=None, training_duration_seconds=0.0,
                       proactive_context=None):
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
      "loss_curve": list(loss_curve or []),
      "training_duration_seconds": float(training_duration_seconds),
      "rng_state": {
          "python": random.getstate(),
          "torch": torch.get_rng_state(),
          "cuda": (torch.cuda.get_rng_state_all()
                   if torch.cuda.is_available() else None),
      },
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
        "variant": no_vpn_ablation.variant_from_config(config),
        "seed": args.seed,
        "config_path": finals_context["config_path"],
        "data_config_fingerprint": finals_context[
            "data_config_fingerprint"],
        "training_seed_source": args.training_seed_source,
        "jsonl_fingerprints": {
            split: metadata["data_fingerprint"]
            for split, metadata in finals_context["metadata"].items()
        },
        "git_commit": finals_config.current_git_commit(PROJECT_ROOT),
        "config_generation_commit": config.get(
            "run", {}).get("git_commit", "unknown"),
        "code_fingerprint": _training_code_fingerprint(),
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
  elif proactive_context:
    contract = proactive_context["contract"]
    page_vocab = feature_embedder.page_embedder
    pc_vocab = feature_embedder.pc_embedder
    payload.update({
        "schema_version": contract["schema_version"],
        "contract_id": contract["contract_id"],
        "experiment_id": contract["experiment_id"],
        "seed": args.seed,
        "training_seed_source": args.training_seed_source,
        "training_args": {
            "learning_rate": args.lr,
            "batch_size": args.batch_size,
            "weight_decay": args.weight_decay,
            "epochs": args.epochs,
            "num_workers": args.num_workers,
            "approx_ndcg_alpha": args.approx_ndcg_alpha,
            "seed": args.seed,
            "device": getattr(args, "actual_device", str(args.device)),
            "deterministic_algorithms": bool(getattr(
                args, "deterministic_algorithms", False)),
            "precision": "fp32",
            "checkpoint_tie_break": "earliest_epoch",
        },
        "stage4_training_contract": contract,
        "stage4_training_contract_fingerprint":
            proactive_context["contract_fingerprint"],
        "jsonl_fingerprints": {
            split: contract["data"][split]["sha256"]
            for split in ("train", "validation")
        },
        "sample_identity": proactive_context["sample_identity"],
        "git_commit": finals_config.current_git_commit(PROJECT_ROOT),
        "code_fingerprint": _training_code_fingerprint(),
        "command": _command_text(),
        "vocab_contract": {
            "page_frozen": page_vocab.frozen,
            "pc_frozen": pc_vocab.frozen,
            "unk_index": 0,
            "page_vocab_fingerprint": finals_config.fingerprint_value(
                page_vocab.input_to_index),
            "pc_vocab_fingerprint": finals_config.fingerprint_value(
                pc_vocab.input_to_index),
        },
        "test_trace_opened": False,
        "selector_status": "disabled",
    })
  return payload


def _load_resume_checkpoint(path, device, feature_embedder, extractor, scorer,
                            optimizer, args, finals_context,
                            proactive_context=None):
  checkpoint = torch.load(path, map_location=device)
  if finals_context:
    config = finals_context["config"]
    finals_config.validate_artifact_identity(
        config, checkpoint, "resume checkpoint")
    finals_config.assert_contract_matches(
        finals_context["contract"],
        checkpoint.get("experiment_contract", {}),
        "resume checkpoint")
    if checkpoint.get("selector_fingerprint") != finals_context[
        "selector_fingerprint"]:
      raise ValueError("Resume checkpoint selector mismatch.")
  elif proactive_context:
    if checkpoint.get("contract_id") != proactive_context["contract"].get(
        "contract_id"):
      raise ValueError("Resume checkpoint Stage-4 contract mismatch.")
    if checkpoint.get("stage4_training_contract_fingerprint") != (
        proactive_context["contract_fingerprint"]):
      raise ValueError("Resume checkpoint Stage-4 identity mismatch.")
    expected_fingerprints = {
        split: proactive_context["contract"]["data"][split]["sha256"]
        for split in ("train", "validation")}
    if checkpoint.get("jsonl_fingerprints") != expected_fingerprints:
      raise ValueError("Resume checkpoint Stage-4 data mismatch.")
  model_args = checkpoint.get("model_args", {})
  if int(checkpoint.get("seed", args.seed)) != int(args.seed):
    raise ValueError("Resume checkpoint seed mismatch.")
  if bool(model_args.get("use_page_id_embedding", True)) != bool(
      getattr(args, "use_page_id_embedding", True)):
    raise ValueError("Resume checkpoint page-ID embedding mode mismatch.")
  feature_embedder.load_state_dict(checkpoint["feature_embedder"])
  extractor.load_state_dict(checkpoint["extractor"])
  scorer.load_state_dict(checkpoint["scorer"])
  optimizer.load_state_dict(checkpoint["optimizer"])
  rng_state = checkpoint.get("rng_state", {})
  if rng_state.get("python") is not None:
    random.setstate(rng_state["python"])
  if rng_state.get("torch") is not None:
    torch.set_rng_state(rng_state["torch"].cpu())
  if torch.cuda.is_available() and rng_state.get("cuda") is not None:
    torch.cuda.set_rng_state_all(
        [state.cpu() for state in rng_state["cuda"]])
  completed_epoch = int(checkpoint.get("epoch", 0))
  if completed_epoch >= int(args.epochs) and not proactive_context:
    raise ValueError(
        "Resume checkpoint already completed configured epochs.")
  return {
      "start_epoch": completed_epoch + 1,
      "best_epoch": checkpoint.get("best_epoch"),
      "best_loss": float(checkpoint.get(
          "best_validation_loss", checkpoint.get(
              "validation_loss", float("inf")))),
      "loss_curve": list(checkpoint.get("loss_curve", [])),
      "training_duration_seconds": float(
          checkpoint.get("training_duration_seconds", 0.0)),
  }


def main():
  args = build_arg_parser().parse_args()
  seed_was_explicit = any(
      value == "--seed" or value.startswith("--seed=")
      for value in sys.argv[1:])
  explicit_seed = args.seed if seed_was_explicit else None
  args.training_seed_source = (
      "explicit_cli" if explicit_seed is not None else "parser_default")
  finals_context = apply_finals_config(args, explicit_seed=explicit_seed)
  proactive_context = apply_proactive_stage4_contract(
      args, explicit_seed=explicit_seed)
  os.makedirs(args.output_dir, exist_ok=True)
  if finals_context:
    finals_config.write_json(
        os.path.join(args.output_dir, "resolved_config.json"),
        finals_context["config"])
  elif proactive_context:
    finals_config.write_json(
        os.path.join(args.output_dir, "resolved_training_contract.json"),
        proactive_context["contract"])
  set_random_seed(args.seed)
  if proactive_context:
    enable_strict_determinism()

  device_name = args.device
  if device_name is None:
    device_name = "cuda" if torch.cuda.is_available() else "cpu"
  device = torch.device(device_name)
  args.actual_device = str(device)
  active_context = finals_context or proactive_context
  expected_shape = (
      active_context["expected_shape"] if active_context else None)
  sample_identity = (
      active_context["sample_identity"] if active_context else None)
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
  elif proactive_context:
    if len(train_dataset) != int(
        proactive_context["data"]["train"]["sample_count"]):
      raise ValueError("Stage-4 Train JSONL row count/contract mismatch.")
    if valid_dataset is None or len(valid_dataset) != int(
        proactive_context["data"]["validation"]["sample_count"]):
      raise ValueError("Stage-4 Validation JSONL row count/contract mismatch.")
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
      rw_embedder=embed.RWFlagEmbedder(embed_dim=args.rw_embed_dim),
      use_page_id_embedding=getattr(
          args, "use_page_id_embedding", True)).to(device)
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
  elif proactive_context:
    # Stage-4 vocabularies are fitted on Train samples only and frozen before
    # the first Validation batch. This prevents validation-vocabulary leakage.
    feature_embedder.page_embedder.fit(
        train_dataset.page_vocab_values()).freeze()
    feature_embedder.pc_embedder.fit(
        train_dataset.pc_vocab_values()).freeze()
    expected_vocabulary = proactive_context.get("vocabulary", {})
    if expected_vocabulary:
      page_sha = finals_config.fingerprint_value(
          feature_embedder.page_embedder.input_to_index)
      pc_sha = finals_config.fingerprint_value(
          feature_embedder.pc_embedder.input_to_index)
      if (page_sha != expected_vocabulary.get("page_vocabulary_sha256") or
          pc_sha != expected_vocabulary.get("pc_vocabulary_sha256")):
        raise ValueError("Train-only vocabulary fingerprint mismatch.")
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
          args, "shared_page_embedding", False),
      context_mode=getattr(args, "context_mode", "cross_attention"),
      use_page_id_embedding=getattr(
          args, "use_page_id_embedding", True)).to(device)
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

  start_epoch = 1
  previous_training_duration = 0.0
  best_loss = float("inf")
  best_epoch = None
  loss_curve = []
  if args.resume_checkpoint:
    resume_state = _load_resume_checkpoint(
        args.resume_checkpoint, device, feature_embedder, extractor, scorer,
        optimizer, args, finals_context,
        proactive_context=proactive_context)
    start_epoch = resume_state["start_epoch"]
    best_loss = resume_state["best_loss"]
    best_epoch = resume_state["best_epoch"]
    loss_curve = resume_state["loss_curve"]
    previous_training_duration = resume_state[
        "training_duration_seconds"]
    print("QMAP resume: checkpoint={} next_epoch={}".format(
        args.resume_checkpoint, start_epoch), flush=True)

  training_started = time.time()
  global_iteration = 0
  last_path = os.path.join(args.output_dir, "qmap_last.pth")
  best_path = os.path.join(args.output_dir, "qmap_best.pth")
  for epoch in range(start_epoch, args.epochs + 1):
    feature_embedder.train()
    extractor.train()
    scorer.train()
    loss_sum = 0.0
    iterations = 0
    for batch in train_loader:
      batch = move_batch_to_device(batch, device)
      loss = _forward_loss(
          batch, feature_embedder, extractor, scorer, loss_fn, args.ablation)
      if not math.isfinite(float(loss.item())):
        raise ValueError("Non-finite batch training loss detected.")
      optimizer.zero_grad()
      loss.backward()
      gradient_norm = torch.nn.utils.clip_grad_norm_(
          parameters, max_norm=10.0)
      if not math.isfinite(float(gradient_norm)):
        raise ValueError(
            "Non-finite training gradient detected before optimizer step.")
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
    loss_curve.append({
        "epoch": epoch,
        "train_loss": train_loss,
        "valid_loss": validation_loss,
    })
    is_best = validation_loss < best_loss
    if is_best:
      best_loss = validation_loss
      best_epoch = epoch
    payload = checkpoint_payload(
        feature_embedder, extractor, scorer, optimizer, epoch,
        validation_loss, args, finals_context,
        best_epoch=best_epoch, best_validation_loss=best_loss,
        loss_curve=loss_curve,
        training_duration_seconds=(
            previous_training_duration + time.time() - training_started),
        proactive_context=proactive_context)
    torch.save(payload, last_path)
    if finals_context is None or args.save_every_epoch:
      # Preserve historical experiment-script checkpoint names outside the
      # isolated finals_v2.1 path. O2 opts in explicitly for v3 checkpoints.
      torch.save(payload, os.path.join(
          args.output_dir, "qmap_epoch_{}.pth".format(epoch)))
    if is_best:
      torch.save(payload, best_path)
    print("epoch={}/{} train_loss={:.6f} valid_loss={:.6f}".format(
        epoch, args.epochs, train_loss, validation_loss), flush=True)

  if not os.path.isfile(best_path):
    # Covers an interruption after qmap_last.pth was durably written but
    # before the first/best checkpoint copy and manifest were written.
    completed = torch.load(last_path, map_location=device)
    if int(completed.get("best_epoch", -1)) != int(
        completed.get("epoch", -2)):
      raise ValueError(
          "Best checkpoint is missing and cannot be reconstructed from last.")
    torch.save(completed, best_path)
  if proactive_context:
    completed_epoch = len(loss_curve)
    for epoch in range(1, args.epochs + 1):
      epoch_path = os.path.join(
          args.output_dir, "qmap_epoch_{}.pth".format(epoch))
      if os.path.isfile(epoch_path):
        continue
      if epoch != completed_epoch:
        raise ValueError(
            "Per-epoch checkpoint is missing and cannot be reconstructed: "
            "{}.".format(epoch_path))
      completed = torch.load(last_path, map_location=device)
      if int(completed.get("epoch", -1)) != epoch:
        raise ValueError("Last checkpoint epoch mismatch during recovery.")
      torch.save(completed, epoch_path)

  manifest = {
      "schema_version": (
          finals_context["config"]["schema_version"]
          if finals_context else
          proactive_context["contract"]["schema_version"]
          if proactive_context else "legacy_qmap"),
      "best_epoch": best_epoch,
      "best_validation_loss": best_loss,
      "final_train_loss": loss_curve[-1]["train_loss"],
      "loss_curve": loss_curve,
      "seed": args.seed,
      "variant": (
          no_vpn_ablation.variant_from_config(finals_context["config"])
          if finals_context else
          "capd_proactive_stage4" if proactive_context else "legacy"),
      "training_seed_source": args.training_seed_source,
      "selection_criterion": (
          "minimum_valid_loss_only" if valid_loader else
          "minimum_train_loss_no_validation"),
      "per_epoch_checkpoints_saved": bool(
          args.save_every_epoch or proactive_context),
      "training_duration_seconds": (
          previous_training_duration + time.time() - training_started),
      "nan_or_inf_detected": False,
      "checkpoints": {
          "last": {"path": os.path.abspath(last_path),
                   "fingerprint": finals_config.fingerprint_file(last_path)},
          "best": {"path": os.path.abspath(best_path),
                   "fingerprint": finals_config.fingerprint_file(best_path)},
      },
      "config_fingerprint": (finals_context["config_fingerprint"]
                             if finals_context else None),
      "config_path": (
          finals_context["config_path"] if finals_context else None),
      "data_config_fingerprint": (
          finals_context["data_config_fingerprint"]
          if finals_context else None),
      "decision_holdout_fingerprint": (
          finals_context["decision_holdout_fingerprint"]
          if finals_context else None),
      "git_commit": finals_config.current_git_commit(PROJECT_ROOT),
      "config_generation_commit": (finals_context["config"].get(
          "run", {}).get("git_commit", "unknown") if finals_context else None),
      "code_fingerprint": _training_code_fingerprint(),
      "command": _command_text(),
      "model_args": vars(args).copy(),
      "training_args": {
          "learning_rate": args.lr,
          "batch_size": args.batch_size,
          "weight_decay": args.weight_decay,
          "epochs": args.epochs,
          "num_workers": args.num_workers,
          "approx_ndcg_alpha": args.approx_ndcg_alpha,
          "seed": args.seed,
          "device": getattr(args, "actual_device", str(args.device)),
          "deterministic_algorithms": bool(getattr(
              args, "deterministic_algorithms", False)),
          "precision": "fp32",
          "checkpoint_tie_break": "earliest_epoch",
      },
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
    manifest["source_manifest"] = finals_context["config"]["data"].get(
        "source_manifest")
    manifest["source_manifest_fingerprint"] = finals_context[
        "selector_params"].get("source_manifest_fingerprint")
    manifest["split_fingerprints"] = dict(
        finals_context["config"]["data"].get("split_fingerprints", {}))
    manifest["audit_input_scope"] = "train_jsonl_and_valid_jsonl_only"
    manifest["test_trace_opened"] = False
    manifest["stage5_variant"] = finals_context["config"].get(
        "stage5_variant")
    manifest["stage6_variant"] = finals_context["config"].get(
        "stage6_variant")
    manifest["optimization_variant"] = finals_context["config"].get(
        "optimization_variant")
    if args.save_every_epoch:
      manifest["checkpoints"]["per_epoch"] = [{
          "epoch": epoch,
          "path": os.path.abspath(os.path.join(
              args.output_dir, "qmap_epoch_{}.pth".format(epoch))),
          "fingerprint": finals_config.fingerprint_file(os.path.join(
              args.output_dir, "qmap_epoch_{}.pth".format(epoch))),
      } for epoch in range(1, args.epochs + 1)]
    manifest["model_contract"] = {
        "use_page_id_embedding": getattr(
            args, "use_page_id_embedding", True),
        "position_encoding": getattr(
            args, "position_encoding", "sinusoidal"),
        "context_mode": getattr(args, "context_mode", "cross_attention"),
        "candidate_state_mode": (
            "zeros_4d" if getattr(
                args, "stage5_variant_id", None) == "no_candidate_state"
            else "observed_4d"),
        "page_embedding_retained": True,
        "page_embedding_active": getattr(
            args, "use_page_id_embedding", True),
        "write_sensitivity_weight": args.write_sensitivity_weight,
    }
  elif proactive_context:
    contract = proactive_context["contract"]
    manifest.update({
        "contract_id": contract["contract_id"],
        "experiment_id": contract["experiment_id"],
        "stage4_training_contract_fingerprint":
            proactive_context["contract_fingerprint"],
        "stage4_training_contract_path":
            proactive_context["contract_path"],
        "jsonl_fingerprints": {
            split: contract["data"][split]["sha256"]
            for split in ("train", "validation")
        },
        "sample_identity": proactive_context["sample_identity"],
        "audit_input_scope": "train_jsonl_and_validation_jsonl_only",
        "checkpoint_validation_scope": copy.deepcopy(
            proactive_context.get("validation_protocol", {}).get(
                "checkpoint_validation_scope", [])),
        "structural_zero_decision_validation": copy.deepcopy(
            proactive_context.get("validation_protocol", {}).get(
                "structural_zero_decision_validation", [])),
        "validation_sample_count_by_workload": copy.deepcopy(
            proactive_context.get("validation_protocol", {}).get(
                "validation_sample_count_by_workload", {})),
        "test_trace_opened": False,
        "selector_status": "disabled",
        "checkpoints": dict(manifest["checkpoints"]),
        "model_contract": {
            "H": proactive_context["expected_shape"]["H"],
            "K": proactive_context["expected_shape"]["K"],
            "page_state_dim":
                proactive_context["expected_shape"]["page_state_dim"],
            "use_page_id_embedding": getattr(
                args, "use_page_id_embedding", True),
            "position_encoding": getattr(args, "position_encoding", "none"),
            "context_mode": getattr(
                args, "context_mode", "cross_attention"),
            "write_sensitivity_weight": args.write_sensitivity_weight,
        },
    })
    manifest["checkpoints"]["per_epoch"] = [{
        "epoch": epoch,
        "path": os.path.abspath(os.path.join(
            args.output_dir, "qmap_epoch_{}.pth".format(epoch))),
        "fingerprint": finals_config.fingerprint_file(os.path.join(
            args.output_dir, "qmap_epoch_{}.pth".format(epoch))),
    } for epoch in range(1, args.epochs + 1)]
  finals_config.write_json(
      os.path.join(args.output_dir, "checkpoint_manifest.json"), manifest)
  print("Training finished. best={} last={}".format(
      best_path, last_path), flush=True)


if __name__ == "__main__":
  main()
