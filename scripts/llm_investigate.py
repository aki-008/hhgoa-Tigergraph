"""Thin CLI for the LLM fraud investigator. Logic lives in agent/.

Usage:
  python scripts/llm_investigate.py --brief-only --case HHG-014
  python scripts/llm_investigate.py --pilot
  python scripts/llm_investigate.py --all
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
runpy.run_module("agent.llm_runner", run_name="__main__")
