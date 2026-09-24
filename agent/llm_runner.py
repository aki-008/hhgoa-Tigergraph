"""LLM investigation runner."""
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
from .llm import (NARR_SYSTEM, SYSTEM, build_brief, call_llm, llm_config,
                 validate_llm)
from .policy import decide
from .retrieval import (graph_window, mcp_call, shared_device_cards)

PILOT = ["HHG-014", "HHG-010", "HHG-003"]
async def run_case(s, cfg, case_id, brief_only=False):
    t0 = time.time()
    tc = [0]

    async def call(name, args):
        tc[0] += 1
        return await mcp_call(s, name, args)

    case = read_case_pack()[case_id]
    card_id, customer_id = case["card_id"], case["customer_id"]
    try:
        window = await graph_window(call, card_id)
        if not window:
            raise ValueError("empty")
    except Exception:  # noqa: BLE001
        window = card_history_from_csv(customer_id)
    flagged = next((t for t in window
                    if str(t.get("TransactionID")) == str(case["flagged_txn_id"])), None)
    if flagged is None:
        flagged = next((t for t in card_history_from_csv(customer_id)
                        if str(t.get("TransactionID")) == str(case["flagged_txn_id"])), None)
    f, _ = build_features(case, window, flagged)
    f["shared_cards"] = await shared_device_cards(call, f.get("device_str", ""), card_id)
    mem = similar_closed("card_not_present_fraud")
    brief = build_brief(case, window, flagged, f, mem)

    if brief_only:
        out = BASE / "cases" / f"{case_id}.brief.json"
        out.write_text(json.dumps(brief, indent=2), encoding="utf-8")
        print(f"{case_id}: brief written ({len(json.dumps(brief))} chars, tools={tc[0]})")
        return {"case_id": case_id, "brief": brief}

    raw = call_llm(cfg, SYSTEM, json.dumps(brief), max_tokens=1100)
    try:
        parsed = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except ValueError:
        parsed = {"verdict": "uncertain", "fraud_probability": 0.5, "pattern": "none",
                  "pattern_description": "", "key_signals": [raw[:300]], "needs_report": False}
    txns = {r["TransactionID"] for r in
            card_history_from_csv(customer_id)} | {str(case["flagged_txn_id"])}
    llm, problems = validate_llm(case, parsed, txns)

    # policy guardrails (deterministic): actions always from the engine
    verdict, p, pattern, pdesc, signals, exposure, initial, assumed, final = \
        decide(case, f)
    # adopt LLM judgment where it passes validation, keep engine for actions
    verdict, p, pattern = llm["verdict"], llm["fraud_probability"], llm["pattern"]
    if llm["pattern"] == "undocumented":
        pdesc = llm.get("pattern_description", "")
    # R2 uplift: denial + corroboration scored as fraud even if LLM hedges
    if (case["trigger_type"] == "customer_report" and f.get("recur_same", 0) < 3
            and verdict != "fraud" and (
                f.get("new_device") or exposure > 1000 or f.get("amount_ratio", 0) >= 1.5
                or 2 <= f.get("burst_48h", 0) <= 4)):
        verdict, p = "fraud", max(p, 0.80)
        signals.append("customer denial with corroborating evidence (policy R2 uplift)")
    for sig in llm.get("key_signals", [])[:6]:
        if sig and sig not in signals:
            signals.append(str(sig)[:200])

    # rebuild actions consistent with LLM verdict (engine rules, R1/R7/R10 enforced)
    if verdict == "legitimate" and not (
            case["trigger_type"] == "customer_report" and f.get("recur_same", 0) >= 3):
        initial = [{"action": "CLOSE_NO_FRAUD", "route": "auto", "reason": "LLM: legitimate"}]
        final, ereqs = initial, []
    elif case["trigger_type"] == "customer_report" and f.get("recur_same", 0) >= 3:
        # R7 overrides: recurring dispute -> case + verify + warn, never block
        initial = [
            {"action": "CREATE_CASE", "route": "auto",
             "reason": "R7: recurring pattern (%dx)" % f["recur_same"]},
            {"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R7"},
            {"action": "WARN_CUSTOMER", "route": "auto", "reason": "R7: no block"}]
        final, ereqs = initial, []
    else:
        _, _, _, _, _, _, initial, assumed, final = decide(case, f)
        if (case["trigger_type"] == "customer_report" and verdict != "fraud"
                and any(a["action"] == "BLOCK_CARD" for a in final)):
            # Uncorroborated denial: single weak signal -> verify before block (R1),
            # not the R2 block path. Keeps verdict and actions consistent.
            initial = [
                {"action": "VERIFY_WITH_CUSTOMER", "route": "auto",
                 "reason": "R1: uncorroborated denial, confirm before block"},
                {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1"},
                {"action": "MONITOR_CARD", "route": "auto", "reason": "R4: watch pending"}]
            final = initial
            assumed = {"type": "customer_validation", "response": "no reply within 24h"}
            signals.append("denial uncorroborated: verify-first per R1, no block")
        ereqs = []
        if assumed:
            ereqs = [{"type": "customer_validation", "asked_after_step": 4,
                      "assumed_response": "Customer %s" % assumed["response"]}]
    file_report = any(a["action"] == "FILE_REPORT" for a in final)
    if llm.get("needs_report") and (verdict == "fraud" and
                                    (exposure > 1000 or f.get("shared_cards") or
                                     f.get("new_device"))):
        if not file_report:
            final.append({"action": "FILE_REPORT", "route": "L2", "reason": "LLM+R2/R6"})
            file_report = True
    narrative = ""
    if file_report:
        try:
            nraw = call_llm(cfg, NARR_SYSTEM, json.dumps({
                "case_id": case_id, "verdict": verdict, "pattern": pattern,
                "exposure": exposure, "flagged": brief["flagged"],
                "signals": signals[:5]}), max_tokens=1500)
            narrative = json.loads(nraw[nraw.index("{"):nraw.rindex("}") + 1]).get(
                "narrative", "")
        except Exception:  # noqa: BLE001 - narrative optional
            narrative = ""
    sar = {"file": file_report,
           "reason": "LLM investigation with policy guardrails" if file_report
                     else "No report per policy 3a",
           "narrative": narrative if file_report else "",
           "subjects": [customer_id, card_id] if file_report else [],
           "total_amount_usd": exposure if file_report else 0,
           "activity_dates": ([str(flagged.get("ts", ""))[:10]] * 2) if file_report else []}
    affected = [str(case["flagged_txn_id"])] if verdict != "legitimate" else []
    out = {
        "case_id": case_id,
        "case": {
            "status": {"fraud": "closed_fraud", "legitimate": "closed_legitimate",
                       "uncertain": "open"}[verdict],
            "verdict": verdict, "fraud_probability": p, "pattern": pattern,
            "pattern_description": pdesc if pattern == "undocumented" else "",
            "affected_txn_ids": affected,
            "first_suspicious_txn_id": affected[0] if affected else "",
            "connected_card_ids": list(f.get("shared_cards", [])[:5]),
            "connected_device_profiles": ([f["device_str"]] if f.get("shared_cards")
                                           and f.get("device_str") else []),
            "exposure_usd": exposure if verdict != "legitimate" else 0,
            "evidence": [
                {"claim": "Flagged $%.2f %s txn (risk %s) vs baseline max $%.2f over %d priors" % (
                    f["amount"], f["channel"], f["risk_score"], f["prior_max"], f["n_prior"]),
                 "source": "graph", "ref": "query:card_window(card_id=%s)" % card_id,
                 "entity_ids": [str(case["flagged_txn_id"])]},
                *[{"claim": s2, "source": "graph", "ref": "llm:evidence_brief",
                    "entity_ids": [str(case["flagged_txn_id"])]} for s2 in signals[:5]]],
            "similar_prior_cases": mem,
            "summary": "LLM verdict %s p=%.2f pattern=%s." % (verdict, p, pattern),
            "written_to_graph": False, "graph_case_id": ""},
        "evidence_requests": ereqs,
        "next_best_actions": {"initial": initial, "final": final,
                              "what_changed": "LLM judgment + policy guardrails" if ereqs else "nothing"},
        "sar": sar,
        "stop_reason": "LLM verdict with policy validation%s." % (
            "; validation notes: %s" % "; ".join(problems) if problems else ""),
        "tool_calls": tc[0], "tokens": 0, "latency_s": round(time.time() - t0, 1)}
    (BASE / "cases").mkdir(exist_ok=True)
    with open(BASE / "cases" / f"{case_id}.llm.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"{case_id}: LLM {verdict} p={p} pattern={pattern} "
          f"problems={problems or 'none'} tools={tc[0]}")
    return out


async def main(cases, cfg, brief_only):
    from dotenv import dotenv_values as _dv  # local import to keep top tidy
    env_vals = {k: v for k, v in _dv(BASE / ".env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for cid in cases:
                try:
                    await run_case(s, cfg, cid, brief_only=brief_only)
                except Exception as e:  # noqa: BLE001
                    print(f"{cid}: ERROR {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--brief-only", action="store_true")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    pack = read_case_pack()
    targets = PILOT if a.pilot else ([c for c in sorted(pack)] if a.all else [a.case or "HHG-014"])
    asyncio.run(main(targets, llm_config(a), a.brief_only))
