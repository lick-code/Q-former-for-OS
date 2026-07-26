# coding=utf-8
"""Pure-Python summarization for the CAPD bridge diagnostic."""

from __future__ import print_function

import math

from qmap import bridge_variants


def _mean(values):
  values = [float(value) for value in values]
  return sum(values) / float(len(values)) if values else 0.0


def _sample_stddev(values):
  values = [float(value) for value in values]
  if len(values) <= 1:
    return 0.0
  center = _mean(values)
  return math.sqrt(
      sum((value - center) ** 2 for value in values) /
      float(len(values) - 1))


def _policy_means(rows):
  grouped = {}
  for row in rows:
    policy = str(row["policy"]).lower()
    grouped.setdefault(policy, []).append(
        float(row["weighted_access_cost"]))
  return {policy: _mean(values) for policy, values in grouped.items()}


def _best_classic(rows):
  means = _policy_means(rows)
  missing = [
      policy for policy in bridge_variants.CLASSIC_POLICIES
      if policy not in means]
  if missing:
    raise ValueError("Bridge baseline set is incomplete: {}".format(missing))
  return min(
      means.items(), key=lambda item: (float(item[1]), item[0]))


def summarize_case(case, qmap_rows, baseline_rows, evidence_source):
  if not qmap_rows:
    raise ValueError("Bridge case has no QMAP rows: {}".format(
        case["case_id"]))
  if any(str(row.get("policy", "")).lower() != "qmap"
         for row in qmap_rows):
    raise ValueError("Bridge QMAP rows contain a non-QMAP policy.")
  best_policy, best_cost = _best_classic(baseline_rows)
  costs = [float(row["weighted_access_cost"]) for row in qmap_rows]
  improvements = [
      (best_cost - cost) * 100.0 / best_cost for cost in costs]
  diagnostics = [
      row.get("bridge_diagnostics") for row in qmap_rows
      if row.get("bridge_diagnostics") is not None]
  fingerprints = {
      item.get("victim_sequence_fingerprint") for item in diagnostics
      if item.get("victim_sequence_fingerprint")}
  outcome_keys = ("qmap_better", "qmap_worse", "equal")
  outcome_totals = {
      key: sum(
          int(item.get("disagreement_next_use_outcomes", {}).get(key, 0))
          for item in diagnostics)
      for key in outcome_keys}
  row = {
      "case_id": case["case_id"],
      "source_id": case["source_id"],
      "engine": case["engine"],
      "candidate_mode": case["candidate_mode"],
      "D": int(case["D"]), "B": int(case["B"]), "K": int(case["K"]),
      "evidence_source": evidence_source,
      "qmap_seed_count": len(qmap_rows),
      "qmap_cost_mean": _mean(costs),
      "qmap_cost_sample_stddev": _sample_stddev(costs),
      "qmap_cost_min": min(costs),
      "qmap_cost_max": max(costs),
      "best_classic_policy": best_policy,
      "best_classic_cost_mean": float(best_cost),
      "improvement_percent_mean": _mean(improvements),
      "improvement_percent_sample_stddev": _sample_stddev(improvements),
      "improvement_percent_min": min(improvements),
      "improvement_percent_max": max(improvements),
      "decision_diagnostics_available": len(diagnostics) == len(qmap_rows),
      "victim_sequence_unique_count": len(fingerprints),
      "lru_victim_disagreement_rate_mean": _mean([
          item.get("lru_victim_disagreement_rate", 0.0)
          for item in diagnostics]),
      "lru_in_retained_candidates_rate_mean": _mean([
          item.get("lru_in_retained_candidates_rate", 0.0)
          for item in diagnostics]),
      "score_margin_mean": _mean([
          item.get("top1_top2_score_margin", {}).get("mean", 0.0)
          for item in diagnostics]),
      "bounded_next_use_advantage_mean": _mean([
          item.get("bounded_next_use_distance_advantage", {}).get(
              "mean", 0.0)
          for item in diagnostics]),
      "disagreement_qmap_better_total": outcome_totals["qmap_better"],
      "disagreement_qmap_worse_total": outcome_totals["qmap_worse"],
      "disagreement_equal_total": outcome_totals["equal"],
      "test_used_for_selection": False,
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
  }
  for key, value in row.items():
    if isinstance(value, float) and not math.isfinite(value):
      raise ValueError("Bridge summary is non-finite: {}".format(key))
  return row


def attribution_rows(case_rows):
  by_id = {row["case_id"]: row for row in case_rows}
  rows = []
  for spec in bridge_variants.ATTRIBUTION_CHAIN:
    left = by_id.get(spec["left"])
    right = by_id.get(spec["right"])
    if left is None or right is None:
      raise ValueError("Bridge attribution chain is incomplete.")
    delta = (
        float(right["improvement_percent_mean"]) -
        float(left["improvement_percent_mean"]))
    rows.append({
        "factor": spec["factor"],
        "left_case": spec["left"],
        "right_case": spec["right"],
        "left_improvement_percent":
            float(left["improvement_percent_mean"]),
        "right_improvement_percent":
            float(right["improvement_percent_mean"]),
        "improvement_percentage_point_delta": delta,
        "absolute_effect_class": (
            "large" if abs(delta) >= 5.0 else
            "moderate" if abs(delta) >= 1.0 else "small"),
        "direction": (
            "improves_right_case" if delta > 0.0 else
            "degrades_right_case" if delta < 0.0 else "no_change"),
        "causal_scope": "matched_bridge_contrast_only",
    })
  return rows


def legacy_baseline_drift(imported_rows, current_rows):
  imported = _policy_means(imported_rows)
  current = _policy_means(current_rows)
  rows = []
  for policy in bridge_variants.CLASSIC_POLICIES:
    if policy not in imported or policy not in current:
      raise ValueError(
          "Legacy baseline drift check lacks policy {}.".format(policy))
    old = float(imported[policy])
    new = float(current[policy])
    rows.append({
        "policy": policy,
        "legacy_imported_cost": old,
        "current_engine_cost": new,
        "absolute_delta": new - old,
        "relative_delta_percent": (
            (new - old) * 100.0 / old if old else 0.0),
        "exact_match": new == old,
    })
  return rows


def build_summary(case_rows, imported_legacy_baselines,
                  current_legacy_baselines):
  return {
      "schema_version": "capd_bridge_summary_1",
      "status": "BRIDGE_DIAGNOSTIC_COMPLETED",
      "scientific_role": "post_hoc_diagnostic_not_method_selection",
      "test_used_for_selection": False,
      "official_stage6_replaced": False,
      "case_count": len(case_rows),
      "cases": list(case_rows),
      "attribution": attribution_rows(case_rows),
      "legacy_baseline_drift": legacy_baseline_drift(
          imported_legacy_baselines, current_legacy_baselines),
  }

