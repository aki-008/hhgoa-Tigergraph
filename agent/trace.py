"""Trace logger (spec items 9+10 support).

Appends JSONL events incrementally so the dashboard can poll a live run:
cases/<case_id>.trace.jsonl — one event per line.
Also keeps an in-memory copy for the final answer file.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import BASE


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Tracer:
    def __init__(self, case_id, live=True, out_dir="cases"):
        self.case_id = case_id
        self.live = live
        self.events = []
        self.tokens = {"prompt": 0, "completion": 0}
        self.path = BASE / out_dir / f"{case_id}.trace.jsonl"
        if self.live:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")  # fresh run

    def log(self, step, msg, data=None, prompt_tokens=0, completion_tokens=0):
        ev = {"t": _now(), "step": step, "msg": msg, "data": data or {},
              "tokens": {"prompt": prompt_tokens, "completion": completion_tokens}}
        self.events.append(ev)
        self.tokens["prompt"] += prompt_tokens
        self.tokens["completion"] += completion_tokens
        if self.live:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev) + "\n")
        return ev

    def totals(self):
        return {"events": len(self.events), **self.tokens,
                "total_tokens": self.tokens["prompt"] + self.tokens["completion"]}
