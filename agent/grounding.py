"""Grounding retrieval for GraphRAG briefs (spec required component #4).

Current backend: TF-IDF over closed-case notes + fraud-policy chunks
(zero extra infra, runs offline). Interface is embedding-ready: swap
build_index() for a vector store (TigerGraph vector attribute + an
embedding model) without touching callers.

Corpus:
  - 5,565 closed-case analyst notes (labeled memory)
  - Fraud-policy rules R0-R10 + pattern typologies (parsed from data/README.md)
"""
import csv
import re
from pathlib import Path

from . import BASE

_POLICY_CACHE = None
_CASE_INDEX = None


def policy_chunks():
    """Parse R-rules + pattern sections out of data/README.md."""
    global _POLICY_CACHE
    if _POLICY_CACHE is not None:
        return _POLICY_CACHE
    text = (BASE / "data" / "README.md").read_text(encoding="utf-8")
    chunks = []
    # rules R1. - R10. (also R0/R3a/R3b prose captured with neighbors)
    for m in re.finditer(r"\*\*(R\d+)\.(.*?)(?=\n\*\*R\d+\.|\n### |\Z)",
                         text, re.S):
        chunks.append({"id": m.group(1), "kind": "policy",
                       "text": re.sub(r"\s+", " ", m.group(0).strip())[:600]})
    # five known patterns section
    pm = re.search(r"## The five known fraud patterns(.*?)(?=\n## |\Z)", text, re.S)
    if pm:
        for i, part in enumerate(re.split(r"\n\*\*", pm.group(1).strip())):
            part = re.sub(r"\s+", " ", part.strip())[:600]
            if len(part) > 80:
                chunks.append({"id": f"P{i}", "kind": "pattern", "text": part})
    _POLICY_CACHE = chunks
    return chunks


def _case_rows(limit=5565):
    rows = []
    with open(BASE / "data" / "closed_cases_history.csv", newline="",
              encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
            if len(rows) >= limit:
                break
    return rows


def build_index():
    """TF-IDF index over case notes + policy chunks. Returns (vectorizer, matrix, docs)."""
    global _CASE_INDEX
    if _CASE_INDEX is not None:
        return _CASE_INDEX
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = []
    for r in _case_rows():
        docs.append({"id": r["case_id"], "kind": "closed_case",
                     "label": f"{r['outcome']}/{r['pattern']}",
                     "text": f"{r['pattern']} {r['outcome']} exposure {r['exposure_usd']} "
                             f"{r['analyst_notes']}"})
    docs.extend(policy_chunks())
    vec = TfidfVectorizer(stop_words="english", max_features=20000)
    mat = vec.fit_transform([d["text"] for d in docs])
    _CASE_INDEX = (vec, mat, docs)
    return _CASE_INDEX


def retrieve(query, k_cases=3, k_policy=2):
    """Top-k grounded context for a brief. Returns dict(cases, policy)."""
    vec, mat, docs = build_index()
    from sklearn.metrics.pairwise import cosine_similarity
    q = vec.transform([query])
    scores = cosine_similarity(q, mat)[0]
    ranked = sorted(range(len(docs)), key=lambda i: -scores[i])
    cases, policy = [], []
    for i in ranked:
        if docs[i]["kind"] == "closed_case" and len(cases) < k_cases:
            cases.append({**docs[i], "score": round(float(scores[i]), 3)})
        elif docs[i]["kind"] in ("policy", "pattern") and len(policy) < k_policy:
            policy.append({**docs[i], "score": round(float(scores[i]), 3)})
        if len(cases) >= k_cases and len(policy) >= k_policy:
            break
    return {"cases": cases, "policy": policy}


def brief_query_text(brief):
    """Compact query string from an evidence brief."""
    fl = brief.get("flagged", {})
    sig = brief.get("signals", {})
    bits = [brief.get("trigger", ""), fl.get("channel", ""), fl.get("product_cd", ""),
            f"amount {fl.get('amount')}",
            "new device" if sig.get("new_device") else "",
            "proxy" if sig.get("proxy") else "",
            "burst" if (sig.get("burst_48h") or 0) >= 2 else "",
            "recurring dispute" if (sig.get("recurring_matches") or 0) >= 3 else ""]
    return " ".join(b for b in bits if b)
