"""LLM fraud investigator (Option B): evidence brief -> local LLM -> policy guardrails.
Works with any OpenAI-compatible endpoint (Ollama / LM Studio / vLLM).

Config (env or flags):
  LLM_BASE_URL  default http://localhost:11434/v1
  LLM_MODEL     default qwen3:32b  (e.g. qwen3:32b, gemma3:27b, qwen2.5:32b)
  LLM_API_KEY   default 'ollama' (local servers usually ignore it)
  LLM_TIMEOUT_S default 300

Usage:
  python scripts/llm_investigate.py --brief-only --case HHG-014   # no model needed
  python scripts/llm_investigate.py --case HHG-014                # full LLM run
  python scripts/llm_investigate.py --pilot                       # HHG-014,010,003
Writes cases/<case_id>.llm.json (rule-based files untouched).
"""
import argparse
import asyncio
import csv
import json
import os
import time
import urllib.request
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

import investigate as INV  # reuse: evidence builders + policy engine + writers

BASE = Path(__file__).parent.parent
PILOT = ["HHG-014", "HHG-010", "HHG-003"]
PATTERNS = ["card_testing", "card_not_present_fraud", "card_not_present_new_device",
            "out_of_region_use", "account_takeover", "undocumented", "none"]

SYSTEM = """You are a bank card-fraud investigator. Given an evidence brief, return a verdict.
Rules: risk_score is a reason to look, never a verdict. One unusual purchase alone (probability <0.70) means VERIFY first, never block (R1). Customer denial of a charge matching their own recurring pattern (recurring_matches >= 3 in the brief: same amount/channel) is pattern NONE with low probability, never undocumented and never fraud (R7). Three or more sub-$5 online authorizations within an hour followed by a larger purchase is card testing (R5). Use undocumented ONLY for coordinated or repeated abuse fitting none of the known patterns, with a 2-3 sentence description. Half of all alerts are legitimate; do not over-call fraud. Reason in at most 6 short sentences, then output the JSON object as your final text.
Return ONLY this JSON (no markdown, no commentary):
{"verdict": "fraud|legitimate|uncertain", "fraud_probability": 0.0-1.0,
 "pattern": "<one of: card_testing, card_not_present_fraud, card_not_present_new_device, out_of_region_use, account_takeover, undocumented, none>",
 "pattern_description": "<required 2-3 sentences if pattern is undocumented, else empty>",
 "key_signals": ["<each decisive observation, max 4, each under 20 words>"],
 "needs_report": true}"""


NARR_SYSTEM = ("You write bank SAR narratives. Return ONLY JSON: "
                '{"narrative": "<6-12 sentences: who, what, when, where, how, why suspicious>"}')


def call_llm(cfg, system, user, max_tokens=400):
    try:
        return chat(cfg, system, user, max_tokens=max_tokens)
    except Exception:  # noqa: BLE001 - streaming hiccup, try single-shot
        return chat_once(cfg, system, user, max_tokens=max_tokens)


def llm_config(args):
    env = dotenv_values(BASE / ".env")
    groq_key = env.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY") or ""
    if groq_key:
        return {
            "provider": "groq",
            "model": ((args.model or env.get("GROQ_MODEL") or os.getenv("GROQ_MODEL") or "")
                      or "qwen/qwen3.8-27b"),
            "api_key": groq_key,
            "timeout": args.timeout,
        }
    return {
        "provider": "openai_compat",
        "base_url": (args.base_url or env.get("LLM_BASE_URL") or os.getenv("LLM_BASE_URL")
                     or "http://localhost:11434/v1").rstrip("/"),
        "model": args.model or env.get("LLM_MODEL") or os.getenv("LLM_MODEL") or "qwen3:32b",
        "api_key": env.get("LLM_API_KEY") or os.getenv("LLM_API_KEY") or "ollama",
        "timeout": args.timeout,
    }


def _groq_client(cfg):
    from groq import Groq
    return Groq(api_key=cfg["api_key"])


def chat(cfg, system, user, max_tokens=400):
    """Streaming chat. Returns full text."""
    if cfg.get("provider") == "groq":
        client = _groq_client(cfg)
        completion = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2, max_completion_tokens=max_tokens, top_p=0.95,
            stream=True)
        return "".join(chunk.choices[0].delta.content or "" for chunk in completion)
    body = json.dumps({"model": cfg["model"],
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "temperature": 0.2, "stream": True, "enable_thinking": False,
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    chunks, think = [], []
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        for line in r:
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0].get("delta", {})
                chunks.append(delta.get("content") or "")
                think.append(delta.get("reasoning_content") or "")
            except (ValueError, KeyError):
                continue
    text = "".join(chunks)
    # Qwen3-thinking servers stream reasoning separately; fall back to it
    return text if text.strip() else "".join(think)


def chat_once(cfg, system, user, max_tokens=400):
    """Non-streaming fallback."""
    if cfg.get("provider") == "groq":
        client = _groq_client(cfg)
        completion = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2, max_completion_tokens=max_tokens, top_p=0.95,
            stream=False)
        return completion.choices[0].message.content or ""
    body = json.dumps({"model": cfg["model"],
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "temperature": 0.2, "stream": False, "enable_thinking": False,
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + cfg["api_key"]})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        msg = json.load(r)["choices"][0]["message"]
    text = msg.get("content", "") or ""
    return text if text.strip() else (msg.get("reasoning_content", "") or "")


