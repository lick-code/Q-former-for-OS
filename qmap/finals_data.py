# coding=utf-8
"""Auditable source manifests and deterministic data audits for CAPD stage 2.

This module is intentionally standard-library only.  The command-line wrappers
under ``scripts/`` are thin entry points so the same logic can be unit-tested
without scattering data gates across shell scripts.
"""

from __future__ import print_function

import bisect
import collections
import copy
import csv
import hashlib
import json
import math
import os


DATA_MANIFEST_SCHEMA = "capd_finals_v3_data_manifest_1"
SOURCE_SPEC_SCHEMA = "capd_finals_v3_source_spec_1"
AUDIT_SCHEMA = "capd_finals_v3_data_audit_1"
ARTIFACT_SCHEMA = "capd_finals_v3_0"
CONTRACT_ID = "CAPD-MIC-1.0"
REQUIRED_SPLITS = ("train", "valid", "test")
READ_VALUES = ("0", "r", "read", "load", "l")
WRITE_VALUES = ("1", "w", "write", "store", "s")


def canonical_json_bytes(value):
  return json.dumps(
      value, sort_keys=True, separators=(",", ":"),
      ensure_ascii=False).encode("utf-8")


def fingerprint_value(value):
  return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def fingerprint_file(path, chunk_size=1024 * 1024):
  digest = hashlib.sha256()
  with open(path, "rb") as input_file:
    while True:
      chunk = input_file.read(chunk_size)
      if not chunk:
        break
      digest.update(chunk)
  return digest.hexdigest()


def load_json(path):
  with open(path, "r", encoding="utf-8") as input_file:
    return json.load(input_file)


def write_json(path, value):
  directory = os.path.dirname(os.path.abspath(path))
  if directory:
    os.makedirs(directory, exist_ok=True)
  with open(path, "w", encoding="utf-8") as output_file:
    json.dump(value, output_file, indent=2, sort_keys=True,
              ensure_ascii=False)
    output_file.write("\n")


def resolve_path(path, repo_root):
  if not path:
    raise ValueError("A non-empty path is required.")
  if os.path.isabs(path):
    return os.path.normpath(path)
  return os.path.normpath(os.path.join(repo_root, path))


def portable_path(path, repo_root):
  absolute = os.path.abspath(path)
  root = os.path.abspath(repo_root)
  try:
    common = os.path.commonpath([absolute, root])
  except ValueError:
    common = ""
  if common == root:
    return os.path.relpath(absolute, root).replace(os.sep, "/")
  return absolute


def parse_int(value):
  return int(str(value).strip(), 0)


def parse_rw(value):
  normalized = str(value).strip().lower()
  if normalized in READ_VALUES:
    return 0
  if normalized in WRITE_VALUES:
    return 1
  raise ValueError("Unsupported RW value: {}".format(value))


def _header_indices(row, require_real_rw):
  normalized = [column.strip().lower() for column in row]
  indices = {"pc": None, "address": None, "rw": None}
  for index, name in enumerate(normalized):
    if name == "pc":
      indices["pc"] = index
    elif name in ("address", "addr"):
      indices["address"] = index
    elif name == "rw":
      indices["rw"] = index
  missing = [name for name in ("pc", "address")
             if indices[name] is None]
  if require_real_rw and indices["rw"] is None:
    missing.append("rw")
  if missing:
    raise ValueError(
        "Trace header is missing required column(s): {}.".format(
            ", ".join(missing)))
  return indices


def iter_trace_records(path, page_shift, require_real_rw=True):
  """Yields normalized records while rejecting simulated official RW."""
  with open(path, "r", newline="", encoding="utf-8") as input_file:
    reader = csv.reader(input_file)
    header = None
    for row_number, row in enumerate(reader, start=1):
      if not row:
        continue
      if header is None:
        normalized = {column.strip().lower() for column in row}
        if normalized & {"pc", "address", "addr", "rw"}:
          header = _header_indices(row, require_real_rw)
          continue
        if require_real_rw:
          raise ValueError(
              "Official trace requires an explicit PC,Address,RW header: "
              "{}".format(path))
        if len(row) not in (2, 3):
          raise ValueError("Line {} must be pc,address[,rw].".format(
              row_number))
        header = {"pc": 0, "address": 1,
                  "rw": 2 if len(row) == 3 else None}

      required = max(header["pc"], header["address"])
      if header["rw"] is not None:
        required = max(required, header["rw"])
      if len(row) <= required:
        raise ValueError("Line {} is missing required columns.".format(
            row_number))
      pc = parse_int(row[header["pc"]])
      address = parse_int(row[header["address"]])
      if header["rw"] is None:
        if require_real_rw:
          raise ValueError("Official trace is missing a real RW field.")
        rw = address & 1
      else:
        rw = parse_rw(row[header["rw"]])
      yield {
          "pc": pc,
          "address": address,
          "page_id": address >> int(page_shift),
          "rw": rw,
      }


def _record_bytes(record):
  return "{},{},{}\n".format(
      record["pc"], record["address"], record["rw"]).encode("ascii")


def scan_trace(path, page_shift, require_real_rw=True, collect=False):
  record_digest = hashlib.sha256()
  access_count = 0
  records = [] if collect else None
  for record in iter_trace_records(path, page_shift, require_real_rw):
    record_digest.update(_record_bytes(record))
    access_count += 1
    if collect:
      records.append(record)
  return {
      "path": path,
      "file_size_bytes": os.path.getsize(path),
      "fingerprint_sha256": fingerprint_file(path),
      "record_fingerprint_sha256": record_digest.hexdigest(),
      "access_count": access_count,
      "records": records,
  }


def scan_trace_ranges(path, page_shift, named_ranges, require_real_rw=True):
  full_digest = hashlib.sha256()
  digests = {name: hashlib.sha256() for name in named_ranges}
  counts = {name: 0 for name in named_ranges}
  access_count = 0
  for index, record in enumerate(iter_trace_records(
      path, page_shift, require_real_rw)):
    encoded = _record_bytes(record)
    full_digest.update(encoded)
    for name, interval in named_ranges.items():
      if (int(interval["start_inclusive"]) <= index <
          int(interval["end_exclusive"])):
        digests[name].update(encoded)
        counts[name] += 1
    access_count += 1
  return {
      "file_size_bytes": os.path.getsize(path),
      "fingerprint_sha256": fingerprint_file(path),
      "record_fingerprint_sha256": full_digest.hexdigest(),
      "access_count": access_count,
      "ranges": {
          name: {
              "record_fingerprint_sha256": digests[name].hexdigest(),
              "access_count": counts[name],
          } for name in named_ranges
      },
  }


