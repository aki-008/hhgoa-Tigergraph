"""Install GSQL queries from graph/queries.gsql onto HHGOA_Fraud.
Run: python scripts/install_queries.py
"""
import asyncio
import re
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

BASE = Path(__file__).parent.parent
GRAPH = "HHGOA_Fraud"


def split_queries(text):
    # strip // comments, split on CREATE QUERY boundaries
    parts = re.split(r"(?=CREATE QUERY )", text)
    return [p.strip() for p in parts if p.strip().startswith("CREATE QUERY")]


async def main():
    text = (BASE / "graph" / "queries.gsql").read_text(encoding="utf-8")
    queries = split_queries(re.sub(r"//[^\n]*", "", text))
    print(f"{len(queries)} queries to install")
    env_vals = {k: v for k, v in dotenv_values(BASE / ".env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for q in queries:
                name = re.search(r"CREATE QUERY (\w+)", q).group(1)
                res = await s.call_tool("tigergraph__install_query", arguments={
                    "graph_name": GRAPH, "query_text": q})
                txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                ok = '"success": true' in txt
                print(f"{name}: {'OK' if ok else 'FAIL'}")
                if not ok:
                    print(txt[:600])


if __name__ == "__main__":
    asyncio.run(main())