def build_brief(case, window, flagged, f, mem):
    prior = [t for t in window if str(t.get("TransactionID")) != str(case["flagged_txn_id"])]
    recent = sorted(prior, key=lambda t: str(t.get("ts", "")))[-8:]
    return {
        "case_id": case["case_id"], "trigger": case["trigger_type"],
        "trigger_text": case["trigger_text"],
        "flagged": {"txn_id": str(case["flagged_txn_id"]), "amount": f["amount"],
                    "ts": flagged.get("ts", ""), "channel": f["channel"],
                    "product_cd": f["product_cd"], "risk_score": f["risk_score"],
                    "region": f["addr1"] or "none"},
        "baseline": {"n_prior": f["n_prior"], "prior_max": round(f["prior_max"], 2),
                     "prior_mean": round(f["prior_mean"], 2),
                     "amount_ratio": round(f["amount_ratio"], 2)},
        "recent_history": [{"txn": t.get("TransactionID"), "amt": t.get("TransactionAmt"),
                            "ts": t.get("ts", ""), "prod": t.get("ProductCD", "")}
                           for t in recent],
        "signals": {"burst_48h": f["burst_48h"], "testing_seq": f["testing_seq"],
                    "novel_product": f["novel_product"], "novel_region": f["novel_region"],
                    "has_device": f["has_device"], "new_device": f["new_device"],
                    "proxy": f["proxy"], "device": f["device_str"] or "none",
                    "recurring_matches": f.get("recur_same", 0),
                    "shared_device_cards": f.get("shared_cards", [])},
        "similar_prior_cases": mem,
    }


def validate_llm(case, llm, txns):
    """Returns (llm_fixed, problems). Never throws."""
    problems = []
    llm = dict(llm)
    if llm.get("verdict") not in ("fraud", "legitimate", "uncertain"):
        problems.append("bad verdict; defaulted uncertain")
        llm["verdict"] = "uncertain"
    try:
        llm["fraud_probability"] = min(max(float(llm.get("fraud_probability", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        problems.append("bad probability; defaulted 0.5")
        llm["fraud_probability"] = 0.5
    if llm.get("pattern") not in PATTERNS:
        problems.append("bad pattern; defaulted none")
        llm["pattern"] = "none"
    if llm["pattern"] == "undocumented" and not llm.get("pattern_description"):
        problems.append("undocumented without description")
        llm["pattern_description"] = "Coordinated activity not matching known patterns."
    if llm.get("verdict") == "legitimate" and llm.get("needs_report"):
        llm["needs_report"] = False
    # every cited txn must exist
    for t in llm.get("cited_txn_ids", []) or []:
        if str(t) not in txns:
            problems.append(f"cited txn {t} not in dataset")
    return llm, problems


async def run_case(s, cfg, case_id, brief_only=False):
    t0 = time.time()
    tc = [0]

    async def call(name, args):
        tc[0] += 1
        return await INV.mcp_call(s, name, args)

    case = INV.read_case_pack()[case_id]
    card_id, customer_id = case["card_id"], case["customer_id"]
    try:
        window = await INV.graph_window(call, card_id)
        if not window:
            raise ValueError("empty")
    except Exception:  # noqa: BLE001
        window = INV.card_history_from_csv(customer_id)
    flagged = next((t for t in window
                    if str(t.get("TransactionID")) == str(case["flagged_txn_id"])), None)
    if flagged is None:
        flagged = next((t for t in INV.card_history_from_csv(customer_id)
                        if str(t.get("TransactionID")) == str(case["flagged_txn_id"])), None)
    f, _ = INV.build_features(case, window, flagged)
    f["shared_cards"] = await INV.shared_device_cards(call, f.get("device_str", ""), card_id)
    mem = INV.similar_closed("card_not_present_fraud")
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
            INV.card_history_from_csv(customer_id)} | {str(case["flagged_txn_id"])}
    llm, problems = validate_llm(case, parsed, txns)

    # policy guardrails (deterministic): actions always from the engine
    verdict, p, pattern, pdesc, signals, exposure, initial, assumed, final = \
        INV.decide(case, f)
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
        _, _, _, _, _, _, initial, assumed, final = INV.decide(case, f)
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
    pack = INV.read_case_pack()
    targets = PILOT if a.pilot else ([c for c in sorted(pack)] if a.all else [a.case or "HHG-014"])
    asyncio.run(main(targets, llm_config(a), a.brief_only))
