"""Deterministic R1-R10 policy engine."""
from .evidence import fnum

# ---------------------------------------------------------------- policy engine

def decide(case, f):
    """Returns (verdict, p, pattern, pattern_desc, evidence_notes, initial, assumed, final)."""
    trigger = case["trigger_type"]
    signals = []
    p = 0.20
    if f["amount_ratio"] >= 2.0 and f["n_prior"] >= 5:
        p += 0.15
        signals.append(f"amount {f['amount']:.2f} is {f['amount_ratio']:.1f}x prior max")
    if 2 <= f["burst_48h"] <= 4 and f["channel"] == "online":
        p += 0.12
        signals.append(f"burst of {f['burst_48h']} within 48h")
    if f["testing_seq"]:
        p += 0.30
        signals.append(f"testing sequence {f['testing_seq']}")
    if f["new_device"]:
        p += 0.12
        signals.append("new device for account")
    if f["proxy"]:
        p += 0.08
        signals.append("proxy/anonymizer")
    if f["novel_region"] and f["channel"] == "in_person":
        p += 0.12
        signals.append(f"novel billing region {f['addr1']}")
    if f["novel_product"]:
        p += 0.05
        signals.append(f"first-time product code {f['product_cd']}")
    if f["risk_score"] >= 0.85:
        p += 0.08
    if trigger == "customer_report":
        p += 0.25
        signals.append("cardholder denies the charge")
    if f.get("shared_cards"):
        p += 0.15
        signals.append("shared device with %d other card(s): %s" % (
            len(f["shared_cards"]), ",".join(f["shared_cards"][:3])))
    if not signals and trigger == "risk_score":
        p = 0.15  # no corroboration at all: lean legitimate
    p = round(min(max(p, 0.05), 0.95), 2)

    if f["testing_seq"]:
        pattern = "card_testing"
    elif f["new_device"] and f["channel"] == "online":
        pattern = "card_not_present_new_device"
    elif f["novel_region"] and f["channel"] == "in_person":
        pattern = "out_of_region_use"
    elif f["channel"] == "online" and (f["amount_ratio"] >= 1.5 or 2 <= f["burst_48h"] <= 4):
        pattern = "card_not_present_fraud"
    elif trigger == "analyst_request":
        pattern = "undocumented"
    elif p >= 0.5:
        pattern = "card_not_present_fraud"
    else:
        pattern = "none"
    pdesc = ("Shared device/region activity across cards under analyst review; described as "
             "coordinated cross-card use pending linkage evidence."
             if pattern == "undocumented" else "")

    exposure = round(f["amount"], 2)

    # R7: disputed charge matching own recurring pattern -> no block
    recur = f.get("recur_same", 0)
    if trigger == "customer_report" and recur >= 3:
        verdict, p = "uncertain", 0.30
        pattern, pdesc = "none", ""
        initial = [
            {"action": "CREATE_CASE", "route": "auto",
             "reason": "R7: disputed charge matches recurring pattern (%dx ~$%.2f)" % (recur, f["amount"])},
            {"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R7"},
            {"action": "WARN_CUSTOMER", "route": "auto",
             "reason": "R7: recurring-charge reminder, do not block"}]
        final = initial
        assumed = None
        signals.append("matches recurring own pattern (%dx)" % recur)
        r7 = (verdict, p, pattern, pdesc, exposure, initial, assumed, final)
    else:
        r7 = None
    if r7 is None:
        if trigger == "customer_report":
            verdict, p = ("fraud", max(p, 0.80)) if p >= 0.55 else ("uncertain", p)
        elif p >= 0.70:
            verdict = "fraud"
        elif p <= 0.30:
            verdict = "legitimate"
        else:
            verdict = "uncertain"

        # ---- actions
        initial, assumed, final = [], None, []
        if trigger == "customer_report":
            initial = [
                {"action": "BLOCK_CARD", "route": "L1" if exposure <= 2500 else "L2",
                 "reason": "R2: customer denied; exposure $%.2f" % exposure},
                {"action": "CREATE_CASE", "route": "auto", "reason": "R2"}]
            if exposure > 1000 or f["new_device"]:
                initial.append({"action": "FILE_REPORT", "route": "L2",
                                "reason": "R2: exposure >$1,000 or new-device link"})
            final = initial
        elif f["testing_seq"]:
            initial = [{"action": "VERIFY_WITH_CUSTOMER", "route": "auto",
                        "reason": "R1: confirm before block"},
                       {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R5: testing sequence"}]
            assumed = {"type": "customer_validation", "response": "denied"}
            final = [
                {"action": "DECLINE_TRANSACTION", "route": "L1", "reason": "R5: testing sequence"},
                {"action": "BLOCK_CARD", "route": "L1" if exposure <= 2500 else "L2",
                 "reason": "R2+R5: denied; purchase cleared" if exposure > 100 else "R2: denied"},
                {"action": "CREATE_CASE", "route": "auto", "reason": "R2"}]
            p = min(0.95, p + 0.15)
            verdict = "fraud"
        elif p < 0.70:
            # R1 weak signal -> verify; assume no reply -> R4 monitor/decline
            initial = [
                {"action": "VERIFY_WITH_CUSTOMER", "route": "auto",
                 "reason": "R1: single signal, p=%.2f < 0.70" % p},
                {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1"},
                {"action": "MONITOR_CARD", "route": "auto", "reason": "R4: watch pending"}]
            assumed = {"type": "customer_validation", "response": "no reply within 24h"}
            final = [
                {"action": "MONITOR_CARD", "route": "auto", "reason": "R4: no reply"},
                {"action": "DECLINE_TRANSACTION", "route": "L1", "reason": "R4: pending auths"}]
            if exposure > 500:
                final.append({"action": "ESCALATE_TO_ANALYST", "route": "auto",
                              "reason": "R4/R8: exposure $%.2f > $500" % exposure})
        else:
            initial = [{"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R1"},
                       {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1"}]
            assumed = {"type": "customer_validation", "response": "denied"}
            final = [{"action": "BLOCK_CARD", "route": "L1" if exposure <= 2500 else "L2",
                      "reason": "R2: denied"},
                     {"action": "CREATE_CASE", "route": "auto", "reason": "R2"}]
            verdict = "fraud"
            p = min(0.95, p + 0.10)

        # R8: uncertain + high exposure -> escalate
        if verdict == "uncertain" and exposure > 500 and not any(
                a["action"] == "ESCALATE_TO_ANALYST" for a in final):
            final.append({"action": "ESCALATE_TO_ANALYST", "route": "auto",
                          "reason": "R8: uncertain with exposure $%.2f" % exposure})
    # R6: shared device across cards -> report + monitor connected
    if f.get("shared_cards") and verdict in ("fraud", "uncertain"):
        if not any(a["action"] == "FILE_REPORT" for a in final):
            final.append({"action": "FILE_REPORT", "route": "L2",
                          "reason": "R6: shared device across %d card(s)" % len(f["shared_cards"])})
        final.append({"action": "MONITOR_CONNECTED_CARDS", "route": "auto",
                      "reason": "R6: monitor %s" % ",".join(f["shared_cards"][:3])})
    if r7 is not None:  # R7 path computed above; restore it
        verdict, p, pattern, pdesc, exposure, initial, assumed, final = r7
    return verdict, p, pattern, pdesc, signals, exposure, initial, assumed, final

