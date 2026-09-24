"""Trigger intake dispatcher (spec item 1).

Each trigger kind builds its own initial evidence plan plus opening
assumptions. Deterministic; no model calls.
"""
from . import GRAPH

TRIGGER_KINDS = ("risk_score", "customer_report", "analyst_request")


def intake_plan(case):
    """Returns (plan_steps, opening_notes).

    plan_steps: ordered retrieval actions the investigator must run.
    opening_notes: assumptions established by the trigger itself.
    """
    kind = case.get("trigger_type", "risk_score")
    card_id = case.get("card_id", "")
    txn_id = str(case.get("flagged_txn_id", ""))
    base = [
        {"step": "card_window", "ref": f"query:card_window(card_id={card_id})"},
        {"step": "txn_detail", "ref": f"query:txn(txn_id={txn_id})"},
        {"step": "txn_links", "ref": f"query:txn_edges(txn_id={txn_id})"},
        {"step": "memory", "ref": "query:case_memory"},
    ]
    if kind == "risk_score":
        plan = ([{"step": "triage",
                  "ref": f"trigger:risk_score={case.get('risk_score', '?')}"}] + base)
        notes = ["Model score is a reason to look, never a verdict."]
    elif kind == "customer_report":
        plan = ([{"step": "denial_record",
                  "ref": f"trigger:customer_report({case.get('customer_id', '')})"}] + base)
        notes = ["Cardholder denies the charge: R2/R7 suspected; "
                 "recurrence check decides between them."]
    elif kind == "analyst_request":
        plan = ([{"step": "ring_sweep",
                  "ref": f"query:shared_device(txn_id={txn_id})"}] + base)
        notes = ["Analyst tip alleges a cross-card device ring: "
                 "shared-origin sweep runs before single-card analysis."]
    else:
        plan, notes = base, [f"Unknown trigger {kind!r}; default plan."]
    return plan, notes


def describe(case):
    return (f"{case.get('trigger_type')} trigger for txn {case.get('flagged_txn_id')} "
            f"on card {case.get('card_id')} ({case.get('trigger_text', '')[:120]})")
