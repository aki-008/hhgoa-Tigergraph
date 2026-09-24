"""Baseline eval: Laya base checkpoint over all 20 case briefs.
Compares Laya pattern + fraud probability vs rule-based + LLM verdicts.
Run: python scripts/eval_laya.py
"""
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent import laya_decide as L  # noqa: E402
from agent.evidence import BASE  # noqa: E402
from agent.features import build_features  # noqa: E402
from agent.grounding import brief_query_text  # noqa: E402 (unused, keeps import warm)


def card_rows(customer_id):
    rows = []
    with open(BASE / "data" / "transactions.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("customer_id") == customer_id:
                rows.append(r)
    rows.sort(key=lambda r: r.get("ts", ""))
    return rows


def identity_for(txn_id):
    with open(BASE / "data" / "identity.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("TransactionID") == str(txn_id):
                return r
    return {}


async def main():
    cfg = L.laya_config()
    assert cfg["base_url"] and cfg["api_key"], "LAYA config missing in .env"
    pack = {}
    with open(BASE / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pack[r["case_id"]] = r
    print(f"{'case':8} {'laya_pat':28} {'conf':6} {'p_fraud':8} rule_verdict/p | llm_verdict/p")
    for cid in sorted(pack):
        case = pack[cid]
        rows = card_rows(case["customer_id"])
        flagged = next((t for t in rows
                        if str(t.get("TransactionID")) == str(case["flagged_txn_id"])), None)
        # minimal identity enrichment (same fields build_features needs)
        f, _ = build_features(case, rows, flagged)
        f["shared_cards"] = []
        state = L.slim_state(case, flagged, f)
        t0 = time.time()
        try:
            res = L.decide_case(cfg, state)
            lat = round(time.time() - t0, 1)
        except Exception as e:  # noqa: BLE001
            print(f"{cid:8} ERROR {type(e).__name__}: {str(e)[:100]}")
            continue
        rule, llm = {}, {}
        try:
            r = json.load(open(BASE / "cases" / f"{cid}.json"))
            rule = (r["case"]["verdict"], r["case"]["fraud_probability"], r["case"]["pattern"])
        except OSError:
            pass
        try:
            l = json.load(open(BASE / "cases" / f"{cid}.llm.json"))
            llm = (l["case"]["verdict"], l["case"]["fraud_probability"], l["case"]["pattern"])
        except OSError:
            pass
        print(f"{cid:8} {res['pattern']:28} {res['pattern_conf']:.2f}   "
              f"{res['p_fraud']:.3f}   {rule} | {llm} [{lat}s]")
        out = BASE / "cases" / "_laya_baseline.json"
        prev = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        prev[cid] = res
        out.write_text(json.dumps(prev, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
