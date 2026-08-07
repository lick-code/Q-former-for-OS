"""Shared path and write-capability guard for Stage11 v2."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


class Stage11V2PathError(ValueError):
  """A requested read or write path violates the Stage11 v2 boundary."""


_CAPABILITY_SECRET = object()


@dataclass(frozen=True)
class _WriteCapability:
  root: Path
  mode: str
  run_id: str
  nonce: str
  _secret: object


def _require(condition: bool, message: str) -> None:
  if not condition:
    raise Stage11V2PathError(message)


def _is_within(parent: Path, child: Path) -> bool:
  try:
    child.relative_to(parent)
    return True
  except ValueError:
    return False


def _check_existing_components(path: Path) -> None:
  current = Path(path.anchor) if path.anchor else Path()
  for part in path.parts[1:] if path.anchor else path.parts:
    current = current / part
    if not current.exists():
      continue
    _require(not current.is_symlink(), "Path contains a symbolic link: {}".format(current))
    try:
      attributes = current.stat().st_file_attributes
    except AttributeError:
      attributes = 0
    reparse_flag = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    _require(not (attributes & reparse_flag),
             "Path contains a reparse point: {}".format(current))


def validate_read_root(requested_root: os.PathLike[str] | str,
                       allowed_parent: os.PathLike[str] | str) -> Path:
  requested = Path(requested_root).absolute()
  parent = Path(allowed_parent).resolve()
  _check_existing_components(requested)
  resolved = requested.resolve(strict=False)
  _require(resolved != parent and _is_within(parent, resolved),
           "Read root escapes its approved parent.")
  return resolved


def validate_synthetic_output_root(
    requested_root: os.PathLike[str] | str,
    test_temp_root: os.PathLike[str] | str,
    production_root: os.PathLike[str] | str,
) -> Path:
  """Reject an unsafe synthetic target before any fixture evidence is read."""
  requested = Path(requested_root).absolute()
  _check_existing_components(requested)
  resolved = requested.resolve(strict=False)
  temp_root = Path(test_temp_root).resolve()
  production = Path(production_root).absolute().resolve(strict=False)
  _require(temp_root.is_dir(), "Synthetic temp root must already exist.")
  _require(resolved != temp_root and _is_within(temp_root, resolved),
           "Synthetic output escapes the test temp root.")
  _require(resolved != production and not _is_within(production, resolved),
           "Synthetic output cannot target the production root.")
  return resolved


def authorize_write_context(
    mode: str,
    requested_root: os.PathLike[str] | str,
    run_id: str,
    authorization: Mapping[str, Any],
    *,
    test_temp_root: Optional[os.PathLike[str] | str] = None,
    production_root: Optional[os.PathLike[str] | str] = None,
    production_enabled: bool = False,
) -> _WriteCapability:
  _require(mode in ("synthetic", "production"), "Unknown write mode.")
  _require(isinstance(run_id, str) and run_id and Path(run_id).name == run_id,
           "Invalid run_id path component.")
  requested = Path(requested_root).absolute()
  _check_existing_components(requested)
  resolved = requested.resolve(strict=False)
  configured_production = (
      Path(production_root).absolute().resolve(strict=False)
      if production_root is not None else None)

  if mode == "synthetic":
    _require(test_temp_root is not None, "Synthetic mode requires a test temp root.")
    temp_root = Path(test_temp_root).resolve()
    _require(temp_root.is_dir(), "Synthetic temp root must already exist.")
    if configured_production is None:
      _require(resolved != temp_root and _is_within(temp_root, resolved),
               "Synthetic output escapes the test temp root.")
    else:
      validate_synthetic_output_root(resolved, temp_root, configured_production)
    _require(authorization.get("synthetic_test_only") is True,
             "Synthetic writes require a synthetic authorization.")
  else:
    _require(production_enabled is True,
             "Production writes are not authorized by this implementation scope.")
    _require(configured_production is not None and
             resolved == configured_production / run_id,
             "Production output must be the exact configured run root.")
    _require(authorization.get("synthetic_test_only") is False,
             "Production writes reject synthetic authorization.")

  return _WriteCapability(
      root=resolved, mode=mode, run_id=run_id,
      nonce=secrets.token_hex(16), _secret=_CAPABILITY_SECRET)


def require_capability(capability: Any,
                       target: Optional[os.PathLike[str] | str] = None
                       ) -> _WriteCapability:
  _require(isinstance(capability, _WriteCapability) and
           capability._secret is _CAPABILITY_SECRET,
           "A valid write capability is required.")
  _check_existing_components(capability.root)
  root = capability.root.resolve(strict=False)
  _require(root == capability.root, "Capability root identity changed.")
  if target is not None:
    resolved = Path(target).absolute().resolve(strict=False)
    _require(resolved == root or _is_within(root, resolved),
             "Writer target escapes the capability root.")
  return capability


def child_target(capability: Any, relative: str) -> Path:
  cap = require_capability(capability)
  _require(isinstance(relative, str) and relative and
           not Path(relative).is_absolute(), "Writer path must be relative.")
  target = (cap.root / relative).resolve(strict=False)
  require_capability(cap, target)
  return target
