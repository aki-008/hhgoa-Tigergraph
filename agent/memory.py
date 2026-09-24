"""Graph-traversal memory + multi-hop queries (spec: GSQL traversal, item 5).

Uses interpreted GSQL via run_query (install endpoint is unreliable on the
free workspace; graph/queries.gsql holds the installable equivalents).
Every function falls back to 1-hop MCP helpers on failure.
"""
from . import GRAPH
from .evidence import similar_closed
from .retrieval import mcp_call


def _result_rows(res, key):
    data = res.get("data") or {}
    for block in data.get("result", []) or []:
        if isinstance(block, dict) and key in block:
            return block[key]
    return []


async def traverse_card_window(call_fn, card_id, limit=2000):
    """2-step traversal Card -> Transactions, server-side (GSQL)."""
    q = (
        "INTERPRET QUERY () FOR GRAPH " + GRAPH + " { "
        f'Seed = {{Card.*}}; One = SELECT s FROM Seed:s WHERE s.id == "{card_id}"; '
        f"Txns = SELECT t FROM One:s -(MADE:e)- Transaction:t LIMIT {int(limit)}; "
        "PRINT Txns; }")
    try:
        res = await call_fn("tigergraph__run_query",
                            {"graph_name": GRAPH, "query_text": q})
        rows = _result_rows(res, "Txns")
        if rows:
            return [{"TransactionID": n.get("v_id"),
                     **(n.get("attributes") or {})} for n in rows]
    except Exception:  # noqa: BLE001
        pass
    return []


async def traverse_device_cards(call_fn, device_str, limit=200):
    """2-hop ring walk: Device -> Transactions -> Cards (R6)."""
    q = (
        "INTERPRET QUERY () FOR GRAPH " + GRAPH + " { "
        f'Seed = {{DeviceProfile.*}}; One = SELECT s FROM Seed:s WHERE s.id == "{device_str}"; '
        f"Txns = SELECT t FROM One:s -(FROM_DEVICE:e)- Transaction:t LIMIT {int(limit)}; "
        f"Cards = SELECT c FROM Txns:t -(MADE:e)- Card:c LIMIT {int(limit)}; "
        "PRINT Cards; PRINT Txns; }")
    try:
        res = await call_fn("tigergraph__run_query",
                            {"graph_name": GRAPH, "query_text": q})
        cards = _result_rows(res, "Cards")
        txns = _result_rows(res, "Txns")
        return ([c.get("v_id") for c in cards if isinstance(c, dict)],
                [t.get("v_id") for t in txns if isinstance(t, dict)])
    except Exception:  # noqa: BLE001
        return [], []


async def traverse_case_memory(call_fn, pattern, limit=50):
    """ClosedCase vertices by pattern + their linked cards (traversal memory)."""
    q = (
        "INTERPRET QUERY () FOR GRAPH " + GRAPH + " { "
        "Seed = {ClosedCase.*}; "
        f'Cases = SELECT c FROM Seed:c WHERE c.pattern == "{pattern}" LIMIT {int(limit)}; '
        "Cards = SELECT card FROM Cases:cc -(ON_CARD:e)- Card:card; "
        "PRINT Cases; PRINT Cards; }")
    try:
        res = await call_fn("tigergraph__run_query",
                            {"graph_name": GRAPH, "query_text": q})
        cases = _result_rows(res, "Cases")
        cards = _result_rows(res, "Cards")
        return ([c.get("v_id") for c in cases if isinstance(c, dict)],
                [c.get("v_id") for c in cards if isinstance(c, dict)])
    except Exception:  # noqa: BLE001
        return [], []


async def similar_cases_graph(call_fn, pattern_hint, limit=3):
    """Memory via traversal first, CSV fallback. Returns case IDs."""
    try:
        cases, _ = await traverse_case_memory(call_fn, pattern_hint, limit * 4)
        if cases:
            # prefer agent-written HHG cases + fraud history, cap at limit
            return cases[:limit]
    except Exception:  # noqa: BLE001
        pass
    return similar_closed(pattern_hint, limit=limit)


async def ring_walk(call_fn, device_str, exclude_card, limit=200):
    """Full R6 walk: device -> txns -> cards (excl. case card)."""
    cards, txns = await traverse_device_cards(call_fn, device_str, limit)
    other = sorted({c for c in cards if c and c != exclude_card})
    return other, txns