def materialize_source_intervals(source_path, output_paths, intervals,
                                 page_shift):
  """Writes exact, non-overlapping source slices with a mandatory real RW."""
  split_contract = {
      split: {
          "collection_id": "materialization-source",
          "source_access_interval": {
              "start_inclusive": int(intervals[split][0]),
              "end_exclusive": int(intervals[split][1]),
          },
      } for split in REQUIRED_SPLITS
  }
  assert_source_intervals_independent(split_contract)
  for split in REQUIRED_SPLITS:
    if split not in output_paths:
      raise ValueError("Missing output path for {}.".format(split))
  normalized_source = os.path.normcase(os.path.abspath(source_path))
  normalized_outputs = [
      os.path.normcase(os.path.abspath(output_paths[split]))
      for split in REQUIRED_SPLITS]
  if (normalized_source in normalized_outputs or
      len(set(normalized_outputs)) != len(REQUIRED_SPLITS)):
    raise ValueError("Source and split output paths must all be distinct.")
  handles = {}
  writers = {}
  counts = {split: 0 for split in REQUIRED_SPLITS}
  try:
    for split in REQUIRED_SPLITS:
      path = output_paths[split]
      directory = os.path.dirname(os.path.abspath(path))
      if directory:
        os.makedirs(directory, exist_ok=True)
      handles[split] = open(path, "w", newline="", encoding="utf-8")
      writers[split] = csv.writer(handles[split])
      writers[split].writerow(("PC", "Address", "RW"))
    access_count = 0
    for index, record in enumerate(iter_trace_records(
        source_path, page_shift, require_real_rw=True)):
      for split in REQUIRED_SPLITS:
        interval = split_contract[split]["source_access_interval"]
        if (interval["start_inclusive"] <= index <
            interval["end_exclusive"]):
          writers[split].writerow((
              hex(record["pc"]), hex(record["address"]),
              "W" if record["rw"] else "R"))
          counts[split] += 1
      access_count += 1
  finally:
    for handle in handles.values():
      handle.close()
  for split in REQUIRED_SPLITS:
    interval = split_contract[split]["source_access_interval"]
    expected = interval["end_exclusive"] - interval["start_inclusive"]
    if interval["end_exclusive"] > access_count or counts[split] != expected:
      raise ValueError("Source trace is too short for {} interval.".format(
          split))
  return {
      "source_access_count": access_count,
      "split_access_counts": counts,
      "independence_evidence": assert_source_intervals_independent(
          split_contract),
  }


def _require(mapping, keys, context):
  missing = [key for key in keys if key not in mapping]
  if missing:
    raise ValueError("{} missing fields: {}".format(context, missing))


def _collection_map(spec_or_manifest):
  collections_value = spec_or_manifest.get("collections", [])
  if isinstance(collections_value, dict):
    values = []
    for collection_id, value in collections_value.items():
      item = copy.deepcopy(value)
      item.setdefault("collection_id", collection_id)
      values.append(item)
  else:
    values = list(collections_value)
  result = {}
  for value in values:
    collection_id = value.get("collection_id")
    if not collection_id or collection_id in result:
      raise ValueError("Collection IDs must be non-empty and unique.")
    result[collection_id] = value
  if not result:
    raise ValueError("At least one collection is required.")
  return result


def assert_source_intervals_independent(splits):
  """Proves record independence by collection identity and source intervals."""
  if set(splits) != set(REQUIRED_SPLITS):
    raise ValueError(
        "Official data must contain exactly train/valid/test splits.")
  evidence = []
  for split_name in REQUIRED_SPLITS:
    if split_name not in splits:
      raise ValueError("Missing split: {}".format(split_name))
    split = splits[split_name]
    _require(split, ("collection_id", "source_access_interval"),
             "split {}".format(split_name))
    interval = split["source_access_interval"]
    _require(interval, ("start_inclusive", "end_exclusive"),
             "split {} source interval".format(split_name))
    start = int(interval["start_inclusive"])
    end = int(interval["end_exclusive"])
    if start < 0 or end <= start:
      raise ValueError("Invalid source interval for split {}.".format(
          split_name))
  for left_index, left_name in enumerate(REQUIRED_SPLITS):
    left = splits[left_name]
    left_interval = left["source_access_interval"]
    for right_name in REQUIRED_SPLITS[left_index + 1:]:
      right = splits[right_name]
      right_interval = right["source_access_interval"]
      if left["collection_id"] != right["collection_id"]:
        evidence.append({
            "left": left_name,
            "right": right_name,
            "proof": "distinct_collection_id",
            "left_collection_id": left["collection_id"],
            "right_collection_id": right["collection_id"],
        })
        continue
      left_start = int(left_interval["start_inclusive"])
      left_end = int(left_interval["end_exclusive"])
      right_start = int(right_interval["start_inclusive"])
      right_end = int(right_interval["end_exclusive"])
      if max(left_start, right_start) < min(left_end, right_end):
        raise ValueError(
            "Source intervals overlap for {} and {} in collection {}.".format(
                left_name, right_name, left["collection_id"]))
      evidence.append({
          "left": left_name,
          "right": right_name,
          "proof": "non_overlapping_half_open_intervals",
          "collection_id": left["collection_id"],
          "left_interval": copy.deepcopy(left_interval),
          "right_interval": copy.deepcopy(right_interval),
      })
  return evidence


