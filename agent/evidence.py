"""CSV/file evidence helpers."""
import csv
from datetime import datetime

from . import BASE

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

