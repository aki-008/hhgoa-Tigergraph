"""Simulated execution layer + deterministic mock responders (spec items 6+8).

- AUTO actions "execute" immediately (logged with timestamp).
- L1/L2 actions are recorded as pending_approval with the required approver.
- Mock customer/analyst replies are deterministic functions of the evidence
  (scripted, reproducible for evaluators) — never random, never an LLM.
"""
from datetime import datetime, timezone

AUTO_ACTIONS = {"ALLOW_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS",
                "WARN_CUSTOMER", "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH",
                "GENERATE_REPORT", "CREATE_CASE", "ESCALATE_TO_ANALYST",
                "CLOSE_NO_FRAUD"}
L1_ACTIONS = {"DECLINE_TRANSACTION"}  # + BLOCK_CARD when exposure <= 2500
L2_ACTIONS = {"BLOCK_ALL_CARDS", "FILE_REPORT"}  # + BLOCK_CARD when exposure > 2500


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def approver_for(action, route):
    if route == "auto":
        return None
    return "team_lead" if route == "L1" else "fraud_manager"


def execute(action, route, casefile, tracer, exposure=0.0):
    """Simulate execution. Returns the action record."""
    rec = {"action": action, "route": route, "at": _now()}
    if route == "auto" and action in AUTO_ACTIONS:
        rec["status"] = "executed"
        rec["detail"] = f"simulated: {action} completed"
    else:
        rec["status"] = "pending_approval"
        rec["approver"] = approver_for(action, route)
        rec["detail"] = f"waiting on {rec['approver']}"
    casefile.actions.append(rec)
    tracer.log("action", f"{action} -> {rec['status']}",
               {"action": action, "route": route, "status": rec["status"]})
    return rec


# ---------------------------------------------------------------- responders

def mock_customer_validation(case, features):
    """Deterministic cardholder reply.

    Denies when the trigger is a report or corroborating fraud signals exist;
    confirms when the charge fits a quiet baseline; otherwise stays silent.
    """
    if case.get("trigger_type") == "customer_report":
        return "denied"
    if features.get("testing_seq"):
        return "denied"
    if features.get("new_device") and (features.get("proxy") or
                                       features.get("amount_ratio", 0) >= 2.0):
        return "denied"
    if (features.get("amount_ratio", 99) <= 1.2 and not features.get("new_device")
            and not features.get("novel_region")):
        return "confirmed"
    return "no_reply"


def mock_step_up_auth(customer_reply):
    """Step-up outcome follows the customer reply deterministically."""
    if customer_reply == "confirmed":
        return "passed"
    if customer_reply == "denied":
        return "failed"
    return "expired"


def mock_analyst_info(case, features):
    """Analyst desk reply: shares whatever linkage the graph actually shows."""
    shared = features.get("shared_cards", [])
    if shared:
        return (f"Desk confirms device seen on {len(shared)} other card(s): "
                + ",".join(shared[:5]))
    if features.get("proxy"):
        return "Desk notes anonymizer IP; no cross-card link in current sample."
    return "Desk reports no additional linkage in current sample."
