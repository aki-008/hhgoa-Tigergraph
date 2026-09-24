# RUNBOOK — run the fraud agent yourself

Every run writes to its own directory. Old runs are never overwritten:
`cases/` holds the original reference outputs,
`cases/run_YYYYMMDD_HHMM/` holds each new run
(answer JSON + `.llm.json` + `.trace.jsonl` per case).

## 0. Prerequisites

- Python 3.13+ (tested 3.13.15), Node 24+ (dashboard only)
- A TigerGraph Savanna workspace (free tier works; enable auto-resume —
  idle workspaces sleep and must be woken in the Savanna console)
- The dataset in `data/`: `transactions.csv` (~675 MB), `identity.csv`,
  `closed_cases_history.csv`, `case_pack.csv` (data is gitignored, not cloned)

## 1. Configure

```bash
cp .env.example .env
```

Fill in `.env` (gitignored, never commit):

| Key | Value |
|---|---|
| `TG_HOST` | `https://<your-workspace>.i.tgcloud.io` (Savanna Connection panel) |
| `TG_GRAPHNAME` | `HHGOA_Fraud` |
| `TG_USERNAME` | `tigergraph` |
| `TG_SECRET` | workspace secret (Savanna uses **secret** auth, not password) |
| `TG_TGCLOUD` | `true` |
| `GROQ_API_KEY` | `gsk_...` (only for the LLM path) |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` |
| `LAYA_BASE_URL` / `LAYA_API_KEY` | Laya `/v1/systemone` server (optional advisory layer) |

## 2. Install

```bash
pip install -r requirements.txt        # includes tigergraph-mcp
cd dashboard && npm install && cd ..
```

## 3. Build the graph (once)

```bash
python scripts/setup_graph.py         # create HHGOA_Fraud schema
python scripts/load_stage1.py         # 20 case windows + 5,565 closed cases (~20 min, throttled)
python scripts/verify.py              # expect 17k+ vertices; counts must match CSVs
```

Optional (unreliable on free tier; interpreted queries are used instead):
`python scripts/install_queries.py`

## 4. Run the agent (final-run commands)

```bash
$RUN = "cases/run_$(Get-Date -Format 'yyyyMMdd_HHmm')"   # PowerShell
# RUN="cases/run_$(date +%Y%m%d_%H%M)"                   # bash

python scripts/investigate.py --all --out-dir $RUN        # rule-based (~10 min)
python scripts/llm_investigate.py --all --out-dir $RUN    # LLM + Laya advisory (~20 min)
```

Single case / pilot:

```bash
python scripts/investigate.py --case HHG-014 --out-dir $RUN
python scripts/llm_investigate.py --pilot --out-dir $RUN   # HHG-014,010,003
python scripts/llm_investigate.py --brief-only --case HHG-014   # no model needed
```

Outputs per case in `$RUN`: `HHG-xxx.json` (rule), `HHG-xxx.llm.json`
(LLM), `HHG-xxx.trace.jsonl` + `HHG-xxx.llm.trace.jsonl` (live step logs
with token counts — the dashboard Live-run tab polls these files).

## 5. Review

```bash
python scripts/sync_dashboard_data.py     # copies latest cases/ into dashboard
cd dashboard && npm run dev               # Overview | Case | Rule vs LLM | Demo run
```

## 5b. Live demo server (real execution, not replay)

```bash
python server.py --port 8000             # serves UI + runs the agent on demand
# open http://127.0.0.1:8000 -> Demo run tab -> Live -> Run live
```

The dashboard POSTs `/api/run` (localhost only; secrets stay in server-side
`.env`), the server executes the real pipeline case by case, and the UI polls
`/api/trace` every 1.5s — orb trails glow, the token stream flows, verdict
badges land as each `done` step arrives. One run at a time (409 if busy);
Stop finishes the current case. Without the server, the tab falls back to
timed replay of recorded traces.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `500/502` on `/restpp/version`, `Failed to start workspace` | Savanna asleep or crashed → Resume/Restart in console, wait 2–3 min, retry |
| `User authentication failed` | Wrong secret or `TG_PASSWORD` used → use `TG_SECRET`, user `tigergraph` |
| LLM `504 Gateway Time-out` | Tunnel/model too slow → Groq path avoids this; keep `max_tokens` small, streaming on |
| `laya unavailable: HTTPError` in problems | Laya server down (ngrok URL may have rotated) → advisory skipped, run still valid |
| `installed: false` after install_queries | Free-tier quirk → harmless; agent uses interpreted queries automatically |
| Identical `p=0.45` across cases | LLM hedging — check `problems` field; guardrails + R2 uplift compensate |
