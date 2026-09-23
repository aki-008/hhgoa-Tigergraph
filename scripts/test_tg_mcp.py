"""Sample fraud-detection agent test via TigerGraph MCP (stdio).
Run:  python test_tg_mcp.py [--case HHG-002]
Requires: .env with TG_HOST, TG_USERNAME/TG_PASSWORD or TG_API_TOKEN, TG_GRAPHNAME.
Falls back to local CSVs when graph is unreachable, so CSV demo always works.
"""
import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

BASE = Path(__file__).parent


def load_env():
    vals = dotenv_values(BASE / ".env")
    # env vars take precedence over .env file
    for k in list(vals.keys()):
        if os.getenv(k):
            vals[k] = os.getenv(k)
    return vals


def read_case(case_id):
    with open(BASE / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["case_id"] == case_id:
                return row
    return None


def read_txn(txn_id):
    with open(BASE / "data" / "transactions.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["TransactionID"] == str(txn_id):
                return {k: row[k] for k in ("TransactionID", "TransactionAmt", "ProductCD", "card1", "addr1", "addr2", "ts", "channel", "risk_score", "customer_id")}
    return None


async def call_tool(session, name, args=None):
    try:
        res = await session.call_tool(name, arguments=args or {})
        texts = [c.text for c in res.content if hasattr(c, "text")]
        return True, "\n".join(texts)[:3000]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


async def main(case_id: str):
    env_vals = load_env()
    print(f"[env] TG_HOST={env_vals.get('TG_HOST', '(missing)')} "
          f"TG_GRAPHNAME={env_vals.get('TG_GRAPHNAME', '(missing)')} "
          f"TG_TGCLOUD={env_vals.get('TG_TGCLOUD', 'false')}")
    if not env_vals.get("TG_HOST") or "your-workspace" in str(env_vals.get("TG_HOST")):
        print("[warn] .env not configured (see .env.example). MCP live test will likely fail; CSV demo continues.")

    # ---- Part 1: connectivity via MCP ----
    server_params = StdioServerParameters(
        command="tigergraph-mcp",
        args=["-v"],
        env={**get_default_environment(), **{k: v for k, v in env_vals.items() if v}},
    )
    print("\n=== Part 1: MCP connectivity ===")
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [t.name for t in tools.tools]
                print(f"[mcp] {len(names)} tools. sample: {names[:8]}")

                for tool, args in [
                    ("tigergraph__list_connections", {}),
                    ("tigergraph__list_graphs", {}),
                    ("tigergraph__get_graph_schema", {"graph_name": env_vals.get("TG_GRAPHNAME", "")} if env_vals.get("TG_GRAPHNAME") else {}),
                ]:
                    if tool.removeprefix("tigergraph__") not in [n.removeprefix("tigergraph__") for n in names] and tool not in names:
                        print(f"[skip] {tool} not served")
                        continue
                    ok, out = await call_tool(session, tool, args)
                    print(f"--- {tool} {'OK' if ok else 'FAIL'} ---\n{out[:1500]}")

                # vertex count if graph known
                g = env_vals.get("TG_GRAPHNAME")
                if g:
                    ok, out = await call_tool(session, "tigergraph__get_vertex_count", {"graph_name": g})
                    print(f"--- get_vertex_count {'OK' if ok else 'FAIL'} ---\n{out[:1500]}")
    except Exception as e:  # noqa: BLE001
        print(f"[mcp ERROR] {type(e).__name__}: {e}")
        print("Tip: copy .env.example -> .env, fill Savanna host/user/pass, restart terminal.")

    # ---- Part 2: fraud case demo (CSV, always works) ----
    print(f"\n=== Part 2: fraud demo for {case_id} (local CSV) ===")
    case = read_case(case_id)
    if not case:
        print(f"Case {case_id} not found in data/case_pack.csv")
        sys.exit(1)
    print(f"trigger={case['trigger_type']} card={case['card_id']} customer={case['customer_id']} flagged_txn={case['flagged_txn_id']}")
    print(f"text: {case['trigger_text']}")
    txn = read_txn(case["flagged_txn_id"])
    print(f"flagged txn detail: {txn}")
    # closed-case memory: same card prefix / high-risk online pattern
    print("\n[closed-case memory sample]")
    with open(BASE / "data" / "closed_cases_history.csv", newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        shown = 0
        for row in rdr:
            if shown >= 3:
                break
            if row["outcome"] == "confirmed_fraud" and "card_not_present" in row["pattern"]:
                print(f"  {row['case_id']} {row['pattern']} exposure=${row['exposure_usd']} notes={row['analyst_notes'][:140]}...")
                shown += 1
    print("\nNext: invoke the opencode subagent `fraud-investigator` with this case_id to produce cases/<id>.json.")
    print("Done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="HHG-002")
    args = ap.parse_args()
    asyncio.run(main(args.case))
