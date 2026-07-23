# coding=utf-8
"""G11 offline-LRU versus closed-loop-CAPD distribution audit."""

from __future__ import print_function

from qmap import stage4_common


SELECTOR_FEATURES = (
    "selector_g_delta", "selector_one_minus_g_a",
    "selector_one_minus_g_w", "selector_clean", "selector_r_lru")
CANDIDATE_FEATURES = (
    "recent_frequency", "dirty_state", "normalized_residency",
    "original_r_lru")
DECISION_FEATURES = ("B_t", "K_t", "dirty_ratio", "decision_interval")
BINARY_FEATURES = {"selector_clean", "dirty_state"}
NUMERIC_SEMANTICS_VERSION = "capd_g11_distribution_numeric_v1"


def _empty_distribution(identity):
  return {"identity": identity,
          "values": {name: [] for name in
                     SELECTOR_FEATURES + CANDIDATE_FEATURES +
                     DECISION_FEATURES}}


def _record(distribution, snapshot, dirty_pages, previous_index,
            access_index):
  for record in snapshot["pool_records"]:
    for name, value in zip(SELECTOR_FEATURES,
                           record["selector_features"]):
      distribution["values"][name].append(value)
  valid = sum(snapshot["candidate_mask"])
  for index in range(valid):
    for name, value in zip(CANDIDATE_FEATURES,
                           snapshot["candidate_state_features"][index]):
      distribution["values"][name].append(value)
  distribution["values"]["B_t"].append(snapshot["B_t"])
  distribution["values"]["K_t"].append(snapshot["K_t"])
  distribution["values"]["dirty_ratio"].append(
      len(dirty_pages) / float(max(1, len(snapshot["P_t"]))))
  # The first decision has no preceding decision inside this trace and is not
  # assigned an artificial zero interval.
  if previous_index is not None:
    distribution["values"]["decision_interval"].append(
        access_index - previous_index)


def collect_lru(trace, config, selector_params, distribution_name):
  from qmap.finals_generator import LRUBehaviorState
  from qmap.finals_generator import build_generator_decision_snapshot
  distribution = _empty_distribution({
      "name": distribution_name, "policy": "lru",
      "trace_role": "train" if distribution_name == "A" else "valid",
      "seed": None})
  state = LRUBehaviorState(config)
  previous = None
  for access_index, access in enumerate(trace):
    if state.is_decision(access["page"]):
      snapshot = build_generator_decision_snapshot(
          state, access, access_index, config, selector_params)
      _record(distribution, snapshot, state.dirty_pages, previous,
              access_index)
      previous = access_index
    state.advance(access, access_index)
  return distribution


def collect_capd(trace, config, selector_params, checkpoint_path, seed,
                 device=None):
  """Replay valid closed-loop CAPD for diagnostics, without future labels."""
  import torch
  from qmap.qmap_eval import QMAPPolicy
  from qmap.qmap_eval import update_mru

  device = torch.device(
      device or ("cuda" if torch.cuda.is_available() else "cpu"))
  contract = config["candidate"]
  policy = QMAPPolicy(
      checkpoint_path, device,
      int(config["history"]["transformer_H"]),
      int(contract["retained_K"]),
      int(config["features"]["residency_scale_Lres"]),
      "cross_attention", 0, 0.0, config=config,
      selector_params=selector_params)
  distribution = _empty_distribution({
      "name": "C", "policy": "capd_closed_loop", "trace_role": "valid",
      "seed": int(seed)})
  dram = []
  dirty = set()
  insert_time = {}
  history = []
  previous = None
  decision_count = 0
  max_page = max((row["page"] for row in trace), default=1)
  capacity = int(config["memory"]["dram_capacity_pages"])
  for access_index, access in enumerate(trace):
    page = access["page"]
    rw = int(bool(access["rw"]))
    if page in dram:
      update_mru(dram, page)
      if rw:
        dirty.add(page)
    else:
      if len(dram) >= capacity:
        decision_history = (history + [access])[-int(
            config["history"]["transformer_H"]):]
        victim = policy.choose_victim(
            dram, decision_history, max_page, access_index,
            insert_time, dirty)
        snapshot = policy.last_selector_snapshot
        stage4_common.require(snapshot is not None,
                              "closed-loop decision has no selector snapshot")
        _record(distribution, snapshot, dirty, previous, access_index)
        previous = access_index
        decision_count += 1
        if decision_count % 500 == 0:
          print("[G11 REPLAY] seed={} decisions={} accesses={}/{}".format(
              seed, decision_count, access_index + 1, len(trace)), flush=True)
        dram.remove(victim)
        dirty.discard(victim)
        insert_time.pop(victim, None)
      dram.insert(0, page)
      insert_time[page] = access_index
      if rw:
        dirty.add(page)
    history.append(access)
    if len(history) > int(config["history"]["transformer_H"]):
      history.pop(0)
    policy.observe(page, rw, access_index)
  return distribution


def compare(reference, observed):
  result = {}
  for name in SELECTOR_FEATURES + CANDIDATE_FEATURES + DECISION_FEATURES:
    left = reference["values"][name]
    right = observed["values"][name]
    stage4_common.require(left and right,
                          "empty distribution feature {}".format(name))
    if name in BINARY_FEATURES:
      left = [int(value) for value in left]
      right = [int(value) for value in right]
      result[name] = stage4_common.binary_distance(left, right)
    else:
      result[name] = stage4_common.distribution_distance(left, right)
  return result


def audit_triplet(distribution_a, distribution_b, distribution_c):
  stage4_common.require(distribution_a["identity"]["name"] == "A",
                        "first distribution must be A")
  stage4_common.require(distribution_b["identity"]["name"] == "B",
                        "second distribution must be B")
  stage4_common.require(distribution_c["identity"]["name"] == "C",
                        "third distribution must be C")
  return {
      "A_vs_C_total_shift": compare(distribution_a, distribution_c),
      "A_vs_B_split_drift": compare(distribution_a, distribution_b),
      "B_vs_C_policy_shift": compare(distribution_b, distribution_c),
  }
