"""Build per-case neighborhood graph JSON for the dashboard explorer.
Nodes: card, flagged txn + nearby window (<=40 txns), device/email/region
nodes, other cards sharing the device. Edges typed. Offline (CSV-based).
Run: python scripts/build_graph_data.py
Output: dashboard/public/cases/HHG-xxx.graph.json
"""
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
DST = BASE / "dashboard" / "public" / "cases"
MAX_TXNS = 40


def parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def main():
    pack = {}
    with open(BASE / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pack[r["case_id"]] = r
    # customer txns
    cust_txns = defaultdict(list)
    with open(BASE / "data" / "transactions.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cust_txns[r.get("customer_id", "")].append(r)
    # identity by txn
    ident = {}
    with open(BASE / "data" / "identity.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ident[r.get("TransactionID")] = r
    # device -> customers (cross-card sharing, online txns only)
    dev_cards = defaultdict(set)
    dev_label = {}
    with open(BASE / "data" / "transactions.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            tid = r.get("TransactionID")
            idr = ident.get(tid)
            if idr and idr.get("DeviceInfo"):
                dev = f"{idr.get('DeviceInfo', '')}|{idr.get('id_30', '')}"
                dev_cards[dev].add(r.get("customer_id", ""))
                dev_label[dev] = idr.get("DeviceInfo", "")[:50]

    DST.mkdir(parents=True, exist_ok=True)
    for cid, case in sorted(pack.items()):
        txns = sorted(cust_txns.get(case["customer_id"], []),
                      key=lambda r: r.get("ts", ""))
        fts = parse_ts(next((t.get("ts", "") for t in txns
                             if t["TransactionID"] == case["flagged_txn_id"]), ""))
        if fts:
            txns_sorted = sorted(txns, key=lambda t: abs(
                ((parse_ts(t.get("ts", "")) or fts) - fts).total_seconds()))
        else:
            txns_sorted = txns
        keep = []
        for t in txns_sorted:
            if t["TransactionID"] == case["flagged_txn_id"] or len(keep) >= MAX_TXNS:
                continue
            keep.append(t)
        flagged = next((t for t in txns
                        if t["TransactionID"] == case["flagged_txn_id"]), None)
        window = ([flagged] if flagged else []) + keep

        nodes = [{"id": case["card_id"], "kind": "card",
                  "label": case["card_id"]}]
        edges = []
        attr_seen = {}
        for t in window:
            tid = t["TransactionID"]
            is_flag = tid == case["flagged_txn_id"]
            nodes.append({"id": tid, "kind": "txn", "flagged": is_flag,
                          "label": f"${t.get('TransactionAmt', '?')}",
                          "sub": f"{t.get('ts', '')} {t.get('channel', '')}"})
            edges.append({"from": case["card_id"], "to": tid, "kind": "MADE"})
            idr = ident.get(tid, {})
            if idr.get("DeviceInfo"):
                dev = f"{idr.get('DeviceInfo', '')}|{idr.get('id_30', '')}"
                if dev not in attr_seen:
                    attr_seen[dev] = f"D{len(attr_seen)}"
                    others = sorted(c for c in dev_cards.get(dev, set())
                                    if c != case["customer_id"])
                    nodes.append({"id": attr_seen[dev], "kind": "device",
                                  "label": dev_label.get(dev, dev[:30]),
                                  "shared": len(others),
                                  "others": others[:5]})
                edges.append({"from": tid, "to": attr_seen[dev], "kind": "FROM_DEVICE"})
            if t.get("P_emaildomain"):
                em = "E:" + t["P_emaildomain"]
                if em not in attr_seen:
                    attr_seen[em] = em
                    nodes.append({"id": em, "kind": "email",
                                  "label": t["P_emaildomain"]})
                edges.append({"from": tid, "to": attr_seen[em], "kind": "EMAIL"})
            if t.get("addr1"):
                rg = "R:" + t["addr1"]
                if rg not in attr_seen:
                    attr_seen[rg] = rg
                    nodes.append({"id": rg, "kind": "region",
                                  "label": "region " + t["addr1"]})
                edges.append({"from": tid, "to": attr_seen[rg], "kind": "BILLED_IN"})
        (DST / f"{cid}.graph.json").write_text(
            json.dumps({"case_id": cid, "card": case["card_id"],
                        "flagged": case["flagged_txn_id"],
                        "nodes": nodes, "edges": edges}), encoding="utf-8")
    print(f"wrote {len(pack)} graph snapshots -> {DST}")


if __name__ == "__main__":
    main()