def build_source_manifest(spec, repo_root, git_commit):
  """Builds a manifest and verifies every split against its source slice."""
  _require(spec, ("schema_version", "workload_id", "page_shift",
                  "rw_source", "split_strategy", "collections", "splits"),
           "source spec")
  if spec["schema_version"] != SOURCE_SPEC_SCHEMA:
    raise ValueError("Unsupported source spec schema.")
  if spec.get("contract_id", CONTRACT_ID) != CONTRACT_ID:
    raise ValueError("Source spec contract mismatch.")
  if not git_commit or not spec.get("split_strategy"):
    raise ValueError("Source spec requires commit and split strategy.")
  if int(spec["page_shift"]) < 0:
    raise ValueError("Source spec page_shift must be non-negative.")
  rw_source = spec["rw_source"]
  if (rw_source.get("kind") != "trace_column" or
      str(rw_source.get("column", "")).lower() != "rw" or
      rw_source.get("verified_real") is not True):
    raise ValueError("Official source spec must verify a real RW trace column.")
  collections_by_id = _collection_map(spec)
  splits = copy.deepcopy(spec["splits"])
  independence = assert_source_intervals_independent(splits)
  referenced_collections = {
      splits[split]["collection_id"] for split in REQUIRED_SPLITS}
  if referenced_collections != set(collections_by_id):
    raise ValueError(
        "Official source spec contains a missing or unused collection.")

  collection_ranges = {collection_id: {} for collection_id in collections_by_id}
  for split_name, split in splits.items():
    collection_id = split["collection_id"]
    if collection_id not in collections_by_id:
      raise ValueError("Split {} references an unknown collection.".format(
          split_name))
    collection_ranges[collection_id][split_name] = copy.deepcopy(
        split["source_access_interval"])

  manifest_collections = []
  source_scans = {}
  source_paths_seen = set()
  page_shift = int(spec["page_shift"])
  for collection_id in sorted(collections_by_id):
    collection = collections_by_id[collection_id]
    _require(collection, ("source_trace", "tool", "command"),
             "collection {}".format(collection_id))
    if not collection.get("collected_at") and not collection.get(
        "source_label"):
      raise ValueError(
          "Collection {} needs collected_at or source_label.".format(
              collection_id))
    if collection.get("provenance_complete") is not True:
      raise ValueError("Official collection provenance is incomplete: {}".format(
          collection_id))
    source_path = resolve_path(collection["source_trace"], repo_root)
    normalized_source_path = os.path.normcase(os.path.abspath(source_path))
    if normalized_source_path in source_paths_seen:
      raise ValueError(
          "Distinct collection IDs cannot reuse the same source trace path.")
    source_paths_seen.add(normalized_source_path)
    source_scan = scan_trace_ranges(
        source_path, page_shift, collection_ranges[collection_id],
        require_real_rw=True)
    source_scans[collection_id] = source_scan
    manifest_collections.append({
        "collection_id": collection_id,
        "tool": collection["tool"],
        "command": collection["command"],
        "collected_at": collection.get("collected_at"),
        "source_label": collection.get("source_label"),
        "environment": collection.get("environment"),
        "provenance_complete": True,
        "source_trace": {
            "path": portable_path(source_path, repo_root),
            "fingerprint_sha256": source_scan["fingerprint_sha256"],
            "record_fingerprint_sha256": source_scan[
                "record_fingerprint_sha256"],
            "file_size_bytes": source_scan["file_size_bytes"],
            "access_count": source_scan["access_count"],
        },
    })

  manifest_splits = {}
  for split_name in REQUIRED_SPLITS:
    split = splits[split_name]
    split_path = resolve_path(split["path"], repo_root)
    split_scan = scan_trace(
        split_path, page_shift, require_real_rw=True, collect=False)
    interval = split["source_access_interval"]
    expected_count = (int(interval["end_exclusive"]) -
                      int(interval["start_inclusive"]))
    source_scan = source_scans[split["collection_id"]]
    if int(interval["end_exclusive"]) > source_scan["access_count"]:
      raise ValueError("Split {} interval exceeds its source trace.".format(
          split_name))
    interval_scan = source_scan["ranges"][split_name]
    if split_scan["access_count"] != expected_count:
      raise ValueError("Split {} count does not match its source interval.".format(
          split_name))
    if (split_scan["record_fingerprint_sha256"] !=
        interval_scan["record_fingerprint_sha256"]):
      raise ValueError(
          "Split {} content does not match the declared source interval.".format(
              split_name))
    manifest_splits[split_name] = {
        "path": portable_path(split_path, repo_root),
        "collection_id": split["collection_id"],
        "source_access_interval": copy.deepcopy(interval),
        "access_count": split_scan["access_count"],
        "file_size_bytes": split_scan["file_size_bytes"],
        "fingerprint_sha256": split_scan["fingerprint_sha256"],
        "record_fingerprint_sha256": split_scan[
            "record_fingerprint_sha256"],
    }

  manifest = {
      "schema_version": DATA_MANIFEST_SCHEMA,
      "artifact_schema": ARTIFACT_SCHEMA,
      "contract_id": CONTRACT_ID,
      "run_profile": "official",
      "artifact_class": "official",
      "workload_id": spec["workload_id"],
      "page_shift": page_shift,
      "rw_source": copy.deepcopy(rw_source),
      "split_strategy": spec["split_strategy"],
      "collections": manifest_collections,
      "splits": manifest_splits,
      "source_independence": {
          "basis": "collection_identity_and_half_open_source_intervals",
          "evidence": independence,
      },
      "git_commit": git_commit,
      "quality_gate": {
          "status": "PENDING",
          "profile_id": None,
          "profile_fingerprint": None,
          "report_path": None,
          "report_fingerprint_sha256": None,
      },
  }
  manifest["content_fingerprint"] = fingerprint_value(manifest)
  return manifest


def _manifest_payload(manifest):
  payload = copy.deepcopy(manifest)
  payload.pop("content_fingerprint", None)
  return payload


def manifest_source_identity(manifest):
  """Fingerprints immutable provenance without the mutable quality seal."""
  payload = _manifest_payload(manifest)
  payload.pop("quality_gate", None)
  return fingerprint_value(payload)


