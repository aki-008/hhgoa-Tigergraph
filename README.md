# hhgoa-Tigergraph — agentic card-fraud investigation on TigerGraph

Investigates 20 alert cases (`data/case_pack.csv`) against 6 months of card
transactions: evidence from a TigerGraph knowledge graph, deterministic fraud
policy R1–R10, optional LLM judgment (Groq-hosted Qwen), case memory, and a
Svelte review dashboard with live run traces.

## Layout

- `agent/` — the agent: `triggers` (intake plans), `casefile` (staged states),
  `retrieval` (MCP reads), `memory` (GSQL traversal), `features`, `policy`
  (R1–R10 engine), `execution` (simulated actions + mock responders),
  `trace` (JSONL run log), `grounding` (GraphRAG retrieval), `llm`
  (provider layer), `runner` + `llm_runner` (per-case pipelines)
- `scripts/` — thin CLIs: `investigate.py`, `llm_investigate.py`,
  `setup_graph.py`, `load_stage1.py`, `install_queries.py`,
  `verify.py`, `sync_dashboard_data.py`, `test_tg_mcp.py`
- `graph/queries.gsql` — installed traversal queries (card window, ring walk, memory)
- `cases/` — answers: `HHG-*.json` (rule-based), `HHG-*.llm.json` (LLM),
  `HHG-*.trace.jsonl` (live run logs)
- `dashboard/` — Svelte review UI (overview, case evidence trail, rule-vs-LLM, live run)
- `data/` — dataset (not in git, ~700 MB): transactions, identity, closed cases, case pack

## Setup

1. Prereqs: Python 3.13+, Node 24+ (dashboard only), a TigerGraph Savanna
   workspace (free tier OK; enable auto-resume).
2. Place the dataset in `data/` (`transactions.csv`, `identity.csv`,
   `closed_cases_history.csv`, `case_pack.csv`, plus `README.md` task spec).
3. `cp .env.example .env` and fill `TG_HOST`, `TG_SECRET`, `TG_GRAPHNAME`
   (Savanna uses secret auth, not password). Optional: `GROQ_API_KEY` /
   `GROQ_MODEL` for the LLM path.
4. `pip install -r requirements.txt`

## Run

```bash
python scripts/setup_graph.py      # create HHGOA_Fraud graph + schema
python scripts/load_stage1.py      # 20 case windows + 5,565 closed cases (~20 min, throttled)
python scripts/verify.py           # live counts vs CSV cross-check
python scripts/investigate.py --all            # rule-based agent -> cases/*.json
python scripts/llm_investigate.py --pilot      # LLM agent (HHG-014/010/003) -> cases/*.llm.json
python scripts/sync_dashboard_data.py          # refresh dashboard data
cd dashboard && npm install && npm run dev     # review UI with live run traces
```

## Flow per case

trigger (intake plan) → investigate (graph window) → gather evidence
(device/email/region/memory) → assess (features + verdict) → more evidence
(mock customer/analyst responders) → act (simulated execution w/ approvals) →
explain → memorize (graph write-back). Every step streams to
`cases/<id>.trace.jsonl`, shown live in the dashboard.
