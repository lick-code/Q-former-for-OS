# coding=utf-8
"""Replay evaluation for QMAP page-migration policies.

The evaluator replays a page trace against a small DRAM/NVM model and reports
the prototype metrics used by the paper experiments:

  - hit rate
  - NVM reads/writes
  - migration count
  - weighted access cost
  - policy decision/inference overhead

Supported policies are LRU, Random, LFU, CLOCK, QMAP, and lightweight learned
baselines. The QMAP path loads a checkpoint produced by qmap_train.py and uses
the same lightweight feature construction as qmap_generator.py.
"""

import argparse
import json
import os
import random
import shlex
import sys
import time

try:
  from qmap_generator import build_candidate_state_features
  from qmap_generator import apply_history_ablation
  from qmap_generator import get_lru_tail_candidates_and_mask
  from qmap_generator import padded_history
  from qmap_generator import read_trace
except ImportError:
  from qmap.qmap_generator import build_candidate_state_features
  from qmap.qmap_generator import apply_history_ablation
  from qmap.qmap_generator import get_lru_tail_candidates_and_mask
  from qmap.qmap_generator import padded_history
  from qmap.qmap_generator import read_trace


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import candidate_filter
from qmap import finals_config


DRAM_READ_COST = 1.0
DRAM_WRITE_COST = 1.0
NVM_READ_COST = 2.0
NVM_WRITE_COST = 8.0
MIGRATION_COST = 10.0
ABLATION_CHOICES = (
    "full", "cross_attention", "no_pc", "no_rw", "mean_pool",
    "no_qformer", "no_cost")


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Evaluate QMAP by trace replay.")
  parser.add_argument("--trace_path", default=None,
                      help="Input CSV trace with PC,Address and optional RW.")
  parser.add_argument("--config", default=None,
                      help="Resolved CAPD finals_v2 config.")
  parser.add_argument("--selector_params", default=None,
                      help="Frozen selector_params.json for QMAP finals_v2.")
  parser.add_argument("--checkpoint", default=None,
                      help="QMAP checkpoint path. Required for --policy qmap.")
  parser.add_argument("--learned_model", default=None,
                      help=("JSON model path for kleio_lite or "
                            "patterns_lite policies."))
  parser.add_argument("--policy",
                      choices=("lru", "random", "lfu", "clock", "qmap",
                               "kleio_lite", "patterns_lite"),
                      required=True)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--page_shift", type=int, default=0)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--rank_guard", type=int, default=0,
                      help=("For QMAP, restrict inference to the first N "
                            "LRU-tail candidates. 0 disables the guard."))
  parser.add_argument("--rank_score_penalty", type=float, default=0.0,
                      help=("For QMAP, subtract penalty * normalized_rank "
                            "from candidate scores. Rank 0 is the oldest "
                            "LRU-tail page; 0 disables the penalty."))
  parser.add_argument("--lookahead", type=int, default=256,
                      help=("Scale used for DRAM residency features. Match "
                            "the generator lookahead used for training."))
  parser.add_argument("--random_seed", type=int, default=0)
  parser.add_argument("--device", default=None,
                      help="cpu, cuda, or omitted for auto selection.")
  parser.add_argument("--dram_read_cost", type=float, default=DRAM_READ_COST)
  parser.add_argument("--dram_write_cost", type=float, default=DRAM_WRITE_COST)
  parser.add_argument("--nvm_read_cost", type=float, default=NVM_READ_COST)
  parser.add_argument("--nvm_write_cost", type=float, default=NVM_WRITE_COST,
                      help=("Weighted access cost for a write served from "
                            "NVM. Default is 8 for write-pressure testing."))
  parser.add_argument("--migration_cost", type=float, default=MIGRATION_COST)
  parser.add_argument("--json_output", default=None,
                      help="Optional path to write machine-readable metrics.")
  parser.add_argument("--ablation", choices=ABLATION_CHOICES, default=None,
                      help=("QMAP ablation variant. Defaults to the checkpoint "
                            "model_args value for --policy qmap."))
  return parser