def validate_data_profile(profile, config):
  _require(profile, (
      "profile_id", "artifact_schema", "contract_id", "method_constants",
      "split_thresholds", "distribution_thresholds", "drift_thresholds",
      "drift_action"), "data quality profile")
  if profile["artifact_schema"] != ARTIFACT_SCHEMA:
    raise ValueError("Data quality profile schema mismatch.")
  if profile["contract_id"] != CONTRACT_ID:
    raise ValueError("Data quality profile contract mismatch.")
  if not profile["profile_id"]:
    raise ValueError("Data quality profile ID must be non-empty.")
  expected = {
      "D": int(config["memory"]["dram_capacity_pages"]),
      "K": int(config["candidate"]["retained_K"]),
      "H": int(config["history"]["transformer_H"]),
      "Hc": int(config["candidate"]["selector_history_Hc"]),
      "L": int(config["labels"]["future_lookahead_L"]),
      "pool_sizes_B": sorted(int(value) for value in
                             config["sweep"]["pool_sizes_B"]),
  }
  actual = copy.deepcopy(profile["method_constants"])
  actual["pool_sizes_B"] = sorted(
      int(value) for value in actual.get("pool_sizes_B", []))
  for key, value in expected.items():
    if actual.get(key) != value:
      raise ValueError(
          "Data quality profile method constant mismatch: {}.".format(key))
  for split in REQUIRED_SPLITS:
    if split not in profile["split_thresholds"]:
      raise ValueError("Data quality profile lacks {} thresholds.".format(
          split))
    required_thresholds = ["min_accesses", "min_victim_decisions"]
    if split in ("train", "valid"):
      required_thresholds.extend([
          "min_complete_window_decisions",
          "min_effective_label_decisions"])
    for key in required_thresholds:
      if (key not in profile["split_thresholds"][split] or
          int(profile["split_thresholds"][split][key]) < 0):
        raise ValueError(
            "Invalid {}.{} threshold.".format(split, key))
  distribution_keys = (
      "max_nondiscriminative_ratio", "min_reuse_event_ratio",
      "max_top_1_percent_page_share", "extreme_write_ratio_low",
      "extreme_write_ratio_high")
  for key in distribution_keys:
    value = float(profile["distribution_thresholds"].get(key, -1.0))
    if value < 0.0 or value > 1.0:
      raise ValueError("Invalid distribution threshold: {}.".format(key))
  if (float(profile["distribution_thresholds"]["extreme_write_ratio_low"]) >=
      float(profile["distribution_thresholds"]["extreme_write_ratio_high"])):
    raise ValueError("Extreme write-ratio thresholds are not ordered.")
  for key, value in profile["drift_thresholds"].items():
    if not key.startswith("max_") or float(value) < 0.0:
      raise ValueError("Invalid drift threshold: {}.".format(key))
  if profile["drift_action"] not in ("warning", "reject"):
    raise ValueError("Data quality profile drift_action is unsupported.")
  return {
      "profile_id": profile["profile_id"],
      "profile_fingerprint": fingerprint_value(profile),
  }


def validate_source_manifest(manifest, repo_root, verify_files=True,
                             require_quality_pass=False,
                             expected_workload=None):
  _require(manifest, (
      "schema_version", "artifact_schema", "contract_id", "run_profile",
      "artifact_class", "workload_id", "page_shift", "rw_source",
      "split_strategy", "collections", "splits", "source_independence",
      "git_commit", "quality_gate", "content_fingerprint"),
           "source manifest")
  if manifest["schema_version"] != DATA_MANIFEST_SCHEMA:
    raise ValueError("Unsupported data manifest schema.")
  if manifest["artifact_schema"] != ARTIFACT_SCHEMA:
    raise ValueError("Data manifest is not a v3 official artifact.")
  if manifest["contract_id"] != CONTRACT_ID:
    raise ValueError("Data manifest contract mismatch.")
  if not manifest.get("git_commit") or not manifest.get("split_strategy"):
    raise ValueError("Data manifest requires commit and split strategy.")
  if int(manifest["page_shift"]) < 0:
    raise ValueError("Data manifest page_shift must be non-negative.")
  if (manifest["run_profile"] != "official" or
      manifest["artifact_class"] != "official"):
    raise ValueError("Data manifest must be official.")
  if expected_workload and manifest["workload_id"] != expected_workload:
    raise ValueError("Data manifest workload mismatch.")
  if manifest["content_fingerprint"] != fingerprint_value(
      _manifest_payload(manifest)):
    raise ValueError("Data manifest content fingerprint mismatch.")
  rw_source = manifest["rw_source"]
  if (rw_source.get("kind") != "trace_column" or
      str(rw_source.get("column", "")).lower() != "rw" or
      rw_source.get("verified_real") is not True):
    raise ValueError("Official data manifest lacks verified real RW evidence.")
  collections_by_id = _collection_map(manifest)
  referenced_collections = {
      manifest["splits"][split]["collection_id"]
      for split in REQUIRED_SPLITS}
  if referenced_collections != set(collections_by_id):
    raise ValueError(
        "Data manifest contains missing or unused collections.")
  normalized_source_paths = []
  for collection_id, collection in collections_by_id.items():
    _require(collection, (
        "tool", "command", "source_trace", "provenance_complete"),
             "collection {}".format(collection_id))
    if (not collection["tool"] or not collection["command"] or
        collection["provenance_complete"] is not True or
        (not collection.get("collected_at") and
         not collection.get("source_label"))):
      raise ValueError(
          "Collection provenance is incomplete: {}.".format(collection_id))
    normalized_source_paths.append(os.path.normcase(resolve_path(
        collection["source_trace"]["path"], repo_root)))
  if len(normalized_source_paths) != len(set(normalized_source_paths)):
    raise ValueError(
        "Distinct collection IDs cannot reuse the same source trace path.")
  independence = assert_source_intervals_independent(manifest["splits"])
  if (manifest["source_independence"].get("basis") !=
      "collection_identity_and_half_open_source_intervals"):
    raise ValueError("Data manifest independence basis mismatch.")
  if manifest["source_independence"].get("evidence") != independence:
    raise ValueError("Data manifest independence evidence is stale.")
  quality = manifest["quality_gate"]
  _require(quality, (
      "status", "profile_id", "profile_fingerprint", "report_path",
      "report_fingerprint_sha256"), "data quality gate")
  if quality["status"] not in (
      "PENDING", "PASSED", "INSUFFICIENT", "REJECTED"):
    raise ValueError("Unsupported data quality gate status.")
  if require_quality_pass:
    if quality.get("status") != "PASSED":
      raise ValueError("Data quality gate has not passed.")
    report_path = resolve_path(quality["report_path"], repo_root)
    if fingerprint_file(report_path) != quality["report_fingerprint_sha256"]:
      raise ValueError("Data quality report fingerprint mismatch.")
    report = load_json(report_path)
    recorded_audit = report.get("audit_fingerprint")
    audit_payload = copy.deepcopy(report)
    audit_payload.pop("audit_fingerprint", None)
    if recorded_audit != fingerprint_value(audit_payload):
      raise ValueError("Data quality report content fingerprint mismatch.")
    if (report.get("status") != "PASSED" or
        report.get("workload_id") != manifest["workload_id"] or
        report.get("profile_id") != quality["profile_id"] or
        report.get("profile_fingerprint") != quality["profile_fingerprint"] or
        report.get("source_manifest_fingerprint") !=
        manifest_source_identity(manifest)):
      raise ValueError("Data quality report/manifest binding mismatch.")

  if verify_files:
    ranges = {collection_id: {} for collection_id in collections_by_id}
    for split_name in REQUIRED_SPLITS:
      split = manifest["splits"][split_name]
      if split["collection_id"] not in collections_by_id:
        raise ValueError("Split references an unknown collection.")
      ranges[split["collection_id"]][split_name] = split[
          "source_access_interval"]
    source_scans = {}
    for collection_id, collection in collections_by_id.items():
      source = collection.get("source_trace", {})
      _require(source, (
          "path", "fingerprint_sha256", "record_fingerprint_sha256",
          "file_size_bytes", "access_count"),
               "collection source {}".format(collection_id))
      path = resolve_path(source["path"], repo_root)
      scan = scan_trace_ranges(
          path, int(manifest["page_shift"]), ranges[collection_id],
          require_real_rw=True)
      source_scans[collection_id] = scan
      for key in ("fingerprint_sha256", "record_fingerprint_sha256",
                  "file_size_bytes", "access_count"):
        if scan[key] != source[key]:
          raise ValueError(
              "Collection {} source {} mismatch.".format(collection_id, key))
    for split_name in REQUIRED_SPLITS:
      split = manifest["splits"][split_name]
      _require(split, (
          "path", "collection_id", "source_access_interval", "access_count",
          "file_size_bytes", "fingerprint_sha256",
          "record_fingerprint_sha256"), "split {}".format(split_name))
      path = resolve_path(split["path"], repo_root)
      scan = scan_trace(
          path, int(manifest["page_shift"]), require_real_rw=True)
      for key in ("fingerprint_sha256", "record_fingerprint_sha256",
                  "file_size_bytes", "access_count"):
        if scan[key] != split[key]:
          raise ValueError("Split {} {} mismatch.".format(split_name, key))
      interval_scan = source_scans[split["collection_id"]]["ranges"][
          split_name]
      interval = split["source_access_interval"]
      expected_count = (int(interval["end_exclusive"]) -
                        int(interval["start_inclusive"]))
      if (int(interval["end_exclusive"]) >
          source_scans[split["collection_id"]]["access_count"] or
          interval_scan["access_count"] != expected_count or
          scan["access_count"] != expected_count):
        raise ValueError("Split {} source interval count mismatch.".format(
            split_name))
      if (interval_scan["record_fingerprint_sha256"] !=
          split["record_fingerprint_sha256"]):
        raise ValueError("Split {} no longer matches its source interval.".format(
            split_name))
  return {
      "workload_id": manifest["workload_id"],
      "source_independence_evidence": independence,
      "split_fingerprints": {
          split: manifest["splits"][split]["fingerprint_sha256"]
          for split in REQUIRED_SPLITS
      },
  }


