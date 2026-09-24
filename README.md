# hhgoa-Tigergraph — agentic card-fraud investigation on TigerGraph

Investigates 20 alert cases against 6 months of card transactions: evidence
from a TigerGraph knowledge graph, deterministic fraud policy R1–R10, optional
LLM judgment (Groq-hosted Qwen) with a Laya typed-decision advisory layer,
case memory, and a Svelte review dashboard with live run traces.

## File types in a run directory (`cases/run_YYYYMMDD_HHMM/`, 80 files)

| Suffix | Producer | Purpose |
|---|---|---|
| `HHG-xxx.json` | `scripts/investigate.py` (rule-based) | **Submission answer**: case record (verdict, probability, pattern, evidence trail, exposure, memory), SAR filing, initial→final actions with routes, evidence requests, stop reason, stats |
| `HHG-xxx.llm.json` | `scripts/llm_investigate.py` | Same schema, verdict/pattern/narrative from the LLM (+ Laya advisory), actions still policy-constrained |
| `HHG-xxx.trace.jsonl` | rule run | Step-by-step run log: trigger → retrieve → assess → memory → evidence requests → actions → memorize → done (the dashboard Live-run tab polls this) |
| `HHG-xxx.llm.trace.jsonl` | LLM run | Same, plus `llm_judge` (with real prompt/completion token counts) and `laya_decide` steps |

Top-level `cases/*.json` are the original reference outputs; every new run
goes to a timestamped subfolder and never overwrites them. `cases/*.brief.json`
are LLM evidence briefs (debug artifacts, not submissions).

## Architecture

```
data/*.csv ──► TigerGraph HHGOA_Fraud ──► MCP (tigergraph-mcp) ──► agent/ ──► cases/run_*/
   (evidence)    (17k vertices)            (retrieval)              │  ├─ rule .json
                                                                   │  ├─ llm .json
                                                                   │  └─ traces ──► dashboard (Svelte)
                                                                   ▼
                                              ClosedCase write-back (memory)
```

Per case, the staged flow is: **trigger** (intake plan per trigger kind) →
**investigate** (graph card window) → **gather evidence** (device, email,
region, traversal memory, grounding) → **assess** (features + verdict) →
**more evidence** (deterministic mock customer/analyst responders) → **act**
(simulated execution; auto executes, L1/L2 wait for approval) → **explain** →
**memorize** (graph write-back). Judgment is swappable (heuristics → LLM →
Laya+LLM); policy and evidence handling are code-owned and stable.

## Directory map

- `agent/` — the agent package (`BASE`/`GRAPH` constants in `__init__.py`):
  - `triggers.py` — intake dispatcher: per-trigger evidence plans (risk-signal triage, customer-denial record, analyst ring sweep)
  - `casefile.py` — staged case object (`open → investigating → pending_evidence → actioned → closed_fraud|closed_legitimate|escalated`); illegal transitions raise
  - `retrieval.py` — 1-hop MCP reads (neighbors, node, edges, degree)
  - `memory.py` — multi-hop GSQL traversal (card window, device→cards ring walk, pattern case memory) with 1-hop fallback
  - `features.py` — signals: amount-vs-baseline, 48h bursts, R5 micro-auth sequences, product/region novelty, new-device/proxy, recurrence counter
  - `policy.py` — deterministic R1–R10 engine + SAR narrative template
  - `execution.py` — simulated action layer (auto executes, L1/L2 pending + approver) + deterministic mock responders (customer/step-up/analyst)
  - `trace.py` — incremental JSONL run logger (steps, tool calls, token counts)
  - `grounding.py` — GraphRAG retrieval: TF-IDF over 5,565 case notes + 16 policy/pattern chunks (embedding-swappable interface)
  - `llm.py` — provider layer (Groq primary, OpenAI-compatible fallback), briefs, validator (repairs enums/probabilities, rejects hallucinated IDs)
  - `laya_decide.py` — Laya `/v1/systemone` client: `pattern` choice + `is_fraud`/`needs_report` nouls, 0.85 confidence gate (advisory; base checkpoint is zero-shot)
  - `runner.py` / `llm_runner.py` — per-case pipelines (rule / LLM+Laya)
