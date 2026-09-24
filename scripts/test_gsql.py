"""Test interpreted GSQL traversal on HHGOA_Fraud."""
import asyncio
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

Q = (
    "INTERPRET QUERY () FOR GRAPH HHGOA_Fraud { "
    'Seed = {Card.*}; '
    'One = SELECT s FROM Seed:s WHERE s.id == "C11891-K1"; '
    "Txns = SELECT t FROM One:s -(MADE:e)- Transaction:t LIMIT 3; "
    "PRINT Txns; }"
)


async def main():
    env_vals = {k: v for k, v in dotenv_values(".env").items() if v}
    sp = StdioServerParameters(command="tigergraph-mcp", args=["-v"],
                               env={**get_default_environment(), **env_vals})
    async with stdio_client(sp) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("tigergraph__run_query",
                                    arguments={"graph_name": "HHGOA_Fraud",
                                               "query_text": Q})
            print("\n".join(c.text for c in res.content if hasattr(c, "text"))[:1200])


if __name__ == "__main__":
    asyncio.run(main())