def load_source_manifest(path, repo_root, verify_files=True,
                         require_quality_pass=False,
                         expected_workload=None):
  manifest = load_json(resolve_path(path, repo_root))
  validate_source_manifest(
      manifest, repo_root, verify_files=verify_files,
      require_quality_pass=require_quality_pass,
      expected_workload=expected_workload)
  return manifest


def manifest_binding(path, manifest, repo_root):
  quality = manifest.get("quality_gate", {})
  return {
      "source_manifest": portable_path(resolve_path(path, repo_root), repo_root),
      "source_manifest_fingerprint": fingerprint_file(
          resolve_path(path, repo_root)),
      "split_fingerprints": {
          split: manifest["splits"][split]["fingerprint_sha256"]
          for split in REQUIRED_SPLITS
      },
      "data_quality_profile_id": quality.get("profile_id"),
      "data_quality_profile_fingerprint": quality.get(
          "profile_fingerprint"),
      "data_quality_report_fingerprint": quality.get(
          "report_fingerprint_sha256"),
  }


def validate_artifact_binding(binding, artifact, context):
  if artifact.get("schema_version") != ARTIFACT_SCHEMA:
    raise ValueError("{} rejects non-v3 artifacts.".format(context))
  required = (
      "source_manifest_fingerprint", "split_fingerprints",
      "data_quality_profile_id", "data_quality_profile_fingerprint",
      "data_quality_report_fingerprint")
  missing_binding = [key for key in required if key not in binding]
  if missing_binding:
    raise ValueError("{} expected binding is incomplete: {}".format(
        context, missing_binding))
  missing = [key for key in required if key not in artifact]
  if missing:
    raise ValueError("{} missing data binding: {}".format(context, missing))
  mismatches = {
      key: (binding[key], artifact.get(key)) for key in required
      if artifact.get(key) != binding[key]
  }
  if mismatches:
    raise ValueError("{} data binding mismatch: {}".format(
        context, mismatches))
  return artifact


def quantile(values, probability):
  if not values:
    return None
  ordered = sorted(float(value) for value in values)
  if len(ordered) == 1:
    return ordered[0]
  position = (len(ordered) - 1) * float(probability)
  lower = int(math.floor(position))
  upper = int(math.ceil(position))
  if lower == upper:
    return ordered[lower]
  fraction = position - lower
  return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values):
  return {
      "min": min(values) if values else None,
      "p25": quantile(values, 0.25),
      "p50": quantile(values, 0.50),
      "p75": quantile(values, 0.75),
      "p90": quantile(values, 0.90),
      "p95": quantile(values, 0.95),
      "p99": quantile(values, 0.99),
      "max": max(values) if values else None,
      "mean": (sum(values) / float(len(values))) if values else None,
  }


