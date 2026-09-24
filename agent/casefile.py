"""Staged fraud case object (spec item 4).

States: open -> investigating -> pending_evidence -> actioned
        -> closed_fraud | closed_legitimate | escalated
Every transition is timestamped and logged for the audit trail.
"""
from datetime import datetime, timezone

STATES = ("open", "investigating", "pending_evidence", "actioned",
          "closed_fraud", "closed_legitimate", "escalated")

TERMINAL = {"closed_fraud", "closed_legitimate", "escalated"}

_ALLOWED = {
    "open": ("investigating",),
    "investigating": ("pending_evidence", "actioned"),
    "pending_evidence": ("investigating", "actioned"),
    "actioned": ("closed_fraud", "closed_legitimate", "escalated", "pending_evidence",
                 "open"),
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CaseFile:
    def __init__(self, case_id, trigger):
        self.case_id = case_id
        self.trigger = trigger
        self.state = "open"
        self.risk = 0.0
        self.pattern = "none"
        self.evidence = []      # [{claim, source, ref, entity_ids, step}]
        self.decisions = []     # [{at, decision, reason, rule}]
        self.actions = []       # [{action, route, status, at}]
        self.transitions = [{"at": _now(), "from": None, "to": "open",
                             "reason": f"trigger: {trigger}"}]

    def add_evidence(self, claim, source, ref, entity_ids=None):
        self.evidence.append({"claim": claim, "source": source, "ref": ref,
                              "entity_ids": list(entity_ids or [])})

    def record(self, decision, reason, rule=""):
        self.decisions.append({"at": _now(), "decision": decision,
                               "reason": reason, "rule": rule})

    def set_risk(self, risk, pattern="none"):
        self.risk = round(float(risk), 2)
        self.pattern = pattern

    def transition(self, to, reason=""):
        if to not in _ALLOWED.get(self.state, ()):
            raise ValueError(f"illegal transition {self.state} -> {to}")
        self.transitions.append({"at": _now(), "from": self.state,
                                 "to": to, "reason": reason})
        self.state = to
        return self.state

    def summary(self):
        return {"case_id": self.case_id, "state": self.state, "risk": self.risk,
                "pattern": self.pattern, "n_evidence": len(self.evidence),
                "n_decisions": len(self.decisions)}
