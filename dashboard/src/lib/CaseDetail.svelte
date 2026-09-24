<script>
  import { loadCase, verdictColor } from "./data.js";
  let { caseId, variant } = $props();
  let data = $state(null);
  let error = $state("");
  $effect(() => {
    data = null;
    error = "";
    loadCase(caseId, variant).then((d) => {
      if (d) data = d;
      else error = `No ${variant} file for ${caseId}`;
    });
  });
</script>

{#if error}<div class="card error">{error}</div>{/if}
{#if data}
  {@const c = data.case}
  <div class="card">
    <div class="head">
      <h2>{data.case_id}</h2>
      <span class="badge" style="background: {verdictColor(c.verdict)}">{c.verdict}</span>
      <span class="meta">p={c.fraud_probability} · {c.pattern} · ${c.exposure_usd} · {c.status}</span>
    </div>
    <p class="summary">{c.summary}</p>
    {#if c.pattern_description}<p class="pdesc">{c.pattern_description}</p>{/if}
  </div>

  <div class="card">
    <h3>Evidence trail ({c.evidence.length})</h3>
    <ol class="trail">
      {#each c.evidence as e, i}
        <li>
          <div class="claim">{i + 1}. {e.claim}</div>
          <div class="cite">
            <span class="src">{e.source}</span>
            <code>{e.ref}</code>
            {#each e.entity_ids as id}<span class="eid">{id}</span>{/each}
          </div>
        </li>
      {/each}
    </ol>
  </div>

  <div class="cols">
    <div class="card">
      <h3>Actions</h3>
      <h4>initial</h4>
      <ul>{#each data.next_best_actions.initial as a}<li><b>{a.action}</b> <span class="route">{a.route}</span> — {a.reason}</li>{/each}</ul>
      <h4>final</h4>
      <ul>{#each data.next_best_actions.final as a}<li><b>{a.action}</b> <span class="route">{a.route}</span> — {a.reason}</li>{/each}</ul>
      <p class="meta">{data.next_best_actions.what_changed}</p>
      {#if data.evidence_requests.length}
        <h4>evidence requests</h4>
        <ul>{#each data.evidence_requests as q}<li>{q.type}: {q.assumed_response}</li>{/each}</ul>
      {/if}
    </div>
    <div class="card">
      <h3>SAR {data.sar.file ? "— FILE" : "— not filed"}</h3>
      <p class="meta">{data.sar.reason}</p>
      {#if data.sar.file}<p>{data.sar.narrative}</p>
        <p class="meta">subjects: {data.sar.subjects.join(", ")} · ${data.sar.total_amount_usd} · {data.sar.activity_dates.join(" → ")}</p>
      {/if}
      <p class="meta">memory: {c.similar_prior_cases.join(", ") || "—"} · {c.written_to_graph ? "in graph (" + c.graph_case_id + ")" : "not in graph"}</p>
      <p class="meta">stop: {data.stop_reason} · tools: {data.tool_calls} · {data.latency_s}s</p>
    </div>
  </div>
{/if}

<style>
  .head { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
  .head h2 { margin: 0; font-family: monospace; }
  .badge { color: #fff; border-radius: 999px; padding: 0.15rem 0.7rem; font-size: 0.8rem; font-weight: 700; }
  .summary { font-size: 1.02rem; }
  .pdesc { font-style: italic; opacity: 0.9; }
  .trail { padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.7rem; }
  .claim { margin-bottom: 0.25rem; }
  .cite { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; font-size: 0.8rem; }
  .src { background: #3a4152; border-radius: 4px; padding: 0 0.4rem; }
  code { background: #22262f; border-radius: 4px; padding: 0 0.4rem; font-size: 0.78rem; }
  .eid { font-family: monospace; color: #8ab4ff; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
  .route { background: #3a4152; border-radius: 4px; padding: 0 0.35rem; font-size: 0.75rem; }
  .error { border-color: #e5484d; }
</style>