def _future_relevance(page, index, lookahead, positions, write_positions):
  page_positions = positions.get(page, [])
  start = bisect.bisect_right(page_positions, index)
  end = bisect.bisect_left(page_positions, index + lookahead + 1, lo=start)
  frequency = end - start
  next_distance = (page_positions[start] - index
                   if start < end else None)
  writes = write_positions.get(page, [])
  write_start = bisect.bisect_right(writes, index)
  write_end = bisect.bisect_left(
      writes, index + lookahead + 1, lo=write_start)
  write_frequency = write_end - write_start
  inactivity = (1.0 if next_distance is None else
                min(next_distance, lookahead) / float(lookahead))
  coldness = 1.0 - min(frequency / float(lookahead), 1.0)
  write_intensity = min(write_frequency / float(lookahead), 1.0)
  return inactivity + coldness - 4.0 * write_intensity


def replay_quality_metrics(pages, rws, dram_capacity, lookahead,
                           pool_sizes, retained_k, epsilon_y):
  positions = collections.defaultdict(list)
  write_positions = collections.defaultdict(list)
  for index, (page, rw) in enumerate(zip(pages, rws)):
    positions[page].append(index)
    if rw:
      write_positions[page].append(index)
  dram = collections.OrderedDict()
  hits = 0
  misses = 0
  decisions = 0
  complete_decisions = 0
  effective_decisions = 0
  first_fill = None
  relevance_ranges = []
  tie_sizes = []
  bt_values = {str(value): [] for value in pool_sizes}
  kt_values = []
  for index, page in enumerate(pages):
    if page in dram:
      hits += 1
      dram.move_to_end(page, last=True)
      continue
    misses += 1
    if len(dram) >= dram_capacity:
      decisions += 1
      dram_pages_oldest_first = list(dram.keys())
      for pool_size in pool_sizes:
        bt_values[str(pool_size)].append(min(
            int(pool_size), len(dram_pages_oldest_first)))
      kt_values.append(min(int(retained_k), len(dram_pages_oldest_first)))
      if index + lookahead < len(pages):
        complete_decisions += 1
        relevance = [
            _future_relevance(
                candidate, index, lookahead, positions, write_positions)
            for candidate in dram_pages_oldest_first
        ]
        relevance_range = max(relevance) - min(relevance)
        relevance_ranges.append(relevance_range)
        if relevance_range > epsilon_y:
          effective_decisions += 1
        maximum = max(relevance)
        tie_sizes.append(sum(
            1 for value in relevance
            if math.isclose(value, maximum, rel_tol=0.0, abs_tol=1e-12)))
      dram.popitem(last=False)
    dram[page] = None
    if first_fill is None and len(dram) == dram_capacity:
      first_fill = index
  access_count = len(pages)
  return {
      "dram_capacity_pages": dram_capacity,
      "lru_hits": hits,
      "lru_misses": misses,
      "miss_ratio": misses / float(access_count) if access_count else 0.0,
      "victim_decision_count": decisions,
      "decision_ratio": decisions / float(access_count) if access_count else 0.0,
      "first_dram_full_index": first_fill,
      "complete_future_window_decision_count": complete_decisions,
      "valid_label_decision_count": complete_decisions,
      "tail_dropped_decision_count": decisions - complete_decisions,
      "tail_dropped_ratio": (
          (decisions - complete_decisions) / float(decisions)
          if decisions else 0.0),
      "effective_relevance_decision_count": effective_decisions,
      "nondiscriminative_ratio": (
          (complete_decisions - effective_decisions) /
          float(complete_decisions) if complete_decisions else 1.0),
      "relevance_range_distribution": distribution(relevance_ranges),
      "tied_best_set_size_distribution": distribution(tie_sizes),
      "candidate_pool_B_t": {
          key: distribution(values) for key, values in bt_values.items()
      },
      "retained_K_t": distribution(kt_values),
  }


def analyze_trace(path, page_shift, constants):
  scan = scan_trace(
      path, page_shift, require_real_rw=True, collect=True)
  records = scan.pop("records")
  pages = [record["page_id"] for record in records]
  pcs = [record["pc"] for record in records]
  rws = [record["rw"] for record in records]
  page_counts = collections.Counter(pages)
  pc_counts = collections.Counter(pcs)
  page_write_counts = collections.Counter(
      page for page, rw in zip(pages, rws) if rw)
  last_seen = {}
  reuse_intervals = []
  for index, page in enumerate(pages):
    if page in last_seen:
      reuse_intervals.append(index - last_seen[page])
    last_seen[page] = index
  total = len(records)
  reads = total - sum(rws)
  writes = sum(rws)
  ordered_counts = sorted(page_counts.values(), reverse=True)

  def top_share(fraction):
    if not ordered_counts or not total:
      return 0.0
    count = max(1, int(math.ceil(len(ordered_counts) * fraction)))
    return sum(ordered_counts[:count]) / float(total)

  replay = replay_quality_metrics(
      pages, rws, int(constants["D"]), int(constants["L"]),
      [int(value) for value in constants["pool_sizes_B"]],
      int(constants["K"]), float(constants["epsilon_y"]))
  metrics = {
      "basic": {
          "access_count": total,
          "unique_page_count": len(page_counts),
          "unique_pc_count": len(pc_counts),
          "file_size_bytes": scan["file_size_bytes"],
          "fingerprint_sha256": scan["fingerprint_sha256"],
          "record_fingerprint_sha256": scan[
              "record_fingerprint_sha256"],
      },
      "read_write": {
          "read_count": reads,
          "read_ratio": reads / float(total) if total else 0.0,
          "write_count": writes,
          "write_ratio": writes / float(total) if total else 0.0,
          "rw_source": "real_trace_column",
          "per_page_write_count_distribution": distribution([
              page_write_counts.get(page, 0) for page in page_counts]),
      },
      "dram_pressure_and_labels": replay,
      "hotspot_and_tail": {
          "page_access_count_distribution": distribution(
              list(page_counts.values())),
          "top_1_percent_page_share": top_share(0.01),
          "top_5_percent_page_share": top_share(0.05),
          "top_10_percent_page_share": top_share(0.10),
          "single_access_page_ratio": (
              sum(1 for value in page_counts.values() if value == 1) /
              float(len(page_counts)) if page_counts else 0.0),
          "reuse_event_count": len(reuse_intervals),
          "reuse_event_ratio": (
              len(reuse_intervals) / float(total) if total else 0.0),
          "reuse_interval_distribution": distribution(reuse_intervals),
      },
  }
  return metrics, set(page_counts), set(pc_counts), pages, pcs


