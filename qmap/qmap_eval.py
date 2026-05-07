# coding=utf-8
"""Replay evaluation for QMAP page-migration policies.

This script replays a memory trace and compares simple page placement policies:
  - lru
  - random
  - qmap

It intentionally does not modify or depend on the training loop. The QMAP path
loads the checkpoint produced by qmap_train.py and uses the same lightweight
feature construction used by qmap_generator.py.
"""

import argparse
import os
import random
import sys

from qmap_generator import build_candidate_state_features
from qmap_generator import get_lru_tail_candidates_and_mask
from qmap_generator import padded_history
from qmap_generator import read_trace


PROJECT_PARENT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_PARENT not in sys.path:
  sys.path.insert(0, PROJECT_PARENT)


DRAM_READ_COST = 1.0
DRAM_WRITE_COST = 1.0
NVM_READ_COST = 2.0
NVM_WRITE_COST = 4.0
MIGRATION_COST = 10.0


def build_arg_parser():
  parser = argparse.ArgumentParser(description="Evaluate QMAP by trace replay.")
  parser.add_argument("--trace_path", required=True,
                      help="Input CSV trace with PC,Address and optional RW.")
  parser.add_argument("--checkpoint", default=None,
                      help="QMAP checkpoint path. Required for --policy qmap.")
  parser.add_argument("--policy", choices=("lru", "random", "qmap"),
                      required=True)
  parser.add_argument("--dram_capacity", type=int, default=128)
  parser.add_argument("--page_shift", type=int, default=0)
  parser.add_argument("--history_length", type=int, default=10)
  parser.add_argument("--candidate_count", type=int, default=64)
  parser.add_argument("--device", default=None,
                      help="cpu, cuda, or omitted for auto selection.")
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

  @property
  def hit_rate(self):
    if self.total_accesses == 0:
      return 0.0
    return self.hit_count / float(self.total_accesses)


def dram_access_cost(rw):
  return DRAM_WRITE_COST if rw else DRAM_READ_COST


def nvm_access_cost(rw):
  return NVM_WRITE_COST if rw else NVM_READ_COST


def update_mru(dram_pages, page):
  """Moves an existing DRAM page to MRU position."""
  dram_pages.remove(page)
  dram_pages.insert(0, page)


def choose_victim_lru(dram_pages):
  return dram_pages[-1]


def choose_victim_random(dram_pages, rng):
  return rng.choice(dram_pages)


class QMAPPolicy(object):
  """Loads a trained QMAP checkpoint and scores LRU-tail candidates."""

  def __init__(self, checkpoint_path, device, history_length, candidate_count):
    if checkpoint_path is None:
      raise ValueError("--checkpoint is required when --policy=qmap.")

    # Lazy imports keep LRU/Random evaluation runnable without importing torch.
    import torch
    from cache_replacement.policy_learning.cache_model import embed
    from cache_replacement.policy_learning.cache_model import model

    self._torch = torch
    self._device = device
    self._history_length = history_length
    self._candidate_count = candidate_count

    checkpoint = torch.load(checkpoint_path, map_location=device)
    model_args = checkpoint.get("model_args", {})

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
        num_heads=model_args.get("num_heads", 2)).to(device)
    self._scorer = model.QMAPCandidateScorer(
        hidden_dim=model_args.get("hidden_dim", 18),
        page_state_dim=model_args.get("page_state_dim", 3),
        page_embed_dim=model_args.get("page_embed_dim", 8),
        page_vocab_size=model_args.get("page_vocab_size", 100000),
        num_heads=model_args.get("num_heads", 2),
        page_dim=model_args.get("page_dim", 21)).to(device)

    self._feature_embedder.load_state_dict(checkpoint["feature_embedder"])
    self._extractor.load_state_dict(checkpoint["extractor"])
    self._scorer.load_state_dict(checkpoint["scorer"])

    self._feature_embedder.eval()
    self._extractor.eval()
    self._scorer.eval()

  def choose_victim(self, dram_pages, history, max_page, access_index,
                    dram_insert_time, dirty_pages):
    candidates, candidate_mask = get_lru_tail_candidates_and_mask(
        dram_pages, self._candidate_count)
    physical_address, pc, rw = padded_history(history, self._history_length)
    candidate_state_features = []
    for candidate in candidates:
      residency_duration = access_index - dram_insert_time.get(
          candidate, access_index)
      candidate_state_features.append(build_candidate_state_features(
          candidate, history, residency_duration, candidate in dirty_pages,
          self._history_length))

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
  history = []
  rng = random.Random(0)

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
        args.candidate_count)

  for access_index, access in enumerate(trace):
    page = access["page"]
    rw = access["rw"]
    stats.total_accesses += 1

    if page in dram_pages:
      stats.hit_count += 1
      stats.weighted_access_cost += dram_access_cost(rw)
      update_mru(dram_pages, page)
      if rw:
        dirty_pages.add(page)
    else:
      stats.miss_count += 1
      stats.weighted_access_cost += nvm_access_cost(rw)
      if rw:
        stats.nvm_write_count += 1
      else:
        stats.nvm_read_count += 1

      if len(dram_pages) >= args.dram_capacity:
        if args.policy == "lru":
          victim = choose_victim_lru(dram_pages)
        elif args.policy == "random":
          victim = choose_victim_random(dram_pages, rng)
        else:
          victim = qmap_policy.choose_victim(
              dram_pages, history, max_page, access_index, dram_insert_time,
              dirty_pages)

        dram_pages.remove(victim)
        nvm_pages.add(victim)
        dram_insert_time.pop(victim, None)
        dirty_pages.discard(victim)
        stats.migration_count += 1
        stats.weighted_access_cost += MIGRATION_COST

      if page in nvm_pages:
        nvm_pages.remove(page)
      dram_pages.insert(0, page)
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


def main():
  args = build_arg_parser().parse_args()
  stats = replay(args)
  print_stats(args.policy, stats)


if __name__ == "__main__":
  main()