class ReplayStats(object):
  """Tracks replay metrics."""

  def __init__(self):
    self.total_accesses = 0
    self.hit_count = 0
    self.miss_count = 0
    self.migration_count = 0
    self.nvm_read_count = 0
    self.nvm_write_count = 0
    self.weighted_access_cost = 0.0
    self.decision_count = 0
    self.decision_time_seconds = 0.0
    self.selector_decision_count = 0
    self.selector_time_seconds = 0.0
    self.selector_B_t = []
    self.selector_K_t = []

  @property
  def hit_rate(self):
    if self.total_accesses == 0:
      return 0.0
    return self.hit_count / float(self.total_accesses)

  @property
  def avg_decision_time_ms(self):
    if self.decision_count == 0:
      return 0.0
    return self.decision_time_seconds * 1000.0 / float(self.decision_count)

  @property
  def avg_selector_time_ms(self):
    if self.selector_decision_count == 0:
      return 0.0
    return (self.selector_time_seconds * 1000.0 /
            float(self.selector_decision_count))

  def record_selector(self, snapshot):
    self.selector_decision_count += 1
    self.selector_time_seconds += snapshot["selector_time_seconds"]
    self.selector_B_t.append(snapshot["B_t"])
    self.selector_K_t.append(snapshot["K_t"])

  def to_dict(self, policy, trace_path, dram_capacity):
    return {
        "policy": policy,
        "trace_path": trace_path,
        "dram_capacity": dram_capacity,
        "total_accesses": self.total_accesses,
        "hits": self.hit_count,
        "misses": self.miss_count,
        "hit_rate": self.hit_rate,
        "hit_rate_percent": self.hit_rate * 100.0,
        "migrations": self.migration_count,
        "nvm_reads": self.nvm_read_count,
        "nvm_writes": self.nvm_write_count,
        "weighted_access_cost": self.weighted_access_cost,
        "decision_count": self.decision_count,
        "decision_time_seconds": self.decision_time_seconds,
        "avg_decision_time_ms": self.avg_decision_time_ms,
        "candidate_filter": {
            "decision_count": self.selector_decision_count,
            "min_B_t": min(self.selector_B_t) if self.selector_B_t else 0,
            "max_B_t": max(self.selector_B_t) if self.selector_B_t else 0,
            "mean_B_t": (sum(self.selector_B_t) /
                         float(len(self.selector_B_t))
                         if self.selector_B_t else 0.0),
            "min_K_t": min(self.selector_K_t) if self.selector_K_t else 0,
            "max_K_t": max(self.selector_K_t) if self.selector_K_t else 0,
            "mean_K_t": (sum(self.selector_K_t) /
                         float(len(self.selector_K_t))
                         if self.selector_K_t else 0.0),
            "selector_time_seconds": self.selector_time_seconds,
            "avg_selector_time_ms": self.avg_selector_time_ms,
        },
    }


def dram_access_cost(rw, args):
  return args.dram_write_cost if rw else args.dram_read_cost


def nvm_access_cost(rw, args):
  return args.nvm_write_cost if rw else args.nvm_read_cost


def rank_score_penalty_values(candidate_count, penalty):
  """Returns per-rank score penalties for LRU-tail candidates."""
  if candidate_count <= 0:
    raise ValueError("candidate_count must be positive.")
  if penalty < 0.0:
    raise ValueError("rank_score_penalty must be non-negative.")
  if candidate_count == 1 or penalty == 0.0:
    return [0.0 for _ in range(candidate_count)]
  normalizer = float(candidate_count - 1)
  return [penalty * rank / normalizer for rank in range(candidate_count)]


def uses_qformer(ablation):
  return ablation == "full"


def checkpoint_uses_qformer(model_args, extractor_state):
  """Keeps old Q-Former checkpoints loadable while new runs default to Pool."""
  ablation = model_args.get("ablation", "mean_pool")
  if uses_qformer(ablation):
    return True
  return any(key.startswith("_qformer.") for key in extractor_state)


def infer_scorer_scoring_input(model_args, scorer_state):
  """Infers whether a checkpoint scores cat(u, g) or the context vector g."""
  hidden_dim = model_args.get("hidden_dim", 18)
  first_weight = scorer_state.get("_scoring_mlp.0.weight")
  if first_weight is not None and len(first_weight.shape) == 2:
    input_dim = first_weight.shape[1]
    if input_dim == hidden_dim:
      return "context"
    if input_dim == hidden_dim * 2:
      return "concat"
  return model_args.get("scoring_input", "context")


