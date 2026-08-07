"""Stage10 v2-r2 source identity and metadata contract helpers."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_ID = "CAPD-PROACTIVE-STAGE10-2.0"
CONFIG_SCHEMA_VERSION = "capd_proactive_stage10_v2_1"
RUN_IDENTITY_SCHEMA_VERSION = "capd_proactive_stage10_run_identity_v2_1"
RUN_STATE_SCHEMA_VERSION = "capd_proactive_stage10_run_state_v2_1"
VERIFICATION_SCHEMA_VERSION = "capd_proactive_stage10_verification_v2_1"
MANIFEST_SCHEMA_VERSION = "capd_proactive_stage10_manifest_v2_1"
SOURCE_MANIFEST_SCHEMA = "capd_proactive_stage10_generation_source_manifest_v1_0"
FREEZE_RECEIPT_SCHEMA = "capd_proactive_stage10_generation_freeze_receipt_v1_0"
GENERATION_TEST_EVIDENCE_SCHEMA = "capd_proactive_stage10_generation_test_evidence_v1_0"
EXECUTION_ENVIRONMENT_SCHEMA = "capd_proactive_stage10_execution_environment_v1_0"
RELEASE_READINESS_SCHEMA = "capd_proactive_stage10_release_readiness_receipt_v1_0"
RELEASE_TEST_EVIDENCE_SCHEMA = "capd_proactive_stage10_release_test_evidence_v1_0"
STAGE11_AUDIT_EVIDENCE_SCHEMA = (
    "capd_proactive_stage10_stage11_negative_audit_evidence_v1_0")
FINAL_STATUS_EVIDENCE_SCHEMA = (
    "capd_proactive_stage10_final_status_evidence_receipt_v1_0")
RELEASE_MANIFEST_SCHEMA = "capd_proactive_stage10_release_manifest_v1_0"
SOURCE_SET_ID = "stage10-v2-r2-generation-core-v1"
EVIDENCE_MODE = "deterministic_async_simulation"
VERIFIED_STATUS = "stage10_async_simulation_verified"
FAILURE_STATUS = "stage10_async_simulation_not_verified"
RUN_ID = "stage10-async-simulator-v2-r2"

APPROVED_DESIGN_PATH = (
    "docs/superpowers/specs/"
    "2026-08-06-stage10-v2-r2-source-identity-migration-design.md")
APPROVED_DESIGN_SHA256 = (
    "e967307c7cc9c3548424c646ca2c442c01ef738da0995fbda9037044567f3cc2")
APPROVED_PLAN_PATH = (
    "docs/superpowers/plans/"
    "2026-08-06-stage10-v2-r2-source-identity-migration.md")
APPROVED_PLAN_SHA256 = (
    "3ed8f1760c1a9f93f06c1d6c9897485b2169be88844f63b0183bdca2351bee23")
SOURCE_MANIFEST_PATH = (
    "configs/finals/capd_proactive_stage10_v2_r2_source_manifest.json")
CONFIG_PATH = "configs/finals/capd_proactive_stage10_v2_r2.json"
FREEZE_RECEIPT_PATH = (
    "docs/superpowers/specs/2026-08-06-stage10-v2-r2-generation-freeze.json")
PROTOCOL_PATH = "docs/CAPD_PROACTIVE_STAGE10_V2_R2_PROTOCOL_CN.md"

CONTROLLED_EXECUTION = {
    "generation_core_test_timeout_seconds": 1800,
    "formal_simulation_timeout_seconds": 1800,
    "release_readiness_test_timeout_seconds": 600,
    "stage11_negative_audit_timeout_seconds": 600,
    "final_status_test_timeout_seconds": 600,
    "monitor_check_interval_seconds": 30,
    "termination_grace_seconds": 10,
    "automatic_retry_allowed": False,
}

ENVIRONMENT_FIELDS = (
    "python_version", "python_implementation", "python_cache_tag",
    "python_executable", "os_name", "platform_system", "platform_release",
    "platform_version", "machine", "architecture",
    "required_dependency_versions", "dependency_policy",
)

METADATA_SCHEMA_VERSIONS = {
    "capd_proactive_stage10_v2_r2_config_schema": CONFIG_SCHEMA_VERSION,
    "capd_proactive_stage10_generation_source_manifest_schema": SOURCE_MANIFEST_SCHEMA,
    "capd_proactive_stage10_generation_freeze_receipt_schema": FREEZE_RECEIPT_SCHEMA,
    "capd_proactive_stage10_generation_test_evidence_schema": GENERATION_TEST_EVIDENCE_SCHEMA,
    "capd_proactive_stage10_execution_environment_schema": EXECUTION_ENVIRONMENT_SCHEMA,
    "capd_proactive_stage10_run_identity_schema_v2_1": RUN_IDENTITY_SCHEMA_VERSION,
    "capd_proactive_stage10_run_state_schema_v2_1": RUN_STATE_SCHEMA_VERSION,
    "capd_proactive_stage10_verification_schema_v2_1": VERIFICATION_SCHEMA_VERSION,
    "capd_proactive_stage10_manifest_schema_v2_1": MANIFEST_SCHEMA_VERSION,
    "capd_proactive_stage10_release_test_evidence_schema": RELEASE_TEST_EVIDENCE_SCHEMA,
    "capd_proactive_stage10_release_readiness_receipt_schema": RELEASE_READINESS_SCHEMA,
    "capd_proactive_stage10_stage11_negative_audit_evidence_schema": STAGE11_AUDIT_EVIDENCE_SCHEMA,
    "capd_proactive_stage10_final_status_evidence_receipt_schema": FINAL_STATUS_EVIDENCE_SCHEMA,
    "capd_proactive_stage10_release_manifest_schema": RELEASE_MANIFEST_SCHEMA,
}

GENERATION_TEST_ARGV_SUFFIX = (
    "-m", "unittest", "-v",
    "tests.test_capd_proactive_stage10",
    "tests.test_capd_proactive_stage10_v2",
    "tests.test_capd_proactive_stage10_v2_r2",
)
FORMAL_WORKER_ARGV_SUFFIX = (
    "scripts/run_capd_proactive_stage10_v2_r2.py",
    "--formal-simulation-worker",
    "--config", CONFIG_PATH,
    "--stage9-run-root",
    "outputs/capd_proactive_stage9/stage9-overhead-v2-r3",
    "--approved-freeze-receipt-sha256",
    "<external-approved-freeze-receipt-sha256>",
)
RELEASE_TEST_MODULE = "tests.test_capd_proactive_stage10_v2_release"
READINESS_TEST_ID = RELEASE_TEST_MODULE + ".Stage10V2R2ReadinessDocumentationTest"
FINAL_STATUS_TEST_ID = RELEASE_TEST_MODULE + ".Stage10V2R2FinalStatusDocumentationTest"
STAGE11_AUDIT_ARGV_SUFFIX = (
    "-m", RELEASE_TEST_MODULE,
    "--stage11-negative-audit-worker",
    "--stage10a-run-root",
    "outputs/capd_proactive_stage10/stage10-async-simulator-r1",
    "--stage10-r2-run-root",
    "outputs/capd_proactive_stage10/stage10-async-simulator-v2-r2",
    "--approved-freeze-receipt-sha256",
    "<external-approved-freeze-receipt-sha256>",
)

STAGE11_EXPECTED = {
    "stage10a": {
        "status": "BLOCKED",
        "reason_code": "stage10a_fixture_only",
        "formal_authorized": False,
    },
    "stage10_r2": {
        "status": "NOT_VERIFIABLE",
        "reason_code": "invalid_stage10a_fixture",
        "formal_authorized": False,
    },
    "stage11_positive_migration_authorized": False,
}

_ENTRY_KEYS = {
    "logical_name", "path", "role", "sha256", "generation_identity",
    "generation_test_groups",
}
_ROLES = {"runtime", "runner", "test", "support"}
_TEST_GROUPS = {"generation_core"}
_LOCAL_PACKAGES = {"qmap", "scripts", "tests"}
_STAGE11_TOKENS = (
    "proactive_stage11", "capd_proactive_stage11", "test_capd_proactive_stage11")


class Stage10V2R2ContractError(ValueError):
    """The Stage10 v2-r2 contract is missing, changed, or untrusted."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise Stage10V2R2ContractError(message)