def oov_metrics(values, train_vocab):
  if not values:
    return {"access_oov_count": 0, "access_oov_ratio": 0.0,
            "unique_oov_count": 0, "unique_oov_ratio": 0.0}
  unique_values = set(values)
  access_oov = sum(1 for value in values if value not in train_vocab)
  unique_oov = len(unique_values - train_vocab)
  return {
      "access_oov_count": access_oov,
      "access_oov_ratio": access_oov / float(len(values)),
      "unique_oov_count": unique_oov,
      "unique_oov_ratio": unique_oov / float(len(unique_values)),
  }


def _profile_threshold(profile, split, key, default=None):
  return profile.get("split_thresholds", {}).get(split, {}).get(key, default)


def _diagnose_split(split_name, metrics, profile, constants):
  sufficiency = []
  warnings = []
  basic = metrics["basic"]
  pressure = metrics["dram_pressure_and_labels"]
  hotspot = metrics["hotspot_and_tail"]
  rw = metrics["read_write"]
  minimum_accesses = int(_profile_threshold(
      profile, split_name, "min_accesses", 0))
  minimum_decisions = int(_profile_threshold(
      profile, split_name, "min_victim_decisions", 1))
  if basic["access_count"] < minimum_accesses:
    sufficiency.append("access_count_below_profile_minimum")
  if basic["access_count"] < int(constants["D"]) + int(constants["L"]) + 1:
    sufficiency.append("trace_too_short_for_fill_and_complete_future_window")
  if basic["unique_page_count"] <= int(constants["D"]):
    sufficiency.append("unique_pages_not_greater_than_D")
  if pressure["victim_decision_count"] < minimum_decisions:
    sufficiency.append("victim_decisions_below_profile_minimum")
  if split_name in ("train", "valid"):
    minimum_complete = int(_profile_threshold(
        profile, split_name, "min_complete_window_decisions", 1))
    minimum_effective = int(_profile_threshold(
        profile, split_name, "min_effective_label_decisions", 1))
    if pressure["complete_future_window_decision_count"] < minimum_complete:
      sufficiency.append("complete_window_decisions_below_profile_minimum")
    if pressure["effective_relevance_decision_count"] < minimum_effective:
      sufficiency.append("effective_label_decisions_below_profile_minimum")
    maximum_nondiscriminative = float(profile.get(
        "distribution_thresholds", {}).get(
            "max_nondiscriminative_ratio", 1.0))
    if pressure["nondiscriminative_ratio"] > maximum_nondiscriminative:
      sufficiency.append("nondiscriminative_ratio_above_profile_maximum")
  distribution_thresholds = profile.get("distribution_thresholds", {})
  if hotspot["reuse_event_ratio"] < float(
      distribution_thresholds.get("min_reuse_event_ratio", 0.0)):
    warnings.append("near_streaming_or_no_reuse")
  if hotspot["top_1_percent_page_share"] > float(
      distribution_thresholds.get("max_top_1_percent_page_share", 1.0)):
    warnings.append("hotspot_overconcentrated")
  if (rw["write_ratio"] < float(
      distribution_thresholds.get("extreme_write_ratio_low", 0.0)) or
      rw["write_ratio"] > float(
          distribution_thresholds.get("extreme_write_ratio_high", 1.0))):
    warnings.append("extreme_write_ratio")
  metrics["diagnostics"] = {
      "sufficiency_failures": sorted(set(sufficiency)),
      "warnings": sorted(set(warnings)),
      "low_pressure": (
          basic["unique_page_count"] <= int(constants["D"]) or
          pressure["victim_decision_count"] < minimum_decisions),
      "fully_streaming_or_no_reuse": "near_streaming_or_no_reuse" in warnings,
      "extreme_write_ratio": "extreme_write_ratio" in warnings,
  }
  return sufficiency, warnings


def _drift_report(split_metrics, profile):
  write_values = [
      split_metrics[name]["read_write"]["write_ratio"]
      for name in REQUIRED_SPLITS]
  decision_values = [
      split_metrics[name]["dram_pressure_and_labels"]["decision_ratio"]
      for name in REQUIRED_SPLITS]
  hotspot_values = [
      split_metrics[name]["hotspot_and_tail"]["top_1_percent_page_share"]
      for name in REQUIRED_SPLITS]
  thresholds = profile.get("drift_thresholds", {})
  spans = {
      "write_ratio_span": max(write_values) - min(write_values),
      "decision_ratio_span": max(decision_values) - min(decision_values),
      "top_1_percent_page_share_span": max(hotspot_values) - min(hotspot_values),
  }
  warnings = []
  for metric, value in spans.items():
    maximum = thresholds.get("max_{}".format(metric))
    if maximum is not None and value > float(maximum):
      warnings.append("{}_above_profile_maximum".format(metric))
  return {"spans": spans, "warnings": warnings}