def infer_extractor_pooling_strategy(model_args, scoring_input):
  if model_args.get("pooling_strategy"):
    return model_args["pooling_strategy"]
  return "none" if scoring_input == "context" else "mean"


def update_mru(dram_pages, page):
  """Moves an existing DRAM page to MRU position."""
  dram_pages.remove(page)
  dram_pages.insert(0, page)


def choose_victim_lru(dram_pages):
  return dram_pages[-1]


def choose_victim_random(dram_pages, rng):
  return rng.choice(dram_pages)


def choose_victim_lfu(dram_pages, access_frequency, last_access_time):
  return min(
      dram_pages,
      key=lambda page: (access_frequency.get(page, 0),
                        last_access_time.get(page, -1)))


def is_learned_policy(policy):
  return policy in ("kleio_lite", "patterns_lite")


def validate_checkpoint_config_contract(checkpoint, config, selector_params):
  """Rejects every frozen Generator/Trainer/Replay contract mismatch."""
  if checkpoint.get("schema_version") != finals_config.SCHEMA_VERSION:
    raise ValueError("Checkpoint is not a CAPD finals_v2 checkpoint.")
  expected_contract = finals_config.contract_from_config(config)
  finals_config.assert_contract_matches(
      expected_contract, checkpoint.get("experiment_contract", {}),
      "checkpoint")
  expected_config_fingerprint = finals_config.config_fingerprint(config)
  if checkpoint.get("config_fingerprint") != expected_config_fingerprint:
    raise ValueError("Checkpoint/config fingerprint mismatch.")
  expected_selector_fingerprint = finals_config.selector_fingerprint(
      selector_params)
  if checkpoint.get("selector_fingerprint") != expected_selector_fingerprint:
    raise ValueError("Checkpoint/selector fingerprint mismatch.")
  if checkpoint.get("workload") != config["run"]["workload"]:
    raise ValueError("Checkpoint/workload mismatch.")
  model_args = checkpoint.get("model_args", {})
  if int(model_args.get("page_state_dim", -1)) != expected_contract[
      "page_state_dim"]:
    raise ValueError("Checkpoint model page_state_dim mismatch.")
  return expected_contract


def apply_replay_finals_config(args):
  """Makes the resolved config authoritative for every replay policy."""
  config_path = getattr(args, "config", None)
  if not config_path:
    if not getattr(args, "trace_path", None):
      raise ValueError("--trace_path is required when --config is omitted.")
    return None
  config = finals_config.load_config(config_path, require_resolved=True)
  configured_trace = config["data"]["test_trace"]
  supplied_trace = getattr(args, "trace_path", None)
  if (supplied_trace and
      os.path.abspath(supplied_trace) != os.path.abspath(configured_trace)):
    raise ValueError("--trace_path does not match resolved config test_trace.")
  args.trace_path = configured_trace
  args.dram_capacity = int(config["memory"]["dram_capacity_pages"])
  args.history_length = int(config["history"]["transformer_H"])
  args.lookahead = int(config["features"]["residency_scale_Lres"])
  args.page_shift = int(config.get("trace", {}).get("page_shift", 12))
  args.random_seed = int(config["evaluation"]["random_seed"])
  for name, value in config["cost_model"].items():
    setattr(args, name, float(value))
  if getattr(args, "rank_guard", 0) != 0:
    raise ValueError("rank_guard is not part of the frozen finals_v2 path.")
  if getattr(args, "rank_score_penalty", 0.0) != 0.0:
    raise ValueError(
        "rank_score_penalty is not part of the frozen finals_v2 path.")
  if args.policy == "qmap":
    if not getattr(args, "selector_params", None):
      raise ValueError("--selector_params is required for finals QMAP replay.")
    args.candidate_count = int(config["candidate"]["retained_K"])
  return config


def build_replay_decision_snapshot(
    dram_pages, decision_history, access_index, dram_insert_time, dirty_pages,
    selector_history, config, selector_params):
  """Explicit adapter used by replay and Generator/Replay equivalence tests."""
  return candidate_filter.build_filtered_candidate_snapshot(
      dram_pages, decision_history, access_index, dram_insert_time,
      dirty_pages, selector_history, config, selector_params)


