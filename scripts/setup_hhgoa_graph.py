"""Create HHGOA_Fraud graph (task suggested schema, STRING-safe attributes).
Run: python setup_hhgoa_graph.py
"""
import asyncio
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

GRAPH = "HHGOA_Fraud"

VERTICES = [
    {"name": "Customer", "attributes": []},
    {"name": "Card", "attributes": [
        {"name": "customer_id", "type": "STRING"}]},
    {"name": "Transaction", "attributes": [
        {"name": "amount", "type": "DOUBLE"},
        {"name": "ts", "type": "STRING"},
        {"name": "channel", "type": "STRING"},
        {"name": "product_cd", "type": "STRING"},
        {"name": "risk_score", "type": "DOUBLE"},
        {"name": "addr1", "type": "STRING"},
        {"name": "card_id", "type": "STRING"}]},
    {"name": "DeviceProfile", "attributes": [
        {"name": "device_info", "type": "STRING"}]},
    {"name": "EmailDomain", "attributes": []},
    {"name": "BillingRegion", "attributes": []},
    {"name": "ClosedCase", "attributes": [
        {"name": "outcome", "type": "STRING"},
        {"name": "pattern", "type": "STRING"},
        {"name": "exposure", "type": "DOUBLE"},
        {"name": "notes", "type": "STRING"}]},
]

EDGES = [
    {"name": "OWNS", "from_vertex": "Customer", "to_vertex": "Card"},
    {"name": "MADE", "from_vertex": "Card", "to_vertex": "Transaction"},
    {"name": "FROM_DEVICE", "from_vertex": "Transaction", "to_vertex": "DeviceProfile"},
    {"name": "PURCHASER_EMAIL", "from_vertex": "Transaction", "to_vertex": "EmailDomain"},
    {"name": "BILLED_IN", "from_vertex": "Transaction", "to_vertex": "BillingRegion"},
    {"name": "INVOLVES", "from_vertex": "ClosedCase", "to_vertex": "Transaction"},
    {"name": "ON_CARD", "from_vertex": "ClosedCase", "to_vertex": "Card"},
    {"name": "NEXT", "from_vertex": "Transaction", "to_vertex": "Transaction"},
]


async def main():
    env_vals = {k: v for k, v in dotenv_values("./.env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            # skip if exists
            res = await s.call_tool("tigergraph__list_graphs", arguments={})
            txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
            if GRAPH in txt:
                print(f"Graph {GRAPH} already exists.")
                return
            res = await s.call_tool("tigergraph__create_graph", arguments={
                "graph_name": GRAPH,
                "vertex_types": VERTICES,
                "edge_types": EDGES,
            })
            print("\n".join(c.text for c in res.content if hasattr(c, "text"))[:3000])


if __name__ == "__main__":
    asyncio.run(main())
