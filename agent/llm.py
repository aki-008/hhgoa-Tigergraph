"""LLM provider layer + evidence briefs + validation."""
import json
import os
import urllib.request
from dotenv import dotenv_values
from . import BASE
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


def _record_usage(cfg, prompt_tokens, completion_tokens):
    u = cfg.setdefault("usage_total", {"prompt": 0, "completion": 0})
    u["prompt"] += prompt_tokens or 0
    u["completion"] += completion_tokens or 0
    cfg["last_usage"] = {"prompt": prompt_tokens or 0,
                         "completion": completion_tokens or 0}


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
        from groq import Groq as _Groq
        client = _Groq(api_key=cfg["api_key"])
        completion = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2, max_completion_tokens=max_tokens, top_p=0.95,
            stream=True)
        chunks = []
        usage = None
        for chunk in completion:
            chunks.append(chunk.choices[0].delta.content or "")
            if getattr(chunk, "usage", None):
                usage = chunk.usage
        if usage is not None:
            _record_usage(cfg, getattr(usage, "prompt_tokens", 0),
                          getattr(usage, "completion_tokens", 0))
        return "".join(chunks)
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
        from groq import Groq as _Groq
        client = _Groq(api_key=cfg["api_key"])
        completion = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2, max_completion_tokens=max_tokens, top_p=0.95,
            stream=False)
        usage = getattr(completion, "usage", None)
        if usage is not None:
            _record_usage(cfg, getattr(usage, "prompt_tokens", 0),
                          getattr(usage, "completion_tokens", 0))
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
    brief = {
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
    # GraphRAG grounding: relevant past cases + policy excerpts, not raw rows
    try:
        from .grounding import brief_query_text, retrieve
        g = retrieve(brief_query_text(brief))
        brief["grounded_memory"] = [
            {"case": c["id"], "label": c["label"], "note": c["text"][:300]}
            for c in g["cases"]]
        brief["grounded_policy"] = [
            {"rule": p["id"], "text": p["text"][:300]} for p in g["policy"]]
    except Exception:  # noqa: BLE001 - grounding is additive, never fatal
        brief["grounded_memory"] = []
        brief["grounded_policy"] = []
    return brief


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