class ClockPolicy(object):
  """Small CLOCK policy over the current DRAM pages."""

  def __init__(self):
    self._reference_bits = {}
    self._hand = 0

  def touch(self, page):
    self._reference_bits[page] = 1

  def remove(self, page):
    self._reference_bits.pop(page, None)

  def choose_victim(self, dram_pages):
    if not dram_pages:
      raise ValueError("CLOCK cannot choose from an empty DRAM.")
    if self._hand >= len(dram_pages):
      self._hand = 0
    while True:
      page = dram_pages[self._hand]
      if self._reference_bits.get(page, 0) == 0:
        victim = page
        self._hand %= len(dram_pages)
        return victim
      self._reference_bits[page] = 0
      self._hand = (self._hand + 1) % len(dram_pages)


class QMAPPolicy(object):
  """Loads QMAP and uses the shared B-to-K selector in finals_v2."""

  def __init__(self, checkpoint_path, device, history_length, candidate_count,
               lookahead=256, ablation=None, rank_guard=0,
               rank_score_penalty=0.0, config=None, selector_params=None):
    if checkpoint_path is None:
      raise ValueError("--checkpoint is required when --policy=qmap.")
    if candidate_count <= 0:
      raise ValueError("candidate_count must be positive.")
    if rank_guard < 0 or rank_score_penalty < 0.0:
      raise ValueError("rank guard/penalty must be non-negative.")

    # Lazy imports keep classical-baseline replay independent of torch.
    import torch
    from policy_learning.cache_model import embed
    from policy_learning.cache_model import model

    self._torch = torch
    self._device = device
    self._config = config
    self._selector_params = selector_params
    self._history_length = history_length
    self._candidate_count = candidate_count
    self._effective_candidate_count = (
        min(candidate_count, rank_guard) if rank_guard else candidate_count)
    self._rank_score_penalty = rank_score_penalty
    self._lookahead = lookahead
    self._selector_history = None
    self.last_selector_snapshot = None

    checkpoint = torch.load(checkpoint_path, map_location=device)
    if config is not None:
      if selector_params is None:
        raise ValueError("Finals QMAP requires selector_params.")
      contract = validate_checkpoint_config_contract(
          checkpoint, config, selector_params)
      self._history_length = contract["H"]
      self._candidate_count = contract["K"]
      self._effective_candidate_count = contract["K"]
      self._lookahead = contract["Lres"]
      self._selector_history = candidate_filter.SelectorHistory(
          contract["Hc"])

    model_args = checkpoint.get("model_args", {})
    self._ablation = ablation or model_args.get("ablation", "mean_pool")
    extractor_state = checkpoint["extractor"]
    scorer_state = checkpoint["scorer"]
    scoring_input = infer_scorer_scoring_input(model_args, scorer_state)
    pooling_strategy = infer_extractor_pooling_strategy(
        model_args, scoring_input)
    self._feature_embedder = embed.QMAPAccessFeatureEmbedder(
        address_embedder=embed.DynamicVocabEmbedder(
            embed_dim=model_args.get("address_embed_dim", 8),
            max_vocab_size=model_args.get("address_vocab_size", 100000)),
        pc_embedder=embed.DynamicVocabEmbedder(
            embed_dim=model_args.get("pc_embed_dim", 8),
            max_vocab_size=model_args.get("pc_vocab_size", 50000)),
        rw_embedder=embed.RWFlagEmbedder(
            embed_dim=model_args.get("rw_embed_dim", 2))).to(device)
    self._extractor = model.QMAPMacroscopicPatternExtractor(
        hidden_dim=model_args.get("hidden_dim", 18),
        num_queries=model_args.get("num_queries", 4),
        num_layers=model_args.get("num_layers", 1),
        num_heads=model_args.get("num_heads", 2),
        feedforward_dim=model_args.get("feedforward_dim"),
        dropout=model_args.get("dropout", 0.0),
        use_qformer=checkpoint_uses_qformer(model_args, extractor_state),
        pooling_strategy=pooling_strategy).to(device)
    self._page_state_dim = model_args.get("page_state_dim", 3)
    self._scorer = model.QMAPCandidateScorer(
        hidden_dim=model_args.get("hidden_dim", 18),
        page_state_dim=self._page_state_dim,
        page_embed_dim=model_args.get("page_embed_dim", 8),
        page_vocab_size=model_args.get("page_vocab_size", 100000),
        num_heads=model_args.get("num_heads", 2),
        dropout=model_args.get("dropout", 0.0),
        page_dim=model_args.get("page_dim", 21),
        scoring_input=scoring_input).to(device)
    self._feature_embedder.load_state_dict(checkpoint["feature_embedder"])
    self._extractor.load_state_dict(extractor_state)
    self._scorer.load_state_dict(scorer_state)
    self._feature_embedder.eval()
    self._extractor.eval()
    self._scorer.eval()

  def synchronize(self):
    if self._device.type == "cuda" and self._torch.cuda.is_available():
      self._torch.cuda.synchronize(self._device)

  def observe(self, page, rw, access_index):
    # Called after the decision and current-page insertion, so selector
    # features at a decision never contain the triggering miss.
    if self._selector_history is not None:
      self._selector_history.observe(page, rw, access_index)

  def choose_victim(self, dram_pages, history, max_page, access_index,
                    dram_insert_time, dirty_pages):
    snapshot = None
    if self._config is not None:
      snapshot = build_replay_decision_snapshot(
          dram_pages, history, access_index, dram_insert_time, dirty_pages,
          self._selector_history, self._config, self._selector_params)
      candidates = snapshot["candidate_pages"]
      candidate_mask = snapshot["candidate_mask"]
      candidate_state_features = snapshot["candidate_state_features"]
    else:
      candidates, candidate_mask = get_lru_tail_candidates_and_mask(
          dram_pages, self._effective_candidate_count)
      candidate_state_features = []
      for rank, candidate in enumerate(candidates):
        residency_duration = access_index - dram_insert_time.get(
            candidate, access_index)
        if self._page_state_dim >= 4:
          features = build_candidate_state_features(
              candidate, history, residency_duration,
              candidate in dirty_pages, self._lookahead, rank=rank,
              candidate_count=self._effective_candidate_count)
        else:
          features = build_candidate_state_features(
              candidate, history, residency_duration,
              candidate in dirty_pages, self._history_length)
        candidate_state_features.append(features)

    physical_address, pc, rw = apply_history_ablation(
        *padded_history(history, self._history_length),
        ablation=self._ablation)
    torch = self._torch
    with torch.no_grad():
      physical_address = torch.tensor(
          [physical_address], dtype=torch.long, device=self._device)
      pc = torch.tensor([pc], dtype=torch.long, device=self._device)
      rw = torch.tensor([rw], dtype=torch.long, device=self._device)
      candidate_pages = torch.tensor(
          [candidates], dtype=torch.long, device=self._device)
      candidate_state_features = torch.tensor(
          [candidate_state_features], dtype=torch.float32,
          device=self._device)
      candidate_mask_tensor = torch.tensor(
          [candidate_mask], dtype=torch.float32, device=self._device)
      access_features = self._feature_embedder(physical_address, pc, rw)
      z = self._extractor(access_features)
      eviction_scores = self._scorer(
          z, candidate_pages, candidate_state_features,
          candidate_mask_tensor)
      if self._rank_score_penalty:
        rank_penalties = torch.tensor(
            [rank_score_penalty_values(
                eviction_scores.shape[1], self._rank_score_penalty)],
            dtype=eviction_scores.dtype, device=self._device)
        eviction_scores = eviction_scores - rank_penalties
      victim_index = int(torch.argmax(eviction_scores, dim=1).item())
    self.last_selector_snapshot = snapshot
    return candidates[victim_index]


