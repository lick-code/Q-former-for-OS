# coding=utf-8
"""G12 proxy-label versus forced-first-victim window-cost audit."""

from __future__ import print_function

from qmap import stage4_common


def replay_forced_victim(state, current_access, future_accesses, victim,
                         cost_model):
  """Clone a pre-decision state, force victim, then continue with fixed LRU.

  The current miss's NVM access is common to every candidate and is reported
  separately; J includes the forced migration and all access/migration costs
  in the following complete L-access window. Dirty demotion has no extra NVM
  write, and NVM capacity is unbounded.
  """
  dram = list(state.dram_pages)
  dirty = set(state.dirty_pages)
  stage4_common.require(victim in dram, "forced victim is not resident")
  current_page = current_access["page"]
  current_rw = int(bool(current_access["rw"]))
  common_current_nvm_cost = float(cost_model[
      "nvm_write_cost" if current_rw else "nvm_read_cost"])
  dram.remove(victim)
  dirty.discard(victim)
  dram.insert(0, current_page)
  if current_rw:
    dirty.add(current_page)

  counts = {"dram_reads": 0, "dram_writes": 0,
            "nvm_reads": 0, "nvm_writes": 0,
            "future_migrations": 0}
  total = float(cost_model["migration_cost"])
  for access in future_accesses:
    page = access["page"]
    rw = int(bool(access["rw"]))
    if page in dram:
      key = "dram_writes" if rw else "dram_reads"
      counts[key] += 1
      total += float(cost_model[
          "dram_write_cost" if rw else "dram_read_cost"])
      dram.remove(page)
      dram.insert(0, page)
      if rw:
        dirty.add(page)
      continue
    key = "nvm_writes" if rw else "nvm_reads"
    counts[key] += 1
    total += float(cost_model[
        "nvm_write_cost" if rw else "nvm_read_cost"])
    if len(dram) >= state.dram_capacity:
      later_victim = dram.pop()
      dirty.discard(later_victim)
      counts["future_migrations"] += 1
      total += float(cost_model["migration_cost"])
    dram.insert(0, page)
    if rw:
      dirty.add(page)
  result = {
      "J": total,
      "forced_migration_cost": float(cost_model["migration_cost"]),
      "common_current_nvm_access_cost_excluded_from_J":
          common_current_nvm_cost,
  }
  result.update(counts)
  return result


def decision_metrics(candidate_rows, variant_name, weights):
  labels = [{"d_hat": row["d_hat"], "q_hat": row["q_hat"],
             "w_hat": row["w_hat"]} for row in candidate_rows]
  scores = stage4_common.proxy_scores(labels, weights)
  costs = [row["J"] for row in candidate_rows]
  ranks = [row["original_pool_rank"] for row in candidate_rows]
  correlation = stage4_common.spearman(scores, [-value for value in costs])
  maximum = max(scores)
  minimum = min(costs)
  proxy_top = {index for index, value in enumerate(scores) if value == maximum}
  cost_top = {index for index, value in enumerate(costs) if value == minimum}
  ndcg, indistinguishable = stage4_common.ndcg_from_costs(
      scores, costs, ranks)
  return {
      "variant": variant_name,
      "weights": list(weights),
      "spearman": correlation,
      "spearman_defined": correlation is not None,
      "top1_any_hit": float(bool(proxy_top & cost_top)),
      "ndcg": ndcg,
      "counterfactual_cost_indistinguishable": indistinguishable,
      "proxy_top_tie_size": len(proxy_top),
      "cost_top_tie_size": len(cost_top),
      "proxy_scores": scores,
  }


def audit_trace(trace, config, selector_params):
  """Audit every complete-window valid LRU decision; never reads test."""
  from qmap.finals_generator import FutureOracle
  from qmap.finals_generator import LRUBehaviorState
  from qmap.finals_generator import build_generator_decision_snapshot
  from qmap.finals_generator import has_complete_future_window
  from qmap.finals_generator import reference_labels

  lookahead = int(config["labels"]["future_lookahead_L"])
  state = LRUBehaviorState(config)
  oracle = FutureOracle(trace, lookahead, require_complete=True)
  decisions = []
  for access_index, access in enumerate(trace):
    if (state.is_decision(access["page"]) and
        has_complete_future_window(access_index, lookahead, len(trace))):
      snapshot = build_generator_decision_snapshot(
          state, access, access_index, config, selector_params)
      rows = []
      for record in snapshot["selected_records"]:
        page = record["page"]
        label = reference_labels(
            trace, access_index, page, lookahead, oracle,
            require_complete=True)
        cost = replay_forced_victim(
            state, access, trace[access_index + 1:access_index + 1 + lookahead],
            page, config["cost_model"])
        row = {
            "decision_index": access_index, "candidate_page": page,
            "original_pool_rank": record["original_pool_rank"],
            "d_hat": label["inactivity"],
            "q_hat": label["coldness"],
            "w_hat": label["write_intensity"],
        }
        row.update(cost)
        rows.append(row)
      stage4_common.require(rows, "complete decision has no valid candidates")
      variants = {
          name: decision_metrics(rows, name, weights)
          for name, weights in stage4_common.LABEL_VARIANTS.items()
      }
      for index, score in enumerate(variants["base"]["proxy_scores"]):
        rows[index]["base_y"] = score
      decisions.append({
          "decision_index": access_index,
          "candidates": rows,
          "variants": variants,
      })
    state.advance(access, access_index)
  return decisions


def summarize(decisions):
  stage4_common.require(decisions, "counterfactual audit has no decisions")
  variants = {}
  for name in stage4_common.LABEL_VARIANTS:
    rows = [decision["variants"][name] for decision in decisions]
    correlations = [row["spearman"] for row in rows
                    if row["spearman_defined"]]
    variants[name] = {
        "decision_count": len(rows),
        "valid_spearman_count": len(correlations),
        "undefined_spearman_count": len(rows) - len(correlations),
        "spearman_mean": stage4_common.mean(correlations),
        "spearman_median": (stage4_common.quantile(correlations, .5)
                            if correlations else None),
        "spearman_P25": (stage4_common.quantile(correlations, .25)
                         if correlations else None),
        "spearman_P75": (stage4_common.quantile(correlations, .75)
                         if correlations else None),
        "top1_any_hit_rate": stage4_common.mean(
            [row["top1_any_hit"] for row in rows]),
        "ndcg_mean": stage4_common.mean([row["ndcg"] for row in rows]),
        "ndcg_median": stage4_common.quantile(
            [row["ndcg"] for row in rows], .5),
        "cost_indistinguishable_ratio": stage4_common.mean([
            float(row["counterfactual_cost_indistinguishable"])
            for row in rows]),
    }
  base = variants["base"]
  for name, values in variants.items():
    values["absolute_delta_vs_base"] = {
        key: (None if values[key] is None or base[key] is None else
              values[key] - base[key])
        for key in ("spearman_mean", "top1_any_hit_rate", "ndcg_mean")
    }
  return variants
