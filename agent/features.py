"""Feature builder."""
from .evidence import fnum, identity_for, parse_ts

# ---------------------------------------------------------------- features

def build_features(case, window, flagged):
    f = {}
    amt = fnum(flagged.get("TransactionAmt"))
    prior = [t for t in window if str(t.get("TransactionID")) != str(case["flagged_txn_id"])]
    pamts = [fnum(t.get("TransactionAmt")) for t in prior]
    f["amount"] = amt
    f["prior_max"] = max(pamts) if pamts else 0
    f["prior_mean"] = sum(pamts) / len(pamts) if pamts else 0
    f["amount_ratio"] = amt / f["prior_max"] if f["prior_max"] else 99.0
    f["n_prior"] = len(prior)
    f["channel"] = flagged.get("channel", "")
    f["product_cd"] = flagged.get("ProductCD", "")
    f["risk_score"] = fnum(flagged.get("risk_score"))
    f["addr1"] = flagged.get("addr1", "")

    fts = parse_ts(flagged.get("ts", ""))
    # burst: txns within Â±48h of flagged
    burst = []
    for t in window:
        tts = parse_ts(t.get("ts", ""))
        if tts and fts and abs((tts - fts).total_seconds()) <= 48 * 3600:
            burst.append(t)
    f["burst_48h"] = len(burst)

    # R5 card testing: 3+ online auths <$5 within 1h + a larger purchase after
    online_sorted = sorted(
        [t for t in window if t.get("channel") == "online" and parse_ts(t.get("ts", ""))],
        key=lambda t: t["ts"])
    testing_seq = []
    for i, t in enumerate(online_sorted):
        if fnum(t.get("TransactionAmt")) >= 5:
            continue
        t0 = parse_ts(t["ts"])
        group = [t]
        for u in online_sorted[i + 1:]:
            if (parse_ts(u["ts"]) - t0).total_seconds() <= 3600 and fnum(u.get("TransactionAmt")) < 5:
                group.append(u)
            elif (parse_ts(u["ts"]) - t0).total_seconds() > 3600:
                break
        if len(group) >= 3:
            after = [u for u in online_sorted
                     if parse_ts(u["ts"]) > parse_ts(group[-1]["ts"])
                     and fnum(u.get("TransactionAmt")) >= 5]
            if after:
                testing_seq = [g["TransactionID"] for g in group] + [after[0]["TransactionID"]]
                break
    f["testing_seq"] = testing_seq

    # product novelty: flagged ProductCD never used before?
    prior_prods = {t.get("ProductCD") for t in prior}
    f["novel_product"] = f["product_cd"] not in prior_prods if prior_prods else False

    # region novelty
    prior_regions = {t.get("addr1") for t in prior if t.get("addr1")}
    f["novel_region"] = bool(f["addr1"]) and f["addr1"] not in prior_regions

    # recurring-match count (R7): prior txns same channel, amount within Â±2%
    f["recur_same"] = sum(
        1 for t in prior
        if (lambda pa: pa and abs(pa - amt) / max(amt, 1) <= 0.02
            and t.get("channel") == f["channel"])(fnum(t.get("TransactionAmt"))))

    # device / identity
    idr = identity_for(case["flagged_txn_id"])
    f["has_device"] = bool(idr.get("DeviceInfo"))
    f["new_device"] = (idr.get("id_15", "") or "").strip().lower() == "new"
    _proxy_raw = (idr.get("id_23", "") or "").strip().lower()
    f["proxy"] = any(k in _proxy_raw for k in ("anonymous", "hidden", "proxy"))
    f["device_str"] = (f"{idr.get('DeviceInfo', '')}|{idr.get('id_30', '')}|"
                       f"{idr.get('id_31', '')}|{idr.get('id_33', '')}") if idr.get("DeviceInfo") else ""
    return f, burst

