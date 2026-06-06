# coding=utf-8
"""Replay evaluation for QMAP page-migration policies.

The evaluator replays a page trace against a small DRAM/NVM model and reports
the prototype metrics used by the paper experiments:

  - hit rate
  - NVM reads/writes
  - migration count
  - weighted access cost
  - policy decision/inference overhead

Supported policies are LRU, Random, LFU, CLOCK, and QMAP. The QMAP path loads a
checkpoint produced by qmap_train.py and uses the same lightweight feature
construction as qmap_generator.py.
"""

import argparse
import json
import os
import random
import sys
import time

from qmap_generator import build_candidate_state_features
from qmap_generator import apply_history_ablation
from qmap_generator import get_lru_tail_candidates_and_mask
from qmap_generator import padded_history
from qmap_generator import read_trace


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)


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
  parser.add_argument("--trace_path", required=True,
                      help="Input CSV trace with PC,Address and optional RW.")
  parser.add_argument("--checkpoint", default=None,
                      help="QMAP checkpoint path. Required for --policy qmap.")
  parser.add_argument("--policy",
                      choices=("lru", "random", "lfu", "clock", "qmap"),
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
  """Loads a trained QMAP checkpoint and scores LRU-tail candidates."""

  def __init__(self, checkpoint_path, device, history_length, candidate_count,
               lookahead=256, ablation=None, rank_guard=0,
               rank_score_penalty=0.0):
    if checkpoint_path is None:
      raise ValueError("--checkpoint is required when --policy=qmap.")
    if candidate_count <= 0:
      raise ValueError("candidate_count must be positive.")
    if rank_guard < 0:
      raise ValueError("rank_guard must be non-negative.")
    if rank_score_penalty < 0.0:
      raise ValueError("rank_score_penalty must be non-negative.")

    # Lazy imports keep LRU/Random evaluation runnable without importing torch.
    import torch
    from policy_learning.cache_model import embed
    from policy_learning.cache_model import model

    self._torch = torch
    self._device = device
    self._history_length = history_length
    self._candidate_count = candidate_count
    self._effective_candidate_count = (
        min(candidate_count, rank_guard) if rank_guard else candidate_count)
    self._rank_score_penalty = rank_score_penalty
    self._lookahead = lookahead

    checkpoint = torch.load(checkpoint_path, map_location=device)
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

  def choose_victim(self, dram_pages, history, max_page, access_index,
                    dram_insert_time, dirty_pages):
    candidates, candidate_mask = get_lru_tail_candidates_and_mask(
        dram_pages, self._effective_candidate_count)
    physical_address, pc, rw = apply_history_ablation(
        *padded_history(history, self._history_length),
        ablation=self._ablation)
    candidate_state_features = []
    for rank, candidate in enumerate(candidates):
      residency_duration = access_index - dram_insert_time.get(
          candidate, access_index)
      if self._page_state_dim >= 4:
        features = build_candidate_state_features(
            candidate, history, residency_duration, candidate in dirty_pages,
            self._lookahead, rank=rank,
            candidate_count=self._effective_candidate_count)
      else:
        features = build_candidate_state_features(
            candidate, history, residency_duration, candidate in dirty_pages,
            self._history_length)
      candidate_state_features.append(features)

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
      candidate_mask = torch.tensor(
          [candidate_mask], dtype=torch.float32, device=self._device)

      access_features = self._feature_embedder(physical_address, pc, rw)
      z = self._extractor(access_features)
      eviction_scores = self._scorer(
          z, candidate_pages, candidate_state_features, candidate_mask)
      if self._rank_score_penalty:
        rank_penalties = torch.tensor(
            [rank_score_penalty_values(
                eviction_scores.shape[1], self._rank_score_penalty)],
            dtype=eviction_scores.dtype,
            device=self._device)
        eviction_scores = eviction_scores - rank_penalties
      victim_index = int(torch.argmax(eviction_scores, dim=1).item())
    return candidates[victim_index]


def replay(args):
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

  qmap_policy = None
  if args.policy == "qmap":
    import torch
    device = args.device
    if device is None:
      device = "cuda" if torch.cuda.is_available() else "cpu"
    qmap_policy = QMAPPolicy(
        args.checkpoint,
        torch.device(device),
        args.history_length,
        args.candidate_count,
        args.lookahead,
        args.ablation,
        args.rank_guard,
        args.rank_score_penalty)

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
        else:
          # qmap_generator.py includes the current miss in the fixed-length
          # access history before constructing a training sample. Keep replay
          # inference aligned with that feature contract.
          decision_history = (history + [access])[-args.history_length:]
          victim = qmap_policy.choose_victim(
              dram_pages, decision_history, max_page, access_index,
              dram_insert_time, dirty_pages)
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


def main():
  args = build_arg_parser().parse_args()
  if args.rank_score_penalty < 0.0:
    raise ValueError("--rank_score_penalty must be non-negative.")
  stats = replay(args)
  print_stats(args.policy, stats)
  if args.json_output:
    output_dir = os.path.dirname(os.path.abspath(args.json_output))
    if output_dir:
      os.makedirs(output_dir, exist_ok=True)
    metrics = stats.to_dict(args.policy, args.trace_path, args.dram_capacity)
    metrics["candidate_count"] = args.candidate_count
    metrics["rank_guard"] = args.rank_guard
    metrics["rank_score_penalty"] = args.rank_score_penalty
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