def replay(args, finals_replay_config=None):
  trace, _ = read_trace(args.trace_path, args.page_shift)
  max_page = max((item["page"] for item in trace), default=1)
  stats = ReplayStats()
  dram_pages = []
  nvm_pages = set()
  dram_insert_time = {}
  dirty_pages = set()
  access_frequency = {}
  last_access_time = {}
  history = []
  rng = random.Random(args.random_seed)
  clock_policy = ClockPolicy()
  learned_policy = None

  qmap_policy = None
  if args.policy == "qmap":
    import torch
    device = args.device
    if device is None:
      device = "cuda" if torch.cuda.is_available() else "cpu"
    selector_params = None
    if finals_replay_config is not None:
      selector_params = finals_config.load_json(args.selector_params)
      if selector_params.get("config_fingerprint") != (
          finals_config.config_fingerprint(finals_replay_config)):
        raise ValueError("Replay selector/config fingerprint mismatch.")
      if selector_params.get("workload") != finals_replay_config[
          "run"]["workload"]:
        raise ValueError("Replay selector/workload mismatch.")
    qmap_policy = QMAPPolicy(
        args.checkpoint,
        torch.device(device),
        args.history_length,
        args.candidate_count,
        args.lookahead,
        args.ablation,
        args.rank_guard,
        args.rank_score_penalty,
        config=finals_replay_config,
        selector_params=selector_params)
  elif is_learned_policy(args.policy):
    if args.learned_model is None:
      raise ValueError("--learned_model is required for {}.".format(
          args.policy))
    try:
      from learned_baselines import LearnedBaselinePolicy
      from learned_baselines import load_model
    except ImportError:
      from qmap.learned_baselines import LearnedBaselinePolicy
      from qmap.learned_baselines import load_model
    learned_model = load_model(args.learned_model)
    if finals_replay_config is not None:
      if learned_model.get("schema_version") != finals_config.SCHEMA_VERSION:
        raise ValueError("Learned baseline is not a finals_v2 model.")
      if learned_model.get("workload") != finals_replay_config[
          "run"]["workload"]:
        raise ValueError("Learned baseline workload mismatch.")
      trained_capacity = learned_model.get("training", {}).get(
          "dram_capacity")
      expected_capacity = int(
          finals_replay_config["memory"]["dram_capacity_pages"])
      if trained_capacity is None or int(trained_capacity) != expected_capacity:
        raise ValueError(
            "Learned baseline must be retrained for DRAM capacity {}."
            .format(expected_capacity))
      if int(learned_model.get("candidate_count", -1)) != 8:
        raise ValueError(
            "Finals learned baselines must retain their native tail-8 pool.")
    learned_policy = LearnedBaselinePolicy(learned_model)

  for access_index, access in enumerate(trace):
    page = access["page"]
    rw = access["rw"]
    stats.total_accesses += 1
    access_frequency[page] = access_frequency.get(page, 0) + 1
    last_access_time[page] = access_index

    if page in dram_pages:
      stats.hit_count += 1
      stats.weighted_access_cost += dram_access_cost(rw, args)
      if args.policy != "clock":
        update_mru(dram_pages, page)
      else:
        clock_policy.touch(page)
      if rw:
        dirty_pages.add(page)
    else:
      stats.miss_count += 1
      stats.weighted_access_cost += nvm_access_cost(rw, args)
      if rw:
        stats.nvm_write_count += 1
      else:
        stats.nvm_read_count += 1

      if len(dram_pages) >= args.dram_capacity:
        if args.policy == "qmap":
          qmap_policy.synchronize()
        decision_start = time.perf_counter()
        if args.policy == "lru":
          victim = choose_victim_lru(dram_pages)
        elif args.policy == "random":
          victim = choose_victim_random(dram_pages, rng)
        elif args.policy == "lfu":
          victim = choose_victim_lfu(
              dram_pages, access_frequency, last_access_time)
        elif args.policy == "clock":
          victim = clock_policy.choose_victim(dram_pages)
        elif is_learned_policy(args.policy):
          decision_history = (history + [access])[-args.history_length:]
          victim = learned_policy.choose_victim(
              dram_pages, decision_history, access_index, dram_insert_time,
              dirty_pages, access_frequency, last_access_time)
        else:
          # qmap_generator.py includes the current miss in the fixed-length
          # access history before constructing a training sample. Keep replay
          # inference aligned with that feature contract.
          decision_history = (history + [access])[-args.history_length:]
          victim = qmap_policy.choose_victim(
              dram_pages, decision_history, max_page, access_index,
              dram_insert_time, dirty_pages)
          selector_snapshot = qmap_policy.last_selector_snapshot
          if selector_snapshot is not None:
            stats.record_selector(selector_snapshot)
          qmap_policy.synchronize()
        stats.decision_time_seconds += time.perf_counter() - decision_start
        stats.decision_count += 1

        dram_pages.remove(victim)
        clock_policy.remove(victim)
        nvm_pages.add(victim)
        dram_insert_time.pop(victim, None)
        dirty_pages.discard(victim)
        stats.migration_count += 1
        stats.weighted_access_cost += args.migration_cost

      if page in nvm_pages:
        nvm_pages.remove(page)
      dram_pages.insert(0, page)
      clock_policy.touch(page)
      dram_insert_time[page] = access_index
      if rw:
        dirty_pages.add(page)

    history.append(access)
    if len(history) > args.history_length:
      history.pop(0)
    if qmap_policy is not None:
      qmap_policy.observe(page, rw, access_index)

  return stats


