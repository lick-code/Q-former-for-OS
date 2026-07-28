# coding=utf-8
"""Machine-check the strict Full-versus-NoVPN configuration allowlist."""

from __future__ import print_function

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from qmap import no_vpn_ablation


DEFAULT_FULL = "configs/finals/capd_direction1_v3_ablation_full.json"
DEFAULT_NO_VPN = "configs/finals/capd_direction1_v3_no_vpn.json"
DEFAULT_REFERENCE = "configs/finals/capd_direction1_v3.json"


def main():
  parser = argparse.ArgumentParser(
      description="Validate the CAPD Full/NoVPN single-variable config pair.")
  parser.add_argument("--full-config", default=DEFAULT_FULL)
  parser.add_argument("--no-vpn-config", default=DEFAULT_NO_VPN)
  parser.add_argument("--reference-config", default=DEFAULT_REFERENCE)
  parser.add_argument("--resolved", action="store_true")
  parser.add_argument("--json-output", default=None)
  args = parser.parse_args()

  full_config = finals_config.load_config(
      args.full_config, require_resolved=args.resolved,
      project_root=PROJECT_ROOT, verify_manifest_files=False)
  no_vpn_config = finals_config.load_config(
      args.no_vpn_config, require_resolved=args.resolved,
      project_root=PROJECT_ROOT, verify_manifest_files=False)
  reference_config = finals_config.load_config(args.reference_config)
  if not args.resolved:
    no_vpn_ablation.assert_variant_matches_reference(
        reference_config, full_config)
    no_vpn_ablation.assert_variant_matches_reference(
        reference_config, no_vpn_config)
  differences = no_vpn_ablation.assert_config_pair(
      full_config, no_vpn_config, allow_resolved=args.resolved)
  payload = {
      "status": "passed",
      "full_config": os.path.abspath(args.full_config),
      "no_vpn_config": os.path.abspath(args.no_vpn_config),
      "reference_config": os.path.abspath(args.reference_config),
      "allowed_differences": {
          ".".join(path): {"full": values[0], "no_vpn": values[1]}
          for path, values in sorted(differences.items())
          if path in no_vpn_ablation.ALLOWED_CONFIG_DIFFS
      },
  }
  if args.json_output:
    finals_config.write_json(args.json_output, payload)
  print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
  main()
