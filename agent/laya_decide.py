"""Laya typed-decision layer (System 1 classifier for the agent loop).

One forward pass per case over a compact state:
  - pattern: choice over the 7 fraud patterns (policy criteria)
  - is_fraud: noul calibrated fraud probability
  - needs_report: noul SAR-filing signal
Server: POST <LAYA_BASE_URL>/v1/systemone, Bearer <LAYA_API_KEY>.
State budget ~512 tokens/question: slim_state() keeps it compact.
"""
import json
import os
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

BASE = Path(__file__).parent.parent

PATTERN_CRITERIA = {
    "card_testing": "three or more tiny online authorizations then a larger purchase",
    "card_not_present_fraud": "unusual online purchase, amount or product outside history",
    "card_not_present_new_device": "unusual online purchase from a device marked New",
    "out_of_region_use": "card-present use in a region with no history while home use continues",
    "account_takeover": "mixed-channel activity inconsistent with holder, device anomalies",
    "undocumented": "coordinated or repeated abuse matching none of the known patterns",
    "none": "no fraud indicators; ordinary legitimate activity",
}


def laya_config():
    env = dotenv_values(BASE / ".env")
    return {
        "base_url": (env.get("LAYA_BASE_URL") or os.getenv("LAYA_BASE_URL") or "").rstrip("/"),
        "api_key": env.get("LAYA_API_KEY") or os.getenv("LAYA_API_KEY") or "",
    }


def slim_state(case, flagged, f):
    """Compact state under the per-question token budget."""
    sigs = []
    if (f.get("burst_48h") or 0) >= 2:
        sigs.append(f"burst{ f['burst_48h'] }in48h")
    if f.get("testing_seq"):
        sigs.append("testing-sequence")
    if f.get("new_device"):
        sigs.append("new-device")
    if f.get("proxy"):
        sigs.append("proxy")
    if f.get("novel_region"):
        sigs.append(f"novel-region-{f.get('addr1', '')}")
    if f.get("novel_product"):
        sigs.append(f"novel-product-{f.get('product_cd', '')}")
    if (f.get("recur_same", 0) or 0) >= 3:
        sigs.append(f"recurring-x{f['recur_same']}")
    if f.get("shared_cards"):
        sigs.append(f"shared-device-{len(f['shared_cards'])}-cards")
    return {
        "trigger": case.get("trigger_type", ""),
        "denial": "customer denies charge" if case.get("trigger_type") == "customer_report" else "",
        "txn": (f"${f.get('amount', 0):.2f} {f.get('channel', '')} "
                f"{f.get('product_cd', '')} risk {f.get('risk_score', 0)} "
                f"region {f.get('addr1') or 'none'}"),
        "baseline": (f"max ${f.get('prior_max', 0):.2f} mean ${f.get('prior_mean', 0):.2f} "
                     f"ratio {f.get('amount_ratio', 0):.1f}x over {f.get('n_prior', 0)} priors"),
        "signals": ";".join(sigs) or "none",
    }


def decide_case(cfg, state, timeout=120):
    """Single forward pass. Returns (pattern, pattern_conf, p_fraud, p_report)."""
    body = json.dumps({
        "state": state,
        "questions": {
            "pattern": {"type": "choice",
                        "instructions": "Which fraud pattern best describes this alert?",
                        "criteria": PATTERN_CRITERIA},
            "is_fraud": {"type": "noul",
                         "instructions": "Is the flagged activity fraud?"},
            "needs_report": {"type": "noul",
                             "instructions": "Does this warrant a regulatory filing?"},
        },
    }).encode()
    req = urllib.request.Request(
        cfg["base_url"] + "/v1/systemone", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ans = json.load(r)["answers"]
    pat = ans["pattern"]
    rep = ans["needs_report"]
    return {
        "pattern": pat.get("choice", "none"),
        "pattern_conf": float(pat.get("confidence", 0) or 0),
        "pattern_dist": {k: round(float(v), 3) for k, v in
                         (pat.get("probabilities") or pat.get("distribution") or {}).items()},
        "p_fraud": float(ans["is_fraud"].get("noul", 0.5) or 0.5),
        "fraud_conf": float(ans["is_fraud"].get("confidence", 0) or 0),
        "p_report": float(rep.get("noul", 0) or 0),
    }
