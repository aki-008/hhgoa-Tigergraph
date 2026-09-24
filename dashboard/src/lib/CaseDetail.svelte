<script>
  import { Badge } from "$lib/components/ui/badge";
  import { Separator } from "$lib/components/ui/separator";
  import RichText from "./RichText.svelte";
  import { sentences } from "./format.js";
  import { loadCase } from "./data.js";
  let { caseId, variant } = $props();
  let data = $state(null);
  let error = $state("");
  let open = $state({});
  $effect(() => {
    data = null;
    error = "";
    open = {};
    loadCase(caseId, variant).then((d) => {
      if (d) data = d;
      else error = `No ${variant} file for ${caseId}`;
    });
  });
  const stageOf = (e) => {
    if (e.source === "customer" || e.source === "analyst") return "response";
    if (/device/i.test(e.claim) || /device/i.test(e.ref)) return "device";
    if (/testing|burst|window|baseline|history/i.test(e.claim + e.ref)) return "analysis";
    if (/email|region/i.test(e.ref)) return "linkage";
    return "baseline";
  };
  const stageLabel = { baseline: "Baseline", analysis: "Analysis", device: "Device", linkage: "Linkage", response: "Response" };
  const stageColor = { baseline: "#8ab4ff", analysis: "#5b7cff", device: "#f5a524", linkage: "#c084fc", response: "#30a46c" };
  let hover = $state(-1);
  let pinned = $state(-1);
  const shown = $derived(pinned >= 0 ? pinned : hover);
  const flowNodes = $derived.by(() => {
    if (!data) return [];
    const ev = data.case.evidence.map((e, i) => ({ kind: "ev", i, e, stage: stageOf(e) }));
    return [
      { kind: "start", label: `Trigger · ${data.case_id}` },
      ...ev,
      { kind: "end", label: `${data.case.verdict} · p=${data.case.fraud_probability}` },
    ];
  });
  const flowH = $derived(104 * (flowNodes.length + 1));
  const wrap2 = (s, per = 46) => {
    const words = String(s).split(/\s+/);
    const lines = [];
    let cur = "";
    for (const w of words) {
      if ((cur + " " + w).trim().length > per && cur) { lines.push(cur); cur = w; }
      else cur = (cur + " " + w).trim();
      if (lines.length === 2) break;
    }
    if (lines.length < 2 && cur) lines.push(cur);
    if (lines.length === 2) lines[1] += "…";
    return lines.slice(0, 2);
  };
</script>