def sha256_file(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def fingerprint_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def self_hash(value: Mapping[str, Any], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return fingerprint_value(payload)


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "JSON object contains a duplicate key: " + key)
        result[key] = value
    return result


def load_json(path: os.PathLike[str] | str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_pairs)


def normalize_relative_path(value: Any) -> str:
    _require(isinstance(value, str) and value, "Source path must be non-empty text.")
    _require("\\" not in value and "//" not in value,
             "Source path must use normalized POSIX separators.")
    _require(not re.match(r"^[A-Za-z]:", value), "Source path cannot be drive-absolute.")
    path = PurePosixPath(value)
    _require(not path.is_absolute(), "Source path cannot be absolute.")
    _require(all(part not in ("", ".", "..") for part in path.parts),
             "Source path contains an unsafe component.")
    normalized = path.as_posix()
    _require(normalized == value, "Source path is not canonical.")
    return normalized


def _is_reparse(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_regular_file(project_root: Path, relative: str) -> Path:
    relative = normalize_relative_path(relative)
    root = project_root.resolve()
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        _require(not candidate.is_symlink() and not _is_reparse(candidate),
                 "Source path traverses a symlink or reparse point: " + relative)
    resolved = candidate.resolve()
    try:
        inside = os.path.commonpath((str(root), str(resolved))) == str(root)
    except ValueError:
        inside = False
    _require(inside and resolved.is_file(),
             "Source path is missing or escapes the project root: " + relative)
    return resolved


def _is_stage11_name(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in _STAGE11_TOKENS)


def _module_candidates(node: ast.AST, current: str) -> Iterable[str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level:
            package = PurePosixPath(current).parent.parts
            prefix = list(package[:max(0, len(package) - node.level + 1)])
            if module:
                prefix.extend(module.split("."))
            module = ".".join(prefix)
        if module in _LOCAL_PACKAGES:
            for alias in node.names:
                if alias.name != "*":
                    yield module + "." + alias.name
        elif module:
            yield module


def _local_module_path(project_root: Path, module: str) -> str | None:
    parts = module.split(".")
    if not parts or parts[0] not in _LOCAL_PACKAGES:
        return None
    file_path = project_root.joinpath(*parts).with_suffix(".py")
    if file_path.is_file():
        return file_path.relative_to(project_root).as_posix()
    package_init = project_root.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        return package_init.relative_to(project_root).as_posix()
    return None


def _python_dependencies(project_root: Path, relative: str) -> set[str]:
    path = resolve_regular_file(project_root, relative)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (SyntaxError, UnicodeError) as exc:
        raise Stage10V2R2ContractError(
            "Generation Python source cannot be parsed: " + relative) from exc
    dependencies = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for module in _module_candidates(node, relative):
                _require(not _is_stage11_name(module),
                         "Generation source imports Stage11: " + relative)
                local = _local_module_path(project_root, module)
                if local:
                    dependencies.add(local)
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            dynamic = (
                isinstance(function, ast.Name) and function.id == "__import__" or
                isinstance(function, ast.Attribute) and
                function.attr in {"import_module", "spec_from_file_location"}
            )
            if dynamic:
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        _require(not _is_stage11_name(argument.value),
                                 "Generation source dynamically loads Stage11: " + relative)
    return dependencies


def validate_source_manifest(value: Any, project_root: Path) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Source manifest must be an object.")
    _require(set(value) == {"schema_version", "source_set_id", "entries"},
             "Source manifest fields are not exact.")
    _require(value.get("schema_version") == SOURCE_MANIFEST_SCHEMA and
             value.get("source_set_id") == SOURCE_SET_ID,
             "Source manifest identity is invalid.")
    entries = value.get("entries")
    _require(isinstance(entries, list) and entries,
             "Source manifest entries must be a non-empty list.")
    paths = []
    logical_names = []
    for entry in entries:
        _require(isinstance(entry, Mapping) and set(entry) == _ENTRY_KEYS,
                 "Source manifest entry fields are not exact.")
        relative = normalize_relative_path(entry.get("path"))
        _require(not _is_stage11_name(relative),
                 "Stage11 path cannot enter generation identity.")
        logical_name = entry.get("logical_name")
        _require(isinstance(logical_name, str) and logical_name,
                 "Source logical name is invalid.")
        _require(entry.get("role") in _ROLES, "Source role is invalid.")
        _require(entry.get("generation_identity") is True,
                 "Generation identity flag must be true.")
        groups = entry.get("generation_test_groups")
        _require(isinstance(groups, list) and groups and len(groups) == len(set(groups)) and
                 set(groups) <= _TEST_GROUPS,
                 "Generation test groups are invalid.")
        expected = entry.get("sha256")
        _require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                 "Source SHA256 is invalid.")
        path = resolve_regular_file(project_root, relative)
        _require(sha256_file(path) == expected, "Source SHA256 mismatch: " + relative)
        paths.append(relative)
        logical_names.append(logical_name)
    _require(paths == sorted(paths), "Source manifest entries are not path-sorted.")
    _require(len(paths) == len(set(paths)) and
             len(logical_names) == len(set(logical_names)),
             "Source manifest paths or logical names are duplicated.")

    path_set = set(paths)
    for relative in paths:
        if relative.endswith(".py"):
            missing = _python_dependencies(project_root, relative) - path_set
            _require(not missing,
                     "Generation dependency is omitted: " + ",".join(sorted(missing)))
    return value


def snapshot_generation_sources(project_root: Path,
                                manifest: Mapping[str, Any],
                                observed_modules: Sequence[str] = ()) -> Mapping[str, Any]:
    validate_source_manifest(manifest, project_root)
    for module in observed_modules:
        _require(isinstance(module, str) and not _is_stage11_name(module),
                 "Generation execution loaded a Stage11 module.")
    entries = []
    for entry in manifest["entries"]:
        current = dict(entry)
        current["sha256"] = sha256_file(
            resolve_regular_file(project_root, entry["path"]))
        entries.append(current)
    return {
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "source_set_id": SOURCE_SET_ID,
        "entry_count": len(entries),
        "fingerprint_sha256": fingerprint_value(entries),
        "entries": entries,
        "observed_local_modules": sorted(set(observed_modules)),
    }


def expected_release_contract(release_test_module_sha256: str) -> Mapping[str, Any]:
    _require(isinstance(release_test_module_sha256, str) and
             re.fullmatch(r"[0-9a-f]{64}", release_test_module_sha256),
             "Release-test module SHA256 is invalid.")
    return {
        "release_test_module": {
            "path": "tests/test_capd_proactive_stage10_v2_release.py",
            "sha256": release_test_module_sha256,
        },
        "readiness_test_argv_suffix": [
            "-m", "unittest", "-v", READINESS_TEST_ID],
        "final_status_test_argv_suffix": [
            "-m", "unittest", "-v", FINAL_STATUS_TEST_ID],
        "stage11_audit_argv_suffix": list(STAGE11_AUDIT_ARGV_SUFFIX),
        "stage11_expected": STAGE11_EXPECTED,
        "stage11_audit_read_only": True,
        "stage11_output_creation_allowed": False,
        "post_seal_stage11_drift": "informational_only",
    }


def _sha_binding(value: Any, name: str) -> None:
    _require(isinstance(value, Mapping), name + " must be an object.")
    digest = value.get("sha256")
    _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
             name + " SHA256 is invalid.")


def _legacy_semantics() -> Mapping[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return load_json(root / "configs/finals/capd_proactive_stage10_v2.json")


def validate_config(value: Any) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Stage10 r2 config must be an object.")
    legacy = _legacy_semantics()
    semantic_fields = {
        "contract_id", "evidence_mode", "success_status", "failure_status",
        "output_root", "result_schema", "result_schema_sha256",
        "byte_recovery_audit", "stage9_binding", "timing_source",
        "timing_conversion_rule", "migration_scenarios", "reference_timing_profile",
        "simulator_parameters", "arrival_profiles", "comparison_channels",
        "scenario_count", "interpretation_boundary",
    }
    expected_fields = semantic_fields | {
        "schema_version", "run_id", "approved_design", "approved_plan",
        "generation_source_manifest", "generation_freeze_receipt",
        "metadata_schemas", "controlled_execution", "generation_tests",
        "formal_simulation_worker", "release_contract",
    }
    _require(set(value) == expected_fields, "Stage10 r2 config fields are not exact.")
    _require(value.get("schema_version") == CONFIG_SCHEMA_VERSION and
             value.get("contract_id") == CONTRACT_ID and
             value.get("run_id") == RUN_ID and
             value.get("evidence_mode") == EVIDENCE_MODE and
             value.get("success_status") == VERIFIED_STATUS and
             value.get("failure_status") == FAILURE_STATUS,
             "Stage10 r2 config identity is invalid.")
    for field in semantic_fields:
        _require(value.get(field) == legacy.get(field),
                 "Stage10 r2 changed frozen v2 simulation semantics: " + field)

    _require(value.get("approved_design") == {
        "path": APPROVED_DESIGN_PATH,
        "sha256": APPROVED_DESIGN_SHA256,
        "status": "design_approved",
    }, "Approved design binding is invalid.")
    _require(value.get("approved_plan") == {
        "path": APPROVED_PLAN_PATH,
        "sha256": APPROVED_PLAN_SHA256,
        "status": "implementation_plan_approved_tasks_0_9",
    }, "Approved plan binding is invalid.")

    manifest = value.get("generation_source_manifest")
    _require(isinstance(manifest, Mapping) and set(manifest) == {
        "path", "sha256", "schema_version", "source_set_id", "entry_count",
        "fingerprint_sha256",
    }, "Generation source-manifest binding is invalid.")
    _require(manifest.get("path") == SOURCE_MANIFEST_PATH and
             manifest.get("schema_version") == SOURCE_MANIFEST_SCHEMA and
             manifest.get("source_set_id") == SOURCE_SET_ID and
             isinstance(manifest.get("entry_count"), int) and
             not isinstance(manifest.get("entry_count"), bool) and
             manifest["entry_count"] > 0,
             "Generation source-manifest identity is invalid.")
    _sha_binding(manifest, "Generation source manifest")
    _require(re.fullmatch(r"[0-9a-f]{64}", manifest.get("fingerprint_sha256", "")),
             "Generation source fingerprint is invalid.")

    _require(value.get("generation_freeze_receipt") == {
        "path": FREEZE_RECEIPT_PATH,
        "schema_version": FREEZE_RECEIPT_SCHEMA,
    }, "Generation freeze-receipt binding is invalid.")

    schemas = value.get("metadata_schemas")
    _require(isinstance(schemas, Mapping) and
             set(schemas) == set(METADATA_SCHEMA_VERSIONS),
             "Metadata schema bindings are incomplete.")
    for name, binding in schemas.items():
        _require(isinstance(binding, Mapping) and set(binding) == {"path", "sha256"} and
                 binding.get("path") == f"configs/finals/{name}.json",
                 "Metadata schema path is invalid: " + name)
        _sha_binding(binding, "Metadata schema " + name)

    _require(value.get("controlled_execution") == CONTROLLED_EXECUTION,
             "Controlled-execution contract changed.")
    tests = value.get("generation_tests")
    _require(isinstance(tests, Mapping) and set(tests) == {
        "interpreter_policy", "argv_suffix", "expected_test_count",
        "ordered_verbose_test_ids",
    }, "Generation-test contract fields are invalid.")
    _require(tests.get("interpreter_policy") == "current_runner_sys_executable" and
             tests.get("argv_suffix") == list(GENERATION_TEST_ARGV_SUFFIX) and
             isinstance(tests.get("expected_test_count"), int) and
             not isinstance(tests.get("expected_test_count"), bool) and
             tests["expected_test_count"] > 0 and
             isinstance(tests.get("ordered_verbose_test_ids"), list) and
             len(tests["ordered_verbose_test_ids"]) == tests["expected_test_count"] and
             all(isinstance(item, str) and item for item in
                 tests["ordered_verbose_test_ids"]),
             "Generation-test command/count identity is invalid.")
    _require(value.get("formal_simulation_worker") == {
        "interpreter_policy": "current_runner_sys_executable",
        "argv_suffix": list(FORMAL_WORKER_ARGV_SUFFIX),
    }, "Formal-simulation worker identity is invalid.")
    release = value.get("release_contract")
    _require(isinstance(release, Mapping), "Release contract is missing.")
    module = release.get("release_test_module")
    _sha_binding(module, "Release-test module")
    _require(release == expected_release_contract(module["sha256"]),
             "Release contract changed.")
    return value


def expected_freeze_receipt(config: Mapping[str, Any],
                            project_root: Path) -> Mapping[str, Any]:
    """Construct the complete repository-owned generation freeze contract."""
    validate_config(config)
    project_root = Path(project_root).resolve()
    source_path = resolve_regular_file(project_root, SOURCE_MANIFEST_PATH)
    source_manifest = load_json(source_path)
    source_snapshot = snapshot_generation_sources(project_root, source_manifest)
    source_binding = config["generation_source_manifest"]
    _require(
        sha256_file(source_path) == source_binding["sha256"] and
        source_snapshot["entry_count"] == source_binding["entry_count"] and
        source_snapshot["fingerprint_sha256"] ==
        source_binding["fingerprint_sha256"],
        "Freeze receipt source-manifest binding changed.",
    )

    schema_bindings = {
        "result_schema": {
            "path": config["result_schema"],
            "sha256": config["result_schema_sha256"],
        },
        "metadata_schemas": config["metadata_schemas"],
    }
    for binding in [schema_bindings["result_schema"],
                    *schema_bindings["metadata_schemas"].values()]:
        path = resolve_regular_file(project_root, binding["path"])
        _require(sha256_file(path) == binding["sha256"],
                 "Freeze receipt schema binding changed: " + binding["path"])

    release_module = config["release_contract"]["release_test_module"]
    release_path = resolve_regular_file(project_root, release_module["path"])
    _require(sha256_file(release_path) == release_module["sha256"],
             "Freeze receipt release-test binding changed.")
    protocol_path = resolve_regular_file(project_root, PROTOCOL_PATH)
    environment_schema = config["metadata_schemas"][
        "capd_proactive_stage10_execution_environment_schema"]

    return {
        "schema_version": FREEZE_RECEIPT_SCHEMA,
        "source_set_id": SOURCE_SET_ID,
        "approved_design": config["approved_design"],
        "approved_plan": config["approved_plan"],
        "config": {
            "path": CONFIG_PATH,
            "sha256": sha256_file(resolve_regular_file(project_root, CONFIG_PATH)),
            "canonical_sha256": fingerprint_value(config),
        },
        "source_manifest": source_binding,
        "schemas": schema_bindings,
        "commands": {
            "generation_tests": config["generation_tests"],
            "formal_simulation_worker": config["formal_simulation_worker"],
            "release_contract": config["release_contract"],
            "protocol": {
                "path": PROTOCOL_PATH,
                "sha256": sha256_file(protocol_path),
            },
        },
        "controlled_execution": config["controlled_execution"],
        "environment_contract": {
            "schema": environment_schema,
            "required_fields": list(ENVIRONMENT_FIELDS),
            "declared_non_standard_dependency_names": [],
            "dependency_policy": "standard_library_only",
            "wall_clock_time_role": "observational_only",
            "deterministic_result_comparison": "byte_exact",
        },
        "stage9_binding": {
            "authority": config["stage9_binding"],
            "byte_recovery_audit": config["byte_recovery_audit"],
        },
        "authorization_state": {
            "formal_run_authorized_at_receipt_creation": False,
            "release_authorized_at_receipt_creation": False,
            "stage11_positive_migration_authorized_at_receipt_creation": False,
        },
    }


def validate_freeze_receipt(value: Any, config: Mapping[str, Any],
                            project_root: Path) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "Freeze receipt must be an object.")
    expected = expected_freeze_receipt(config, project_root)
    _require(value == expected,
             "Freeze receipt does not match the complete independently constructed object.")
    return value
