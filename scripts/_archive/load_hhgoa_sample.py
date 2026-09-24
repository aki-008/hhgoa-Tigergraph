"""Load HHG sample windows into HHGOA_Fraud via TigerGraph MCP (batched).
Sample: 3 cases (HHG-002, HHG-003, HHG-014) -> customers, cards, all their
transactions + device/email/region + 7 closed cases.
Run: python load_hhgoa_sample.py
"""
import asyncio
import csv
from collections import defaultdict
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

BASE = Path(__file__).parent
GRAPH = "HHGOA_Fraud"
CASES = ["HHG-002", "HHG-003", "HHG-014"]


def fnum(x, default=0.0):
    try:
        return float(x) if str(x).strip() not in ("", "None") else default
    except (ValueError, TypeError):
        return default


def load_inputs():
    # case rows
    want = {}
    with open(BASE / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["case_id"] in CASES:
                want[row["case_id"]] = row
    customers = {r["customer_id"]: r["card_id"] for r in want.values()}
    cust_txns = defaultdict(list)
    flagged = {r["flagged_txn_id"] for r in want.values()}

    # single pass over transactions (large file)
    with open(BASE / "data" / "transactions.csv", newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            cid = row.get("customer_id", "")
            if cid in customers:
                cust_txns[cid].append(row)
    for cid in cust_txns:
        cust_txns[cid].sort(key=lambda r: r.get("ts", ""))

    # identity map for our txn ids only
    needed_txn = set()
    for rows in cust_txns.values():
        for r in rows:
            needed_txn.add(r["TransactionID"])
    ident = {}
    with open(BASE / "data" / "identity.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("TransactionID") in needed_txn:
                ident[row["TransactionID"]] = row

    # closed cases: 5 fraud (prefer card_not_present) + 2 cleared
    fraud, cleared = [], []
    with open(BASE / "data" / "closed_cases_history.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["outcome"] == "confirmed_fraud" and len(fraud) < 5:
                fraud.append(row)
            elif row["outcome"] == "cleared" and len(cleared) < 2:
                cleared.append(row)
            if len(fraud) == 5 and len(cleared) == 2:
                break
    return want, customers, cust_txns, ident, fraud + cleared


def build_batches(want, customers, cust_txns, ident, closed):
    nodes = defaultdict(dict)  # (type) -> {id: attrs}
    edges = []  # (from_type, from_id, edge, to_type, to_id)

    def add_node(vt, vid, attrs):
        if vid is None or str(vid) == "":
            return
        d = nodes[vt].setdefault(str(vid), {})
        d.update({k: v for k, v in attrs.items() if v is not None})

    for cid, card_id in customers.items():
        add_node("Customer", cid, {})
        add_node("Card", card_id, {"customer_id": cid})
        edges.append(("Customer", cid, "OWNS", "Card", card_id))
        prev = None
        for r in cust_txns.get(cid, []):
            tid = r["TransactionID"]
            add_node("Transaction", tid, {
                "amount": fnum(r.get("TransactionAmt")),
                "ts": r.get("ts", ""),
                "channel": r.get("channel", ""),
                "product_cd": r.get("ProductCD", ""),
                "risk_score": fnum(r.get("risk_score")),
                "addr1": r.get("addr1", ""),
                "card_id": card_id,
            })
            edges.append(("Card", card_id, "MADE", "Transaction", tid))
            if r.get("P_emaildomain"):
                add_node("EmailDomain", r["P_emaildomain"], {})
                edges.append(("Transaction", tid, "PURCHASER_EMAIL", "EmailDomain", r["P_emaildomain"]))
            if r.get("addr1"):
                add_node("BillingRegion", r["addr1"], {})
                edges.append(("Transaction", tid, "BILLED_IN", "BillingRegion", r["addr1"]))
            idr = ident.get(tid)
            if idr and idr.get("DeviceInfo"):
                dev = f"{idr.get('DeviceInfo','')}|{idr.get('id_30','')}|{idr.get('id_31','')}"
                add_node("DeviceProfile", dev, {"device_info": idr.get("DeviceInfo", "")})
                edges.append(("Transaction", tid, "FROM_DEVICE", "DeviceProfile", dev))
            if prev:
                edges.append(("Transaction", prev, "NEXT", "Transaction", tid))
            prev = tid

    for cc in closed:
        add_node("ClosedCase", cc["case_id"], {
            "outcome": cc["outcome"], "pattern": cc["pattern"],
            "exposure": fnum(cc.get("exposure_usd")),
            "notes": (cc.get("analyst_notes", "") or "")[:800],
        })
        # link to card vertex if that card exists in sample
        for card_id in customers.values():
            if cc.get("card_id") == card_id:
                edges.append(("ClosedCase", cc["case_id"], "ON_CARD", "Card", card_id))
        for tid in (cc.get("txn_ids", "") or "").split("|")[:3]:
            if tid and tid in {r["TransactionID"] for rows in cust_txns.values() for r in rows}:
                edges.append(("ClosedCase", cc["case_id"], "INVOLVES", "Transaction", tid))
    return nodes, edges


async def main():
    want, customers, cust_txns, ident, closed = load_inputs()
    n_txn = sum(len(v) for v in cust_txns.values())
    print(f"cases={list(want)} customers={list(customers)} txns={n_txn} closed={len(closed)}")
    nodes, edges = build_batches(want, customers, cust_txns, ident, closed)
    print("nodes:", {k: len(v) for k, v in nodes.items()}, "edges:", len(edges))

    env_vals = {k: v for k, v in dotenv_values("./.env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args):
                res = await s.call_tool(name, arguments=args)
                txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                ok = '"success": true' in txt
                if not ok:
                    print(f"FAIL {name}: {txt[:500]}")
                return ok, txt

            # vertices per type (batched)
            for vt, mapping in nodes.items():
                verts = [{"id": vid, **attrs} for vid, attrs in mapping.items()]
                for i in range(0, len(verts), 100):
                    await call("tigergraph__add_nodes", {
                        "graph_name": GRAPH, "vertex_type": vt,
                        "vertex_id": "id", "vertices": verts[i:i + 100]})
            print("vertices loaded.")

            # edges per type (batched if supported, else single)
            by_type = defaultdict(list)
            for e in edges:
                by_type[(e[2], e[0], e[3])].append(e)
            for (etype, fvt, tvt), lst in by_type.items():
                batch = [{"source_id": fid, "target_id": tid,
                          "source_type": fvt, "target_type": tvt}
                         for (ft, fid, et, tt, tid) in lst]
                # try batch tool (source_id/target_id per edge)
                ok, _ = await call("tigergraph__add_edges", {
                    "graph_name": GRAPH, "edge_type": etype, "edges": batch})
                if not ok:  # fallback single
                    for (ft, fid, et, tt, tid) in lst:
                        await call("tigergraph__add_edge", {
                            "graph_name": GRAPH, "source_vertex_type": ft,
                            "source_vertex_id": fid, "edge_type": et,
                            "target_vertex_type": tt, "target_vertex_id": tid})
            print("edges loaded. DONE.")


if __name__ == "__main__":
    asyncio.run(main())