- `scripts/` — thin CLIs (all accept `--out-dir`, default `cases/`):
  - `investigate.py [--case X|--all]`, `llm_investigate.py [--case X|--pilot|--all|--brief-only]`
  - `setup_graph.py` (create schema), `load_stage1.py` (20 windows + all closed cases, throttled, idempotent), `install_queries.py`, `verify.py` (live counts vs CSV), `sync_dashboard_data.py`, `test_tg_mcp.py` (connectivity), `test_gsql.py` (traversal check), `eval_laya.py` (Laya baseline harness)
  - `_archive/` — superseded monoliths and early experiments
- `graph/queries.gsql` — installable traversal queries (card window, ring walk, memory)
- `cases/` — reference answers + per-run folders (see table above)
- `dashboard/` — Svelte 5 + Vite review UI: Overview (mix, exposure, probability bars), Case (cited evidence trail, actions, SAR), Rule-vs-LLM compare, Live run (2s trace polling with token totals). `public/cases/` is synced data; `dist/` is the static build
- `data/` — dataset, gitignored (~700 MB): `transactions.csv` (590k txns, Jul–Dec 2016, risk scores, no labels), `identity.csv` (144k device records, online only), `closed_cases_history.csv` (5,565 solved Jul–Oct cases = training/memory), `case_pack.csv` (20 exam cases Nov–Dec), `README.md` (task spec + fraud policy R1–R10 + answer format)
- `.opencode/agent/fraud-investigator.md` — subagent spec mirroring this pipeline

## Setup (complete)

1. **Prereqs**: Python 3.13+, Node 24+ (dashboard only), a TigerGraph Savanna
   workspace (free tier OK). Keep it awake: idle workspaces sleep — Resume in
   the Savanna console and wait 2–3 min before running.
2. **Data**: place `transactions.csv`, `identity.csv`,
   `closed_cases_history.csv`, `case_pack.csv` in `data/` and verify sizes
   (~675 / 25 / 2.6 MB).
3. **Config**: `cp .env.example .env` and fill:
   `TG_HOST` (workspace URL), `TG_GRAPHNAME=HHGOA_Fraud`,
   `TG_USERNAME=tigergraph`, `TG_SECRET` (workspace secret — Savanna uses
   **secret auth, not password**), `TG_TGCLOUD=true`.
   Optional: `GROQ_API_KEY`/`GROQ_MODEL` (LLM path),
   `LAYA_BASE_URL`/`LAYA_API_KEY` (decision advisory).
4. **Install**: `pip install -r requirements.txt` (includes `tigergraph-mcp`);
   `cd dashboard && npm install`.

## Run (complete)

```bash
python scripts/setup_graph.py                 # create HHGOA_Fraud schema (once)
python scripts/load_stage1.py                 # 20 windows + 5,565 closed cases (~20 min)
python scripts/verify.py                      # 17k+ vertices; must match CSV counts
# final run into a fresh folder (PowerShell shown; bash: RUN="cases/run_$(date +%Y%m%d_%H%M)")
$RUN = "cases/run_$(Get-Date -Format 'yyyyMMdd_HHmm')"
python scripts/investigate.py --all --out-dir $RUN        # rule-based (~10 min)
python scripts/llm_investigate.py --all --out-dir $RUN    # LLM + Laya advisory (~20 min)
python scripts/sync_dashboard_data.py         # refresh dashboard data
cd dashboard && npm run dev                   # review UI (Live run polls traces)
```

Single case / pilots: `--case HHG-014`, `--pilot` (LLM: HHG-014/010/003),
`--brief-only` (no model needed). Validate any run: every `affected_txn_ids`
must exist in `transactions.csv`; `sar.file` must equal FILE_REPORT presence;
no `BLOCK_CARD` without a fraud verdict.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `500/502`, `Failed to start workspace` | Resume/restart workspace in Savanna console, wait, retry |
| `User authentication failed` | Use `TG_SECRET` (not password), user `tigergraph` |
| LLM `504` | Tunnel/model too slow; Groq path avoids it; keep budgets small, streaming on |
| `laya unavailable` in `problems` | Decision server down (tunnel URL may have rotated); advisory skipped, run stays valid |
| `installed: false` after install | Free-tier quirk; agent uses interpreted queries automatically |
