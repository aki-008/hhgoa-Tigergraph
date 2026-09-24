"""Quick live verification of HHGOA_Fraud contents. Run: python verify_hhgoa.py"""
import asyncio
import json
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

GRAPH = "HHGOA_Fraud"
MARK = "```json"


async def call(s, name, args):
    res = await s.call_tool(name, arguments=args)
    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
    if MARK in txt:
        return json.loads(txt.split(MARK)[1].split("```")[0])
    return {"raw": txt[:500]}


async def main():
    env_vals = {k: v for k, v in dotenv_values("./.env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            vc = await call(s, "tigergraph__get_vertex_count", {"graph_name": GRAPH})
            print("VERTEX:", json.dumps(vc.get("data", vc), default=str))
            ec = await call(s, "tigergraph__get_edge_count", {"graph_name": GRAPH})
            print("EDGE:", json.dumps(ec.get("data", ec), default=str))
            t = await call(s, "tigergraph__get_node", {
                "graph_name": GRAPH, "vertex_type": "Transaction", "vertex_id": "3478782"})
            print("TXN 3478782:", json.dumps(t.get("data", t), default=str)[:700])
            nb = await call(s, "tigergraph__get_node_degree", {
                "graph_name": GRAPH, "vertex_type": "Card", "vertex_id": "C11891-K1"})
            print("CARD DEGREE:", json.dumps(nb.get("data", nb), default=str)[:400])


if __name__ == "__main__":
    asyncio.run(main())
