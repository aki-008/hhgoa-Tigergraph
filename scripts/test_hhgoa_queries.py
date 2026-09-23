"""Test fraud queries on HHGOA_Fraud live graph via MCP.
Run: python test_hhgoa_queries.py [--case HHG-002]
"""
import argparse
import asyncio
import json
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

GRAPH = "HHGOA_Fraud"
CASE_CARD = {"HHG-002": "C11891-K1", "HHG-003": "C08623-K2", "HHG-014": "C13487-K1"}
CASE_TXN = {"HHG-002": "3478782", "HHG-003": "3530164", "HHG-014": "3478561"}


async def call(s, name, args):
    res = await s.call_tool(name, arguments=args)
    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
    # extract JSON block
    try:
        js = json.loads(txt.split("```json")[1].split("```")[0])
    except (IndexError, ValueError):
        js = {"raw": txt[:800]}
    return js


async def main(case_id):
    env_vals = {k: v for k, v in dotenv_values("./.env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            card = CASE_CARD[case_id]
            txn = CASE_TXN[case_id]

            print(f"--- {case_id}: card={card} flagged_txn={txn} ---")
            c = await call(s, "tigergraph__get_vertex_count", {"graph_name": GRAPH})
            print("vertex counts:", c.get("data", {}).get("counts_by_type"))
            e = await call(s, "tigergraph__get_edge_count", {"graph_name": GRAPH})
            print("edge total:", e.get("data", {}).get("total"))

            t = await call(s, "tigergraph__get_node",
                           {"graph_name": GRAPH, "vertex_type": "Transaction", "vertex_id": txn})
            print("flagged txn:", json.dumps(t.get("data", t), default=str)[:600])

            nb = await call(s, "tigergraph__get_neighbors", {
                "graph_name": GRAPH, "source_vertex_type": "Card",
                "source_vertex_id": card, "edge_type": "MADE", "limit": 5})
            data = nb.get("data", {})
            print("card MADE neighbors:", json.dumps(data, default=str)[:800])

            deg = await call(s, "tigergraph__get_node_degree", {
                "graph_name": GRAPH, "vertex_type": "Card", "vertex_id": card})
            print("card degree:", json.dumps(deg.get("data", deg), default=str)[:400])

            ce = await call(s, "tigergraph__get_node_edges", {
                "graph_name": GRAPH, "vertex_type": "Transaction", "vertex_id": txn})
            print("flagged txn edges:", json.dumps(ce.get("data", ce), default=str)[:800])
            print("LIVE GRAPH TEST OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="HHG-002")
    asyncio.run(main(ap.parse_args().case))
