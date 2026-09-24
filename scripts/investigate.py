"""Thin CLI for the rule-based fraud investigator. Logic lives in agent/.

Usage:
  python scripts/investigate.py --case HHG-001
  python scripts/investigate.py --all [--skip HHG-001,HHG-002]
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
runpy.run_module("agent.runner", run_name="__main__")