{#if error}<div class="card error">{error}</div>{/if}
{#if data}
  {@const c = data.case}
  <div class="card">
    <div class="head">
      <h2>{data.case_id}</h2>
      {#if c.verdict === "fraud"}<Badge variant="destructive">fraud</Badge>{:else if c.verdict === "legitimate"}<Badge class="b-green">legitimate</Badge>{:else}<Badge class="b-amber">uncertain</Badge>{/if}
      <span class="meta">p={c.fraud_probability} · {c.pattern} · ${c.exposure_usd} · {c.status}</span>
    </div>
    <p class="summary"><RichText text={c.summary} /></p>
    {#if c.pattern_description}<p class="pdesc">{c.pattern_description}</p>{/if}
  </div>

  <div class="card">
    <h3>Investigation flow ({c.evidence.length} steps) — hover any node for details, click to pin</h3>
    <div class="flowwrap">
      <svg viewBox={`0 0 600 ${flowH}`} style={`height:${Math.min(flowH, 560)}px`}>
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9" fill="none" stroke="#3a4152" stroke-width="1.6" />
          </marker>
        </defs>
        {#each flowNodes as n, i}
          {@const y = 56 + i * 104}
          {#if i > 0}<line x1="300" y1={y - 104 + 28} x2="300" y2={y - 28} stroke="#3a4152" stroke-width="1.6" marker-end="url(#arr)" />{/if}
          {#if n.kind === "ev"}
            {@const col = stageColor[n.stage]}
            <g onmouseenter={() => (hover = n.i)} onmouseleave={() => (hover = -1)}
               onclick={() => (pinned = pinned === n.i ? -1 : n.i)}
               onkeydown={() => {}} role="button" tabindex="0" style="cursor:pointer">
              <rect x="90" y={y - 28} width="420" height="56" rx="12"
                fill={shown === n.i ? "#222a45" : "#171a23"}
                stroke={shown === n.i ? col : "#2e303a"} stroke-width={shown === n.i ? 2 : 1} />
              <circle cx="300" cy={y - 28} r="5" fill={col} />
              <text x="112" y={y - 8} class="flabel">{stageLabel[n.stage]}</text>
              {#each wrap2(n.e.claim) as ln, li}
                <text x="112" y={y + 8 + li * 14} class="fsub">{ln}</text>
              {/each}
            </g>
          {:else}
            <g>
              <rect x="150" y={y - 28} width="300" height="56" rx="24"
                fill={n.kind === "start" ? "rgba(91,124,255,.15)" : "rgba(255,255,255,.04)"}
                stroke={n.kind === "start" ? "#5b7cff" : "#3a4152"} stroke-width="1.5" />
              <text x="300" y={y + 5} text-anchor="middle" class="flabel end">{n.label}</text>
            </g>
          {/if}
        {/each}
      </svg>
      <div class="fdetail">
        {#if shown >= 0 && c.evidence[shown]}
          {@const e = c.evidence[shown]}
          <h4>{stageLabel[stageOf(e)]} step {shown + 1}{pinned === shown ? " (pinned)" : ""}</h4>
          <p><RichText text={e.claim} /></p>
          <div class="cite">
            <Badge variant="secondary">{e.source}</Badge>
            <code>{e.ref}</code>
          </div>
          <div class="cite">
            {#each e.entity_ids as id}<Badge variant="outline">{id}</Badge>{/each}
            {#if !e.entity_ids.length}<span class="meta">no linked IDs</span>{/if}
          </div>
        {:else}
          <h4>How to read this</h4>
          <p class="meta">Each node is one investigation step, top to bottom: trigger, evidence gathering, verdict. Hover (or tap) a node to inspect its claim, source system, exact query reference, and backing entity IDs.</p>
        {/if}
      </div>
    </div>
  </div>

  <div class="cols">
    <div class="card">
      <h3>Actions</h3>
      <h4>initial</h4>
      <ul>{#each data.next_best_actions.initial as a}<li><b>{a.action}</b> <Badge variant="outline">{a.route}</Badge> — <RichText compact text={a.reason} /></li>{/each}</ul>
      <Separator class="my-2" />
      <h4>final</h4>
      <ul>{#each data.next_best_actions.final as a}<li><b>{a.action}</b> <Badge variant="outline">{a.route}</Badge> — <RichText compact text={a.reason} /></li>{/each}</ul>
      <p class="meta">{data.next_best_actions.what_changed}</p>
      {#if data.evidence_requests.length}
        <h4>evidence requests</h4>
        <ul>{#each data.evidence_requests as q}<li>{q.type}: {q.assumed_response}</li>{/each}</ul>
      {/if}
    </div>
    <div class="card">
      <h3>SAR {data.sar.file ? "— FILE" : "— not filed"}</h3>
      <p class="meta">{data.sar.reason}</p>
      {#if data.sar.file}
        <div class="narrative">
          {#each sentences(data.sar.narrative) as s}<p><RichText text={s} /></p>{/each}
        </div>
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
  .xbadge { color: #fff; border-radius: 999px; padding: 0.15rem 0.7rem; font-size: 0.8rem; font-weight: 700; }
  .summary { font-size: 1.05rem; line-height: 1.65; }
  .narrative p { line-height: 1.7; margin: 0 0 0.55rem; }
  .narrative p:first-child::first-letter { font-size: 1.35em; font-weight: 800; color: #8ab4ff; }
  .pdesc { font-style: italic; opacity: 0.9; }
  .trail { padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.7rem; }
  .flowwrap { display: grid; grid-template-columns: 1fr 280px; gap: 1rem; }
  @media (max-width: 800px) { .flowwrap { grid-template-columns: 1fr; } }
  .flowwrap svg { width: 100%; background: #0e1016; border-radius: 10px; border: 1px solid var(--border); }
  .flabel { fill: #e8eaf0; font-size: 12.5px; font-weight: 700; }
  .flabel.end { font-size: 12px; }
  .fsub { fill: #8b90a0; font-size: 11px; font-family: var(--mono); }
  .fdetail { background: #0e1016; border: 1px solid var(--border); border-radius: 10px; padding: 0.8rem 0.9rem; align-self: start; position: sticky; top: 1rem; }
  .fdetail h4 { margin: 0 0 0.4rem; }
  .fdetail p { font-size: 0.9rem; margin: 0 0 0.5rem; }
  .timeline { list-style: none; padding: 0; margin: 0.5rem 0 0; display: flex; flex-direction: column; }
  .timeline li { display: grid; grid-template-columns: 1.2rem 1fr; position: relative; padding-bottom: 0.9rem; }
  .timeline li::before { content: ""; position: absolute; left: 0.42rem; top: 1.1rem; bottom: 0; width: 2px; background: #2a2f3a; }
  .timeline li:last-child::before { display: none; }
  .timeline .dot { width: 0.9rem; height: 0.9rem; border-radius: 50%; background: #4f6bed; margin-top: 0.15rem; z-index: 1; }
  .tclaim { all: unset; cursor: pointer; display: block; width: 100%; font-size: 0.95rem; }
  .tclaim:hover { color: #fff; }
  .tstage { display: inline-block; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; background: #3a4152; border-radius: 4px; padding: 0 0.4rem; margin-right: 0.5rem; }
  .chev { opacity: 0.6; margin-left: 0.4rem; }
  .claim { margin-bottom: 0.25rem; }
  .cite { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; font-size: 0.8rem; }
  .src { background: rgba(91,124,255,.16); color: #9db1ff; border-radius: 4px; padding: 0 0.4rem; }
  code { background: #22262f; border-radius: 4px; padding: 0 0.4rem; font-size: 0.78rem; }
  .eid { font-family: var(--mono); color: #8ab4ff; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  @media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
  .xroute { background: #3a4152; border-radius: 4px; padding: 0 0.35rem; font-size: 0.75rem; }
  .error { border-color: #e5484d; }
</style>