def audit_source_manifest(manifest_path, repo_root, config, profile):
  """Returns a deterministic report; it never claims server verification."""
  hard_failures = []
  try:
    manifest = load_source_manifest(
        manifest_path, repo_root, verify_files=True,
        require_quality_pass=False)
  except (OSError, ValueError) as error:
    manifest = None
    hard_failures.append(str(error))

  report = {
      "schema_version": AUDIT_SCHEMA,
      "artifact_schema": ARTIFACT_SCHEMA,
      "contract_id": CONTRACT_ID,
      "verification_status": "ANALYZED",
      "profile_id": profile["profile_id"],
      "profile_fingerprint": fingerprint_value(profile),
      "hard_failures": hard_failures,
      "sufficiency_failures": [],
      "warnings": [],
      "splits": {},
      "cross_split": {},
  }
  if manifest is None:
    report["status"] = "REJECTED"
    report["audit_fingerprint"] = fingerprint_value(report)
    return report

  workload_id = manifest["workload_id"]
  report.update({
      "workload_id": workload_id,
      "source_manifest": portable_path(
          resolve_path(manifest_path, repo_root), repo_root),
      "source_manifest_fingerprint": manifest_source_identity(manifest),
      "git_commit": manifest["git_commit"],
  })
  if config.get("schema_version") != ARTIFACT_SCHEMA:
    hard_failures.append("config_schema_is_not_capd_finals_v3_0")
  if config.get("contract", {}).get("id") != CONTRACT_ID:
    hard_failures.append("config_contract_id_mismatch")
  if workload_id not in config.get("workloads", {}):
    hard_failures.append("workload_missing_from_v3_config")
  try:
    validate_data_profile(profile, config)
  except (KeyError, TypeError, ValueError) as error:
    hard_failures.append(str(error))
  configured_data = config.get("workloads", {}).get(workload_id, {})
  for split_name, config_key in (
      ("train", "train_trace"), ("valid", "valid_trace"),
      ("test", "test_trace")):
    configured_path = configured_data.get(config_key)
    if (not configured_path or os.path.normcase(resolve_path(
        configured_path, repo_root)) != os.path.normcase(resolve_path(
            manifest["splits"][split_name]["path"], repo_root))):
      hard_failures.append(
          "config_manifest_{}_path_mismatch".format(split_name))
  if int(manifest["page_shift"]) != int(config["trace"]["page_shift"]):
    hard_failures.append("config_manifest_page_shift_mismatch")
  constants = {
      "D": int(config["memory"]["dram_capacity_pages"]),
      "K": int(config["candidate"]["retained_K"]),
      "H": int(config["history"]["transformer_H"]),
      "Hc": int(config["candidate"]["selector_history_Hc"]),
      "L": int(config["labels"]["future_lookahead_L"]),
      "epsilon_y": float(config["selector"]["epsilon_y"]),
      "pool_sizes_B": list(config["sweep"]["pool_sizes_B"]),
  }
  report["method_constants"] = constants
  split_vocab = {}
  all_sufficiency = []
  all_warnings = []
  for split_name in REQUIRED_SPLITS:
    split_path = resolve_path(manifest["splits"][split_name]["path"], repo_root)
    metrics, pages, pcs, page_sequence, pc_sequence = analyze_trace(
        split_path, int(manifest["page_shift"]), constants)
    split_vocab[split_name] = {
        "pages": pages, "pcs": pcs,
        "page_sequence": page_sequence, "pc_sequence": pc_sequence,
    }
    sufficiency, warnings = _diagnose_split(
        split_name, metrics, profile, constants)
    report["splits"][split_name] = metrics
    all_sufficiency.extend(
        "{}:{}".format(split_name, value) for value in sufficiency)
    all_warnings.extend(
        "{}:{}".format(split_name, value) for value in warnings)

  train_pages = split_vocab["train"]["pages"]
  train_pcs = split_vocab["train"]["pcs"]
  oov = {}
  for split_name in ("valid", "test"):
    oov[split_name] = {
        "page": oov_metrics(
            split_vocab[split_name]["page_sequence"], train_pages),
        "pc": oov_metrics(
            split_vocab[split_name]["pc_sequence"], train_pcs),
    }
  page_capacity = int(config["embedding"]["page"]["max_vocab_size"])
  pc_capacity = int(config["embedding"]["pc"]["max_vocab_size"])
  vocabulary = {
      "train_page_vocab_size": len(train_pages),
      "train_pc_vocab_size": len(train_pcs),
      "page_vocab_capacity": page_capacity,
      "pc_vocab_capacity": pc_capacity,
      "train_page_vocab_exceeds_capacity": len(train_pages) > page_capacity,
      "train_pc_vocab_exceeds_capacity": len(train_pcs) > pc_capacity,
      "vocab_fit_policy": "train_only_valid_test_do_not_extend",
      "oov": oov,
  }
  if vocabulary["train_page_vocab_exceeds_capacity"]:
    all_sufficiency.append("train:page_vocab_exceeds_capacity")
  if vocabulary["train_pc_vocab_exceeds_capacity"]:
    all_sufficiency.append("train:pc_vocab_exceeds_capacity")
  report["cross_split"] = {
      "source_independence": copy.deepcopy(
          manifest["source_independence"]),
      "vocabulary_risk": vocabulary,
      "distribution_drift": _drift_report(report["splits"], profile),
  }
  drift_diagnostics = [
      "drift:{}".format(value) for value in
      report["cross_split"]["distribution_drift"]["warnings"]]
  if profile.get("drift_action") == "reject":
    all_sufficiency.extend(drift_diagnostics)
  else:
    all_warnings.extend(drift_diagnostics)
  report["sufficiency_failures"] = sorted(set(all_sufficiency))
  report["warnings"] = sorted(set(all_warnings))
  if hard_failures:
    report["status"] = "REJECTED"
  elif all_sufficiency:
    report["status"] = "INSUFFICIENT"
  else:
    report["status"] = "PASSED"
  report["audit_fingerprint"] = fingerprint_value(report)
  return report


def update_manifest_quality_gate(manifest_path, report_path, repo_root,
                                 report):
  manifest_file = resolve_path(manifest_path, repo_root)
  report_file = resolve_path(report_path, repo_root)
  manifest = load_json(manifest_file)
  validate_source_manifest(
      manifest, repo_root, verify_files=True, require_quality_pass=False)
  report_payload = copy.deepcopy(report)
  recorded_audit = report_payload.pop("audit_fingerprint", None)
  if recorded_audit != fingerprint_value(report_payload):
    raise ValueError("Cannot seal a stale data quality report.")
  if (report.get("source_manifest_fingerprint") !=
      manifest_source_identity(manifest) or
      report.get("workload_id") != manifest.get("workload_id")):
    raise ValueError("Cannot seal a report for a different source manifest.")
  if load_json(report_file) != report:
    raise ValueError("Data quality report object/file mismatch.")
  manifest["quality_gate"] = {
      "status": report["status"],
      "profile_id": report["profile_id"],
      "profile_fingerprint": report["profile_fingerprint"],
      "report_path": portable_path(report_file, repo_root),
      "report_fingerprint_sha256": fingerprint_file(report_file),
  }
  manifest["content_fingerprint"] = fingerprint_value(
      _manifest_payload(manifest))
  write_json(manifest_file, manifest)
  return fingerprint_file(manifest_file)
