"""Stage-1 load: all 20 case windows (±60d) + ALL closed cases into HHGOA_Fraud.
Idempotent (upserts). Run: python scripts/load_stage1.py
"""
import asyncio
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

BASE = Path(__file__).parent.parent  # repo root (scripts/ lives in scripts/)
GRAPH = "HHGOA_Fraud"
WINDOW_DAYS = 60
NODE_BATCH = 50
EDGE_BATCH = 100
THROTTLE_S = 1.0
MAX_RETRIES = 4


def fnum(x, default=0.0):
    try:
        return float(x) if str(x).strip() not in ("", "None") else default
    except (ValueError, TypeError):
        return default


def parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def load_inputs():
    want = {}  # case_id -> row
    with open(BASE / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            opened = parse_ts(row["opened_at"])
            want[row["case_id"]] = {**row, "_opened": opened}
    customers = {r["customer_id"]: r["card_id"] for r in want.values()}

    cust_txns = defaultdict(list)
    with open(BASE / "data" / "transactions.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row.get("customer_id", "")
            if cid not in customers:
                continue
            # window: ±60d around ANY case opened_at for this customer, or flagged txn
            keep = row["TransactionID"] in {r["flagged_txn_id"] for r in want.values()
                                            if r["customer_id"] == cid}
            if not keep:
                ts = parse_ts(row.get("ts", ""))
                if ts:
                    for r in want.values():
                        if r["customer_id"] == cid and r["_opened"] and \
                                abs((ts - r["_opened"]).days) <= WINDOW_DAYS:
                            keep = True
                            break
            if keep:
                cust_txns[cid].append(row)
    for cid in cust_txns:
        cust_txns[cid].sort(key=lambda r: r.get("ts", ""))

    needed = {r["TransactionID"] for rows in cust_txns.values() for r in rows}
    ident = {}
    with open(BASE / "data" / "identity.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("TransactionID") in needed:
                ident[row["TransactionID"]] = row

    closed = []
    with open(BASE / "data" / "closed_cases_history.csv", newline="", encoding="utf-8") as f:
        closed = list(csv.DictReader(f))
    return want, customers, cust_txns, ident, closed


def build_batches(want, customers, cust_txns, ident, closed):
    nodes = defaultdict(dict)
    edges = []

    def add_node(vt, vid, attrs):
        if vid is None or str(vid) == "":
            return
        nodes[vt].setdefault(str(vid), {}).update(
            {k: v for k, v in attrs.items() if v is not None})

    for cid, card_id in customers.items():
        add_node("Customer", cid, {})
        add_node("Card", card_id, {"customer_id": cid})
        edges.append(("Customer", cid, "OWNS", "Card", card_id))
        prev = None
        for r in cust_txns.get(cid, []):
            tid = r["TransactionID"]
            add_node("Transaction", tid, {
                "amount": fnum(r.get("TransactionAmt")),
                "ts": r.get("ts", ""), "channel": r.get("channel", ""),
                "product_cd": r.get("ProductCD", ""),
                "risk_score": fnum(r.get("risk_score")),
                "addr1": r.get("addr1", ""), "card_id": card_id})
            edges.append(("Card", card_id, "MADE", "Transaction", tid))
            if r.get("P_emaildomain"):
                add_node("EmailDomain", r["P_emaildomain"], {})
                edges.append(("Transaction", tid, "PURCHASER_EMAIL",
                              "EmailDomain", r["P_emaildomain"]))
            if r.get("addr1"):
                add_node("BillingRegion", r["addr1"], {})
                edges.append(("Transaction", tid, "BILLED_IN", "BillingRegion", r["addr1"]))
            idr = ident.get(tid)
            if idr and idr.get("DeviceInfo"):
                dev = f"{idr.get('DeviceInfo', '')}|{idr.get('id_30', '')}|{idr.get('id_31', '')}"
                add_node("DeviceProfile", dev, {"device_info": idr.get("DeviceInfo", "")})
                edges.append(("Transaction", tid, "FROM_DEVICE", "DeviceProfile", dev))
            if prev:
                edges.append(("Transaction", prev, "NEXT", "Transaction", tid))
            prev = tid

    sample_txn_ids = {r["TransactionID"] for rows in cust_txns.values() for r in rows}
    sample_cards = set(customers.values())
    for cc in closed:
        add_node("ClosedCase", cc["case_id"], {
            "outcome": cc["outcome"], "pattern": cc["pattern"],
            "exposure": fnum(cc.get("exposure_usd")),
            "notes": (cc.get("analyst_notes", "") or "")[:800]})
        if cc.get("card_id") in sample_cards:
            edges.append(("ClosedCase", cc["case_id"], "ON_CARD", "Card", cc["card_id"]))
        for tid in (cc.get("txn_ids", "") or "").split("|")[:3]:
            if tid and tid in sample_txn_ids:
                edges.append(("ClosedCase", cc["case_id"], "INVOLVES", "Transaction", tid))
    return nodes, edges


async def main():
    want, customers, cust_txns, ident, closed = load_inputs()
    n_txn = sum(len(v) for v in cust_txns.values())
    print(f"cases={len(want)} customers={len(customers)} window_txns={n_txn} closed={len(closed)}")
    nodes, edges = build_batches(want, customers, cust_txns, ident, closed)
    print("nodes:", {k: len(v) for k, v in nodes.items()}, "edges:", len(edges))

    env_vals = {k: v for k, v in dotenv_values(BASE / ".env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args, retries=MAX_RETRIES):
                for attempt in range(retries):
                    try:
                        res = await s.call_tool(name, arguments=args)
                    except Exception as e:  # noqa: BLE001 - transport hiccup
                        print(f"RETRY {name} attempt {attempt + 1}: {type(e).__name__}")
                        await asyncio.sleep(THROTTLE_S * (attempt + 1))
                        continue
                    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                    ok = '"success": true' in txt
                    if ok:
                        await asyncio.sleep(THROTTLE_S)
                        return True
                    # server 500s are transient on free tier; back off and retry
                    if "500" in txt or "502" in txt:
                        print(f"RETRY {name} attempt {attempt + 1} (server busy)")
                        await asyncio.sleep(THROTTLE_S * (attempt + 2))
                        continue
                    print(f"FAIL {name}: {txt[:400]}")
                    return False
                print(f"FAIL {name}: exhausted retries")
                return False

            fails = 0
            for vt, mapping in nodes.items():
                verts = [{"id": vid, **attrs} for vid, attrs in mapping.items()]
                for i in range(0, len(verts), NODE_BATCH):
                    if not await call("tigergraph__add_nodes", {
                            "graph_name": GRAPH, "vertex_type": vt,
                            "vertex_id": "id", "vertices": verts[i:i + NODE_BATCH]}):
                        fails += 1
            print(f"vertices loaded, batch fails={fails}")

            by_type = defaultdict(list)
            for e in edges:
                by_type[(e[2], e[0], e[3])].append(e)
            for (etype, fvt, tvt), lst in by_type.items():
                batch = [{"source_id": fid, "target_id": tid,
                          "source_type": fvt, "target_type": tvt}
                         for (ft, fid, et, tt, tid) in lst]
                for i in range(0, len(batch), EDGE_BATCH):
                    if not await call("tigergraph__add_edges", {
                            "graph_name": GRAPH, "edge_type": etype,
                            "edges": batch[i:i + EDGE_BATCH]}):
                        fails += 1
            print(f"edges loaded, total fails={fails}. DONE.")


if __name__ == "__main__":
    asyncio.run(main())
