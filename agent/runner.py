"""Per-case investigation runner."""
import argparse
import asyncio
import json
import time
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from . import BASE, GRAPH
from .casefile import CaseFile
from .evidence import card_history_from_csv, read_case_pack
from .execution import execute as exec_action
from .execution import mock_analyst_info, mock_customer_validation, mock_step_up_auth
from .features import build_features
from .memory import ring_walk, similar_cases_graph
from .policy import decide, sar_narrative, trigger_shared
from .retrieval import graph_txn_edges, graph_window, mcp_call, shared_device_cards
from .trace import Tracer
from .triggers import describe as describe_trigger
from .triggers import intake_plan
# ---------------------------------------------------------------- main per case

async def investigate(s, case_id, tool_calls, live_trace=True, out_dir="cases"):
    """Staged flow: trigger -> investigate -> evidence -> assess ->
    more-evidence -> act -> explain -> memorize. Output schema unchanged."""
    t0 = time.time()
    case = read_case_pack()[case_id]
    card_id, customer_id = case["card_id"], case["customer_id"]
    tracer = Tracer(case_id, live=live_trace, out_dir=out_dir)
    cf = CaseFile(case_id, case.get("trigger_type", ""))

    async def call(name, args):
        tool_calls[0] += 1
        tracer.log("retrieve", f"tool:{name}", {"tool": name})
        return await mcp_call(s, name, args)

    # 1. trigger: intake plan per trigger kind
    plan, notes = intake_plan(case)
    tracer.log("trigger", describe_trigger(case),
               {"plan": [p["step"] for p in plan], "notes": notes})
    cf.transition("investigating", "intake plan ready")

    # 2-3. investigate + gather: graph window, fallback CSV
    try:
        window = await graph_window(call, card_id)
        src_window = "graph"
        if not window:
            raise ValueError("empty")
    except Exception:  # noqa: BLE001
        window = card_history_from_csv(customer_id)
        src_window = "csv"
    tracer.log("retrieve", f"card_window: {len(window)} txns ({src_window})",
               {"n": len(window), "src": src_window})
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
    try:
        f["shared_cards"], _ring_txns = await ring_walk(call, f.get("device_str", ""), card_id)
        tracer.log("traverse", f"ring walk: {len(f["shared_cards"])} other cards",
                   {"cards": f["shared_cards"]})
    except Exception:  # noqa: BLE001
        f["shared_cards"] = await shared_device_cards(call, f.get("device_str", ""), card_id)
    tracer.log("retrieve", "txn links + shared-device sweep",
               {"edge_types": edge_types, "shared_cards": f["shared_cards"]})

    # 4. assess
    verdict, p, pattern, pdesc, signals, exposure, initial, assumed, final = decide(case, f)
    if (verdict != "fraud"
            and any(a["action"] == "BLOCK_CARD" for a in final)):
        # Uncorroborated denial: single weak signal -> verify before block (R1),
        # not the R2 block path. (R7 recurring cases never carry BLOCK here.)
        initial = [
            {"action": "VERIFY_WITH_CUSTOMER", "route": "auto",
             "reason": "R1: uncorroborated denial, confirm before block"},
            {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1"},
            {"action": "MONITOR_CARD", "route": "auto", "reason": "R4: watch pending"}]
        final = initial
        assumed = {"type": "customer_validation", "response": "no reply within 24h"}
        signals.append("denial uncorroborated: verify-first per R1, no block")
        cf_note = "downgrade: R1 verify-first (was R2 block)"
    else:
        cf_note = None
    cf.set_risk(p, pattern)
    cf.record(f"assess: {verdict} p={p} pattern={pattern}",
              "; ".join(signals) or "single weak signal", "features")
    tracer.log("assess", f"{verdict} p={p} pattern={pattern}",
               {"signals": signals, "exposure": exposure})

    # similar prior cases (memory)
    mem = await similar_cases_graph(
        call, pattern if pattern not in ("none", "undocumented") else
        "card_not_present_fraud")
    tracer.log("memory", f"{len(mem)} similar prior cases", {"cases": mem})

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
    for e in evidence:
        cf.add_evidence(e["claim"], e["source"], e["ref"], e["entity_ids"])

    # 5. more evidence if needed: mock responders (deterministic, simulated)
    ereqs = []
    reply = None
    if assumed and assumed.get("type") == "customer_validation":
        cf.transition("pending_evidence", "verification requested")
        reply = mock_customer_validation(case, f)
        tracer.log("evidence_request", f"customer_validation -> {reply}",
                   {"assumed": assumed.get("response")})
        evidence.append({"claim": f"Customer {reply} the transaction on validation request",
                         "source": "customer", "ref": "evidence_request:1", "entity_ids": []})
        cf.add_evidence(evidence[-1]["claim"], "customer", "evidence_request:1", [])
        ereqs = [{"type": "customer_validation", "asked_after_step": 4,
                  "assumed_response": "Customer %s the $%.2f transaction of %s (mock responder)" % (
                      reply, f["amount"], flagged.get("ts", ""))}]
        if any(a["action"] == "STEP_UP_AUTH" for a in initial):
            su = mock_step_up_auth(reply)
            tracer.log("evidence_request", f"step_up_auth -> {su}", {})
            evidence.append({"claim": f"Step-up authentication {su}",
                             "source": "customer", "ref": "evidence_request:2", "entity_ids": []})
        if reply == "confirmed" and verdict != "legitimate":
            # R3: confirmation settles it as legitimate
            verdict, p = "legitimate", min(p, 0.15)
            cf.set_risk(p, pattern)
            cf.record("R3: customer confirmed", "verification reply", "R3")
            final = [{"action": "CLOSE_NO_FRAUD", "route": "auto", "reason": "R3: confirmed"},
                     {"action": "GENERATE_REPORT", "route": "auto", "reason": "R3: record"}]
            initial = final
        cf.transition("investigating", f"evidence received: {reply}")
    if case.get("trigger_type") == "analyst_request":
        info = mock_analyst_info(case, f)
        tracer.log("evidence_request", f"analyst_info -> {info[:120]}", {})
        evidence.append({"claim": info, "source": "analyst",
                         "ref": "evidence_request:analyst", "entity_ids": []})
        cf.add_evidence(info, "analyst", "evidence_request:analyst", [])

    # 6. act: simulated execution with approval routing
    cf.transition("actioned", "final actions selected")
    for a in final:
        exec_action(a["action"], a["route"], cf, tracer, exposure)
    for a in initial:
        if a not in final:
            cf.record(f"initially considered {a['action']}", a["reason"], "superseded")

    file_report = any(a["action"] == "FILE_REPORT" for a in final)
    if verdict == "fraud" and (exposure > 1000 or f["new_device"] or f["testing_seq"] or
                               trigger_shared(case)) and not file_report:
        final.append({"action": "FILE_REPORT", "route": "L2",
                      "reason": "R2/R6: exposure/linkage"})
        exec_action("FILE_REPORT", "L2", cf, tracer, exposure)
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
    terminal = {"fraud": "closed_fraud", "legitimate": "closed_legitimate"}.get(verdict, "open")
    if any(a["action"] == "ESCALATE_TO_ANALYST" for a in final) and verdict == "uncertain":
        terminal = "escalated"
    status = terminal
    cf.transition(terminal, f"verdict={verdict}")

    # 8. memorize: write-back (case memory)
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
    tracer.log("memorize", f"case write-back written={written}", {"graph_case_id": gid})

    # 7. explain
    what_changed = ("nothing" if not ereqs else
                    f"Evidence ({reply}) finalized the path under R2/R3/R4.")
    cf.record(f"explain: {what_changed}", f"stop: {verdict} p={p}", "summary")
    tracer.log("done", f"{verdict} p={p}", tracer.totals())
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
        "stop_reason": ("Verification response settles the question." if reply in ("denied", "confirmed") else
                        "Stopping at p=%.2f: %s." % (
                            p, "verification pending under R1" if verdict == "uncertain"
                            else "decision supported by pattern evidence")),
        "tool_calls": tool_calls[0], "tokens": 0,
        "latency_s": round(time.time() - t0, 1)}
    (BASE / out_dir).mkdir(parents=True, exist_ok=True)
    with open(BASE / out_dir / f"{case_id}.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return out


async def main(cases, out_dir="cases"):
    env_vals = {k: v for k, v in dotenv_values(BASE / ".env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for cid in cases:
                tc = [0]
                try:
                    out = await investigate(s, cid, tc, out_dir=out_dir)
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
    ap.add_argument("--out-dir", default="cases",
                    help="output directory for answer JSON + traces (e.g. cases/run_20260924)")
    a = ap.parse_args()
    pack = read_case_pack()
    if a.all:
        skip = {x.strip() for x in a.skip.split(",") if x.strip()}
        targets = [c for c in sorted(pack) if c not in skip]
    else:
        targets = [a.case or "HHG-001"]
    asyncio.run(main(targets, out_dir=a.out_dir))
