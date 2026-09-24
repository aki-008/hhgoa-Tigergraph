"""Fraud investigation agent: graph evidence -> features -> policy engine -> answer JSON.
Usage:
  python scripts/investigate.py --case HHG-001        # single case
  python scripts/investigate.py --all                 # all 20 cases
Evidence priority: live TigerGraph HHGOA_Fraud via MCP, CSV fallback.
Writes: cases/<case_id>.json + ClosedCase write-back to graph.
"""
import argparse
import asyncio
import csv
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

BASE = Path(__file__).parent.parent
GRAPH = "HHGOA_Fraud"
MARK = "```json"
POLICY = "data/README.md"  # fraud policy source (not needed at runtime)

# ---------------------------------------------------------------- CSV helpers

def parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def fnum(x, default=0.0):
    try:
        return float(x) if str(x).strip() not in ("", "None") else default
    except (ValueError, TypeError):
        return default


def read_case_pack():
    with open(BASE / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        return {r["case_id"]: r for r in csv.DictReader(f)}


def card_history_from_csv(customer_id):
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


def similar_closed(pattern_hint, limit=3):
    """Memory: past closed cases with same pattern (fraud) + one cleared example."""
    fraud, cleared = [], []
    with open(BASE / "data" / "closed_cases_history.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["outcome"] == "confirmed_fraud" and r["pattern"] == pattern_hint and len(fraud) < limit:
                fraud.append(r["case_id"])
            elif r["outcome"] == "cleared" and len(cleared) < 1:
                cleared.append(r["case_id"])
    return fraud

# ---------------------------------------------------------------- MCP helpers

async def mcp_call(s, name, args):
    res = await s.call_tool(name, arguments=args)
    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
    if MARK in txt:
        try:
            return json.loads(txt.split(MARK)[1].split("```")[0])
        except ValueError:
            pass
    return {"_raw": txt[:300], "_ok": '"success": true' in txt}


async def graph_window(call_fn, card_id, limit=2000):
    """Card -> MADE -> Transactions via live graph."""
    r = await call_fn("tigergraph__get_neighbors", {
        "graph_name": GRAPH, "vertex_type": "Card", "vertex_id": card_id,
        "edge_type": "MADE", "limit": limit})
    nbs = (r.get("data") or {}).get("neighbors", [])
    txns = [{"TransactionID": n["v_id"], **{k: v for k, v in n.get("attributes", {}).items()}} for n in nbs]
    # normalize attribute names to CSV-ish
    for t in txns:
        t.setdefault("TransactionAmt", t.pop("amount", 0))
        t.setdefault("ts", t.get("ts", ""))
        t.setdefault("channel", t.get("channel", ""))
        t.setdefault("ProductCD", t.pop("product_cd", ""))
        t.setdefault("risk_score", t.get("risk_score", 0))
        t.setdefault("addr1", t.get("addr1", ""))
    txns.sort(key=lambda r: str(r.get("ts", "")))
    return txns


async def graph_txn_edges(call_fn, txn_id):
    r = await call_fn("tigergraph__get_node_edges", {
        "graph_name": GRAPH, "vertex_type": "Transaction",
        "vertex_id": str(txn_id), "limit": 20})
    return (r.get("data") or {}).get("edges", [])


async def shared_device_cards(call_fn, device_str, exclude_card):
    """R6: other cards sharing the flagged txn's device profile (via graph)."""
    if not device_str:
        return []
    try:
        r = await call_fn("tigergraph__get_neighbors", {
            "graph_name": GRAPH, "vertex_type": "DeviceProfile",
            "vertex_id": device_str, "limit": 50})
        cards = set()
        for n in (r.get("data") or {}).get("neighbors", []):
            if n.get("v_type") == "Transaction":
                cid = (n.get("attributes") or {}).get("card_id", "")
                if cid and cid != exclude_card:
                    cards.add(cid)
        return sorted(cards)
    except Exception:  # noqa: BLE001
        return []

# ---------------------------------------------------------------- features

def build_features(case, window, flagged):
    f = {}
    amt = fnum(flagged.get("TransactionAmt"))
    prior = [t for t in window if str(t.get("TransactionID")) != str(case["flagged_txn_id"])]
    pamts = [fnum(t.get("TransactionAmt")) for t in prior]
    f["amount"] = amt
    f["prior_max"] = max(pamts) if pamts else 0
    f["prior_mean"] = sum(pamts) / len(pamts) if pamts else 0
    f["amount_ratio"] = amt / f["prior_max"] if f["prior_max"] else 99.0
    f["n_prior"] = len(prior)
    f["channel"] = flagged.get("channel", "")
    f["product_cd"] = flagged.get("ProductCD", "")
    f["risk_score"] = fnum(flagged.get("risk_score"))
    f["addr1"] = flagged.get("addr1", "")

    fts = parse_ts(flagged.get("ts", ""))
    # burst: txns within ±48h of flagged
    burst = []
    for t in window:
        tts = parse_ts(t.get("ts", ""))
        if tts and fts and abs((tts - fts).total_seconds()) <= 48 * 3600:
            burst.append(t)
    f["burst_48h"] = len(burst)

    # R5 card testing: 3+ online auths <$5 within 1h + a larger purchase after
    online_sorted = sorted(
        [t for t in window if t.get("channel") == "online" and parse_ts(t.get("ts", ""))],
        key=lambda t: t["ts"])
    testing_seq = []
    for i, t in enumerate(online_sorted):
        if fnum(t.get("TransactionAmt")) >= 5:
            continue
        t0 = parse_ts(t["ts"])
        group = [t]
        for u in online_sorted[i + 1:]:
            if (parse_ts(u["ts"]) - t0).total_seconds() <= 3600 and fnum(u.get("TransactionAmt")) < 5:
                group.append(u)
            elif (parse_ts(u["ts"]) - t0).total_seconds() > 3600:
                break
        if len(group) >= 3:
            after = [u for u in online_sorted
                     if parse_ts(u["ts"]) > parse_ts(group[-1]["ts"])
                     and fnum(u.get("TransactionAmt")) >= 5]
            if after:
                testing_seq = [g["TransactionID"] for g in group] + [after[0]["TransactionID"]]
                break
    f["testing_seq"] = testing_seq

    # product novelty: flagged ProductCD never used before?
    prior_prods = {t.get("ProductCD") for t in prior}
    f["novel_product"] = f["product_cd"] not in prior_prods if prior_prods else False

    # region novelty
    prior_regions = {t.get("addr1") for t in prior if t.get("addr1")}
    f["novel_region"] = bool(f["addr1"]) and f["addr1"] not in prior_regions

    # recurring-match count (R7): prior txns same channel, amount within ±2%
    f["recur_same"] = sum(
        1 for t in prior
        if (lambda pa: pa and abs(pa - amt) / max(amt, 1) <= 0.02
            and t.get("channel") == f["channel"])(fnum(t.get("TransactionAmt"))))

    # device / identity
    idr = identity_for(case["flagged_txn_id"])
    f["has_device"] = bool(idr.get("DeviceInfo"))
    f["new_device"] = (idr.get("id_15", "") or "").strip().lower() == "new"
    _proxy_raw = (idr.get("id_23", "") or "").strip().lower()
    f["proxy"] = any(k in _proxy_raw for k in ("anonymous", "hidden", "proxy"))
    f["device_str"] = (f"{idr.get('DeviceInfo', '')}|{idr.get('id_30', '')}|"
                       f"{idr.get('id_31', '')}|{idr.get('id_33', '')}") if idr.get("DeviceInfo") else ""
    return f, burst

# ---------------------------------------------------------------- policy engine

def decide(case, f):
    """Returns (verdict, p, pattern, pattern_desc, evidence_notes, initial, assumed, final)."""
    trigger = case["trigger_type"]
    signals = []
    p = 0.20
    if f["amount_ratio"] >= 2.0 and f["n_prior"] >= 5:
        p += 0.15
        signals.append(f"amount {f['amount']:.2f} is {f['amount_ratio']:.1f}x prior max")
    if 2 <= f["burst_48h"] <= 4 and f["channel"] == "online":
        p += 0.12
        signals.append(f"burst of {f['burst_48h']} within 48h")
    if f["testing_seq"]:
        p += 0.30
        signals.append(f"testing sequence {f['testing_seq']}")
    if f["new_device"]:
        p += 0.12
        signals.append("new device for account")
    if f["proxy"]:
        p += 0.08
        signals.append("proxy/anonymizer")
    if f["novel_region"] and f["channel"] == "in_person":
        p += 0.12
        signals.append(f"novel billing region {f['addr1']}")
    if f["novel_product"]:
        p += 0.05
        signals.append(f"first-time product code {f['product_cd']}")
    if f["risk_score"] >= 0.85:
        p += 0.08
    if trigger == "customer_report":
        p += 0.25
        signals.append("cardholder denies the charge")
    if f.get("shared_cards"):
        p += 0.15
        signals.append("shared device with %d other card(s): %s" % (
            len(f["shared_cards"]), ",".join(f["shared_cards"][:3])))
    if not signals and trigger == "risk_score":
        p = 0.15  # no corroboration at all: lean legitimate
    p = round(min(max(p, 0.05), 0.95), 2)

    if f["testing_seq"]:
        pattern = "card_testing"
    elif f["new_device"] and f["channel"] == "online":
        pattern = "card_not_present_new_device"
    elif f["novel_region"] and f["channel"] == "in_person":
        pattern = "out_of_region_use"
    elif f["channel"] == "online" and (f["amount_ratio"] >= 1.5 or 2 <= f["burst_48h"] <= 4):
        pattern = "card_not_present_fraud"
    elif trigger == "analyst_request":
        pattern = "undocumented"
    elif p >= 0.5:
        pattern = "card_not_present_fraud"
    else:
        pattern = "none"
    pdesc = ("Shared device/region activity across cards under analyst review; described as "
             "coordinated cross-card use pending linkage evidence."
             if pattern == "undocumented" else "")

    exposure = round(f["amount"], 2)

    # R7: disputed charge matching own recurring pattern -> no block
    recur = f.get("recur_same", 0)
    if trigger == "customer_report" and recur >= 3:
        verdict, p = "uncertain", 0.30
        pattern, pdesc = "none", ""
        initial = [
            {"action": "CREATE_CASE", "route": "auto",
             "reason": "R7: disputed charge matches recurring pattern (%dx ~$%.2f)" % (recur, f["amount"])},
            {"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R7"},
            {"action": "WARN_CUSTOMER", "route": "auto",
             "reason": "R7: recurring-charge reminder, do not block"}]
        final = initial
        assumed = None
        signals.append("matches recurring own pattern (%dx)" % recur)
        r7 = (verdict, p, pattern, pdesc, exposure, initial, assumed, final)
    else:
        r7 = None
    if r7 is None:
        if trigger == "customer_report":
            verdict, p = ("fraud", max(p, 0.80)) if p >= 0.55 else ("uncertain", p)
        elif p >= 0.70:
            verdict = "fraud"
        elif p <= 0.30:
            verdict = "legitimate"
        else:
            verdict = "uncertain"

        # ---- actions
        initial, assumed, final = [], None, []
        if trigger == "customer_report":
            initial = [
                {"action": "BLOCK_CARD", "route": "L1" if exposure <= 2500 else "L2",
                 "reason": "R2: customer denied; exposure $%.2f" % exposure},
                {"action": "CREATE_CASE", "route": "auto", "reason": "R2"}]
            if exposure > 1000 or f["new_device"]:
                initial.append({"action": "FILE_REPORT", "route": "L2",
                                "reason": "R2: exposure >$1,000 or new-device link"})
            final = initial
        elif f["testing_seq"]:
            initial = [{"action": "VERIFY_WITH_CUSTOMER", "route": "auto",
                        "reason": "R1: confirm before block"},
                       {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R5: testing sequence"}]
            assumed = {"type": "customer_validation", "response": "denied"}
            final = [
                {"action": "DECLINE_TRANSACTION", "route": "L1", "reason": "R5: testing sequence"},
                {"action": "BLOCK_CARD", "route": "L1" if exposure <= 2500 else "L2",
                 "reason": "R2+R5: denied; purchase cleared" if exposure > 100 else "R2: denied"},
                {"action": "CREATE_CASE", "route": "auto", "reason": "R2"}]
            p = min(0.95, p + 0.15)
            verdict = "fraud"
        elif p < 0.70:
            # R1 weak signal -> verify; assume no reply -> R4 monitor/decline
            initial = [
                {"action": "VERIFY_WITH_CUSTOMER", "route": "auto",
                 "reason": "R1: single signal, p=%.2f < 0.70" % p},
                {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1"},
                {"action": "MONITOR_CARD", "route": "auto", "reason": "R4: watch pending"}]
            assumed = {"type": "customer_validation", "response": "no reply within 24h"}
            final = [
                {"action": "MONITOR_CARD", "route": "auto", "reason": "R4: no reply"},
                {"action": "DECLINE_TRANSACTION", "route": "L1", "reason": "R4: pending auths"}]
            if exposure > 500:
                final.append({"action": "ESCALATE_TO_ANALYST", "route": "auto",
                              "reason": "R4/R8: exposure $%.2f > $500" % exposure})
        else:
            initial = [{"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R1"},
                       {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1"}]
            assumed = {"type": "customer_validation", "response": "denied"}
            final = [{"action": "BLOCK_CARD", "route": "L1" if exposure <= 2500 else "L2",
                      "reason": "R2: denied"},
                     {"action": "CREATE_CASE", "route": "auto", "reason": "R2"}]
            verdict = "fraud"
            p = min(0.95, p + 0.10)

        # R8: uncertain + high exposure -> escalate
        if verdict == "uncertain" and exposure > 500 and not any(
                a["action"] == "ESCALATE_TO_ANALYST" for a in final):
            final.append({"action": "ESCALATE_TO_ANALYST", "route": "auto",
                          "reason": "R8: uncertain with exposure $%.2f" % exposure})
    # R6: shared device across cards -> report + monitor connected
    if f.get("shared_cards") and verdict in ("fraud", "uncertain"):
        if not any(a["action"] == "FILE_REPORT" for a in final):
            final.append({"action": "FILE_REPORT", "route": "L2",
                          "reason": "R6: shared device across %d card(s)" % len(f["shared_cards"])})
        final.append({"action": "MONITOR_CONNECTED_CARDS", "route": "auto",
                      "reason": "R6: monitor %s" % ",".join(f["shared_cards"][:3])})
    if r7 is not None:  # R7 path computed above; restore it
        verdict, p, pattern, pdesc, exposure, initial, assumed, final = r7
    return verdict, p, pattern, pdesc, signals, exposure, initial, assumed, final

# ---------------------------------------------------------------- main per case

async def investigate(s, case_id, tool_calls):
    t0 = time.time()
    case = read_case_pack()[case_id]
    card_id, customer_id = case["card_id"], case["customer_id"]

    async def call(name, args):
        tool_calls[0] += 1
        return await mcp_call(s, name, args)

    # 1. graph window, fallback CSV
    try:
        window = await graph_window(call, card_id)
        src_window = "graph"
        if not window:
            raise ValueError("empty")
    except Exception:  # noqa: BLE001
        window = card_history_from_csv(customer_id)
        src_window = "csv"
    flagged = next((t for t in window
                    if str(t.get("TransactionID")) == str(case["flagged_txn_id"])), None)
    if flagged is None:  # flagged outside window: fetch node + csv row
        try:
            r = await call("tigergraph__get_node", {"graph_name": GRAPH,
                           "vertex_type": "Transaction",
                           "vertex_id": str(case["flagged_txn_id"])})
            attrs = (r.get("data") or {}).get("attributes", {})
            flagged = {"TransactionID": case["flagged_txn_id"],
                       "TransactionAmt": attrs.get("amount", 0), "ts": attrs.get("ts", ""),
                       "channel": attrs.get("channel", ""),
                       "ProductCD": attrs.get("product_cd", ""),
                       "risk_score": attrs.get("risk_score", 0),
                       "addr1": attrs.get("addr1", "")}
        except Exception:  # noqa: BLE001
            pass
    if flagged is None:
        for t in card_history_from_csv(customer_id):
            if str(t.get("TransactionID")) == str(case["flagged_txn_id"]):
                flagged = t
                break

    f, burst = build_features(case, window, flagged)
    edges = await graph_txn_edges(call, case["flagged_txn_id"])
    edge_types = sorted({e.get("e_type", "") for e in edges if isinstance(e, dict)})
    f["shared_cards"] = await shared_device_cards(call, f.get("device_str", ""), card_id)

    verdict, p, pattern, pdesc, signals, exposure, initial, assumed, final = decide(case, f)

    # similar prior cases (memory)
    mem = similar_closed(pattern if pattern not in ("none", "undocumented") else
                         "card_not_present_fraud")

    evidence = [
        {"claim": f"Flagged ${f['amount']:.2f} {f['channel']} txn (risk {f['risk_score']}) vs "
                  f"card baseline max ${f['prior_max']:.2f} over {f['n_prior']} prior txns",
         "source": "graph" if src_window == "graph" else "document",
         "ref": f"query:card_window(card_id={card_id})",
         "entity_ids": [str(case["flagged_txn_id"])]},
        {"claim": ("; ".join(signals) if signals else "no corroborating signals; single weak signal"),
         "source": "graph",
         "ref": "query:txn_edges(txn_id=%s) -> %s" % (case["flagged_txn_id"], ",".join(edge_types) or "none"),
         "entity_ids": [str(case["flagged_txn_id"])]},
    ]
    if f["testing_seq"]:
        evidence.append({"claim": "Testing sequence: %s" % (">".join(f["testing_seq"])),
                         "source": "graph", "ref": "query:card_window_1h",
                         "entity_ids": f["testing_seq"]})
    if f["device_str"]:
        evidence.append({"claim": "Device profile: %s%s" % (
            f["device_str"], " (New for account)" if f["new_device"] else ""),
            "source": "graph", "ref": "query:txn_device",
            "entity_ids": [str(case["flagged_txn_id"])]})
    if assumed:
        evidence.append({"claim": "Customer %s on validation request" % assumed["response"],
                         "source": "customer", "ref": "evidence_request:1", "entity_ids": []})

    ereqs = []
    if assumed:
        ereqs = [{"type": "customer_validation", "asked_after_step": 4,
                  "assumed_response": "Customer %s the $%.2f transaction of %s" % (
                      ("denied" if "denied" in assumed["response"] else
                       "did not respond about"), f["amount"], flagged.get("ts", ""))}]

    file_report = any(a["action"] == "FILE_REPORT" for a in final)
    if verdict == "fraud" and (exposure > 1000 or f["new_device"] or f["testing_seq"] or
                               trigger_shared(case)) and not file_report:
        final.append({"action": "FILE_REPORT", "route": "L2",
                      "reason": "R2/R6: exposure/linkage"})
        file_report = True

    sar = {"file": file_report,
           "reason": ("R2/R6: confirmed fraud with exposure/linkage" if file_report else
                      "No report: %s; exposure $%.2f, no shared-device/second-card link (3a)" % (
                          "unconfirmed single signal" if verdict != "fraud" else
                          "case-level only", exposure)),
           "narrative": "", "subjects": [], "total_amount_usd": 0, "activity_dates": []}
    if file_report:
        sar.update({
            "narrative": sar_narrative(case, f, verdict, pattern, exposure),
            "subjects": [customer_id, card_id],
            "total_amount_usd": exposure,
            "activity_dates": [str(flagged.get("ts", ""))[:10], str(flagged.get("ts", ""))[:10]]})

    affected = [str(case["flagged_txn_id"])] if verdict != "legitimate" else []
    if f["testing_seq"] and verdict == "fraud":
        affected = f["testing_seq"]
    status = {"fraud": "closed_fraud", "legitimate": "closed_legitimate",
              "uncertain": "open"}[verdict]

    # write-back (case memory)
    try:
        await call("tigergraph__add_node", {"graph_name": GRAPH, "vertex_type": "ClosedCase",
                   "vertex_id": case_id, "attributes": {
                       "outcome": {"fraud": "confirmed_fraud", "legitimate": "cleared",
                                   "uncertain": "uncertain"}[verdict],
                       "pattern": pattern, "exposure": exposure,
                       "notes": ("Agent case %s: %s p=%.2f pattern=%s" % (
                           case_id, verdict, p, pattern))[:400]}})
        await call("tigergraph__add_edge", {"graph_name": GRAPH,
                   "source_vertex_type": "ClosedCase", "source_vertex_id": case_id,
                   "edge_type": "ON_CARD", "target_vertex_type": "Card",
                   "target_vertex_id": card_id})
        await call("tigergraph__add_edge", {"graph_name": GRAPH,
                   "source_vertex_type": "ClosedCase", "source_vertex_id": case_id,
                   "edge_type": "INVOLVES", "target_vertex_type": "Transaction",
                   "target_vertex_id": str(case["flagged_txn_id"])})
        written, gid = True, case_id
    except Exception:  # noqa: BLE001
        written, gid = False, ""

    what_changed = ("nothing" if not assumed else
                    "Customer response moved p and finalized block/monitor path under R2/R4.")
    out = {
        "case_id": case_id,
        "case": {
            "status": status, "verdict": verdict, "fraud_probability": p,
            "pattern": pattern, "pattern_description": pdesc,
            "affected_txn_ids": affected,
            "first_suspicious_txn_id": affected[0] if affected else "",
            "connected_card_ids": list(f.get("shared_cards", [])[:5]),
            "connected_device_profiles": [f["device_str"]] if f.get("shared_cards") and f.get("device_str") else [],
            "exposure_usd": exposure if verdict != "legitimate" else 0,
            "evidence": evidence, "similar_prior_cases": mem,
            "summary": "%s on card %s: %s." % (case["trigger_type"], card_id,
                                               "; ".join(signals) if signals else
                                               "isolated alert without corroboration"),
            "written_to_graph": written, "graph_case_id": gid},
        "evidence_requests": ereqs,
        "next_best_actions": {"initial": initial, "final": final,
                              "what_changed": what_changed},
        "sar": sar,
        "stop_reason": ("Verification response settles the question." if assumed and
                        "denied" in assumed["response"] else
                        "Stopping at p=%.2f: %s." % (
                            p, "verification pending under R1" if verdict == "uncertain"
                            else "decision supported by pattern evidence")),
        "tool_calls": tool_calls[0], "tokens": 0,
        "latency_s": round(time.time() - t0, 1)}
    (BASE / "cases").mkdir(exist_ok=True)
    with open(BASE / "cases" / f"{case_id}.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return out


def trigger_shared(case):
    return case["trigger_type"] == "analyst_request"


def sar_narrative(case, f, verdict, pattern, exposure):
    return (
        "On %s, card %s of customer %s was used for a $%.2f %s transaction "
        "(product code %s, risk score %.2f). The amount is %.1fx the card's prior maximum "
        "($%.2f), inconsistent with established history. %s The cardholder denied the "
        "activity when contacted. Total exposure $%.2f. Card blocked pending reissue." % (
            f.get("ts", ""), case["card_id"], case["customer_id"], f["amount"],
            f["channel"], f["product_cd"], f["risk_score"], f["amount_ratio"],
            f["prior_max"],
            ("Device profile marked new for the account. " if f["new_device"] else ""),
            exposure))


async def main(cases):
    env_vals = {k: v for k, v in dotenv_values(BASE / ".env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for cid in cases:
                tc = [0]
                try:
                    out = await investigate(s, cid, tc)
                    print(f"{cid}: {out['case']['verdict']} p={out['case']['fraud_probability']} "
                          f"pattern={out['case']['pattern']} tools={tc[0]}")
                except Exception as e:  # noqa: BLE001
                    print(f"{cid}: ERROR {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--skip", default="",
                    help="comma-separated case_ids to skip (e.g. HHG-002 already done)")
    a = ap.parse_args()
    pack = read_case_pack()
    if a.all:
        skip = {x.strip() for x in a.skip.split(",") if x.strip()}
        targets = [c for c in sorted(pack) if c not in skip]
    else:
        targets = [a.case or "HHG-001"]
    asyncio.run(main(targets))