def print_stats(policy, stats):
  print("Policy:", policy)
  print("Total accesses:", stats.total_accesses)
  print("Hits:", stats.hit_count)
  print("Misses:", stats.miss_count)
  print("Hit rate: {:.2f}%".format(stats.hit_rate * 100.0))
  print("Migrations:", stats.migration_count)
  print("NVM reads:", stats.nvm_read_count)
  print("NVM writes:", stats.nvm_write_count)
  print("Weighted access cost: {:.2f}".format(stats.weighted_access_cost))
  print("Policy decisions:", stats.decision_count)
  print("Total decision time: {:.6f}s".format(stats.decision_time_seconds))
  print("Avg decision time: {:.6f} ms".format(stats.avg_decision_time_ms))
  if stats.selector_decision_count:
    print("Candidate filter decisions:", stats.selector_decision_count)
    print("Candidate B_t range: {}..{}".format(
        min(stats.selector_B_t), max(stats.selector_B_t)))
    print("Retained K_t range: {}..{}".format(
        min(stats.selector_K_t), max(stats.selector_K_t)))
    print("Avg candidate filter time: {:.6f} ms".format(
        stats.avg_selector_time_ms))


def main():
  args = build_arg_parser().parse_args()
  if args.rank_score_penalty < 0.0:
    raise ValueError("--rank_score_penalty must be non-negative.")
  replay_config = apply_replay_finals_config(args)
  stats = replay(args, finals_replay_config=replay_config)
  print_stats(args.policy, stats)
  if args.json_output:
    output_dir = os.path.dirname(os.path.abspath(args.json_output))
    if output_dir:
      os.makedirs(output_dir, exist_ok=True)
    metrics = stats.to_dict(args.policy, args.trace_path, args.dram_capacity)
    metrics["candidate_count"] = (
        8 if is_learned_policy(args.policy) else args.candidate_count)
    metrics["candidate_scope"] = (
        "full_dram" if args.policy in ("lru", "random", "lfu", "clock")
        else ("native_lru_tail_8" if is_learned_policy(args.policy)
              else "capd_selector_B_to_K"))
    metrics["rank_guard"] = args.rank_guard
    metrics["rank_score_penalty"] = args.rank_score_penalty
    metrics["command"] = " ".join(
        shlex.quote(value) for value in sys.argv)
    if replay_config is not None:
      metrics["schema_version"] = finals_config.SCHEMA_VERSION
      metrics["workload"] = replay_config["run"]["workload"]
      metrics["experiment_contract"] = finals_config.contract_from_config(
          replay_config)
      metrics["config_fingerprint"] = finals_config.config_fingerprint(
          replay_config)
      metrics["git_commit"] = replay_config.get("run", {}).get(
          "git_commit", "unknown")
      metrics["selector_params"] = args.selector_params
      if args.selector_params:
        metrics["selector_fingerprint"] = (
            finals_config.selector_fingerprint(
                finals_config.load_json(args.selector_params)))
      finals_config.write_json(
          os.path.join(output_dir, "resolved_config.json"), replay_config)
    if args.checkpoint:
      metrics["checkpoint"] = os.path.abspath(args.checkpoint)
      metrics["checkpoint_fingerprint"] = finals_config.fingerprint_file(
          args.checkpoint)
    if is_learned_policy(args.policy):
      metrics["learned_model"] = args.learned_model
      metrics["learned_model_fingerprint"] = finals_config.fingerprint_file(
          args.learned_model)
    metrics["cost_model"] = {
        "dram_read_cost": args.dram_read_cost,
        "dram_write_cost": args.dram_write_cost,
        "nvm_read_cost": args.nvm_read_cost,
        "nvm_write_cost": args.nvm_write_cost,
        "migration_cost": args.migration_cost,
    }
    with open(args.json_output, "w") as output_file:
      json.dump(
          metrics,
          output_file,
          indent=2,
          sort_keys=True)
      output_file.write("\n")


if __name__ == "__main__":
  main()
