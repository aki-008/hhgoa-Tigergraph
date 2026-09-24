"""TigerGraph MCP retrieval helpers."""
import json

from . import GRAPH, MARK

# ---------------------------------------------------------------- MCP helpers

async def mcp_call(s, name, args):
    res = await s.call_tool(name, arguments=args)
    txt = "\n".join(c.text for c in res.content if hasattr(c, "text"))
    if MARK in txt:
        try:
            return json.loads(txt.split(MARK)[1].split("```")[0])
        except ValueError:
            pass
    return {"_raw": txt[:300], "_ok": '"success": true' in txt}


async def graph_window(call_fn, card_id, limit=2000):
    """Card -> MADE -> Transactions via live graph."""
    r = await call_fn("tigergraph__get_neighbors", {
        "graph_name": GRAPH, "vertex_type": "Card", "vertex_id": card_id,
        "edge_type": "MADE", "limit": limit})
    nbs = (r.get("data") or {}).get("neighbors", [])
    txns = [{"TransactionID": n["v_id"], **{k: v for k, v in n.get("attributes", {}).items()}} for n in nbs]
    # normalize attribute names to CSV-ish
    for t in txns:
        t.setdefault("TransactionAmt", t.pop("amount", 0))
        t.setdefault("ts", t.get("ts", ""))
        t.setdefault("channel", t.get("channel", ""))
        t.setdefault("ProductCD", t.pop("product_cd", ""))
        t.setdefault("risk_score", t.get("risk_score", 0))
        t.setdefault("addr1", t.get("addr1", ""))
    txns.sort(key=lambda r: str(r.get("ts", "")))
    return txns


async def graph_txn_edges(call_fn, txn_id):
    r = await call_fn("tigergraph__get_node_edges", {
        "graph_name": GRAPH, "vertex_type": "Transaction",
        "vertex_id": str(txn_id), "limit": 20})
    return (r.get("data") or {}).get("edges", [])


async def shared_device_cards(call_fn, device_str, exclude_card):
    """R6: other cards sharing the flagged txn's device profile (via graph)."""
    if not device_str:
        return []
    try:
        r = await call_fn("tigergraph__get_neighbors", {
            "graph_name": GRAPH, "vertex_type": "DeviceProfile",
            "vertex_id": device_str, "limit": 50})
        cards = set()
        for n in (r.get("data") or {}).get("neighbors", []):
            if n.get("v_type") == "Transaction":
                cid = (n.get("attributes") or {}).get("card_id", "")
                if cid and cid != exclude_card:
                    cards.add(cid)
        return sorted(cards)
    except Exception:  # noqa: BLE001
        return []

