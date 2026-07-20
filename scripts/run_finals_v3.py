# coding=utf-8
"""Isolated server entry point for CAPD-MIC-1.0 / capd_finals_v3_0."""

from __future__ import print_function

import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from qmap import finals_config
from scripts.run_finals_v2 import main


if __name__ == "__main__":
  main(expected_schema=finals_config.SCHEMA_VERSION,
       runner_label="finals_v3.0 official",
       expected_profile=finals_config.OFFICIAL_PROFILE)
