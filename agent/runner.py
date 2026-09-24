"""Per-case investigation runner."""
import argparse
import asyncio
import json
import time
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from . import BASE, GRAPH
from .evidence import card_history_from_csv, read_case_pack, similar_closed
from .features import build_features
from .policy import decide
from .retrieval import graph_txn_edges, graph_window, mcp_call, shared_device_cards
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
