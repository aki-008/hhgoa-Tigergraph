<script>
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Progress } from "$lib/components/ui/progress";
  import { Slider } from "$lib/components/ui/slider";
  import GeometricOrb from "./GeometricOrb.svelte";
  import RichText from "./RichText.svelte";
  import { verdictColor } from "./data.js";
  let { index } = $props();

  const SOURCES = [
    { id: "casefile", label: "Case file", ico: "▤" },
    { id: "tigergraph", label: "TigerGraph", ico: "◈" },
    { id: "mcp", label: "MCP tools", ico: "⛭" },
    { id: "memory", label: "Case memory", ico: "❖" },
    { id: "policy", label: "Policy engine", ico: "⚖" },
    { id: "judge", label: "LLM judge", ico: "✦" },
    { id: "desk", label: "Actors & scribe", ico: "✎" },
  ];
  // trace step -> source node
  const route = (e) => {
    const m = `${e.step} ${e.msg}`;
    if (e.step === "trigger") return "casefile";
    if (e.step === "traverse") return "tigergraph";
    if (e.step === "memory" || e.step === "memorize") return "memory";
    if (e.step === "assess") return "policy";
    if (e.step === "llm_judge" || e.step === "laya_decide" || e.step === "laya_gate") return "judge";
    if (e.step === "evidence_request" || e.step === "action") return "desk";
    if (/travers|graph|query/i.test(m)) return "tigergraph";
    if (/tool:/i.test(m)) return "mcp";
    return "mcp";
  };
  const KIND = { trigger: "discovery", retrieve: "mcp", traverse: "traversal", memory: "discovery",
    assess: "switching", llm_judge: "switching", laya_decide: "switching",
    evidence_request: "clues", action: "clues", memorize: "clues", done: "finalize" };

  let variant = $state("rule");
  let running = $state(false);
  let speedArr = $state([1]);
  const speed = $derived(speedArr[0] ?? 1);
  let qi = $state(0); // case queue index
  let feed = $state([]); // streamed events {caseId, step, msg, tokens, kind}
  let active = $state(null); // currently glowing source id
  let doneCases = $state([]); // {id, verdict, p}
  let tokens = $state({ prompt: 0, completion: 0 });
  let stopFlag = $state(false);
  let mode = $state("replay"); // replay | live (live needs python server.py)
  let serverUp = $state(false);
  let serverCase = $state(null); // case the server is executing right now
  let liveCase = $state("all");
  let liveSeen = $state({}); // caseId -> events already shown

  async function probeServer() {
    try {
      const r = await fetch("api/status", { cache: "no-store" });
      if (!r.ok) throw 0;
      const s = await r.json();
      const was = serverUp;
      serverUp = true;
      serverCase = s.case;
      if (!was && !s.running) mode = "live";
      return s;
    } catch (_) {
      serverUp = false;
      serverCase = null;
      return null;
    }
  }
  probeServer();
  setInterval(() => { if (!running) probeServer(); }, 5000);

  const W = 560, H = 480, CX = 280, CY = 220;
  let nodePos = $derived.by(() => {
    const p = {};
    SOURCES.forEach((s, i) => {
      const a = (2 * Math.PI * i) / SOURCES.length - Math.PI / 2;
      p[s.id] = { x: CX + 205 * Math.cos(a), y: CY + 175 * Math.sin(a) };
    });
    return p;
  });
  const trail = (id) => {
    const n = nodePos[id];
    if (!n) return "";
    const mx = (CX + n.x) / 2, my = (CY + n.y) / 2 - 34;
    return `M ${CX} ${CY} Q ${mx} ${my} ${n.x} ${n.y}`;
  };

  const suffix = $derived(variant === "llm" ? ".llm" : "");
  async function loadTrace(id) {
    const r = await fetch(`cases/${id}${suffix}.trace.jsonl`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.text()).trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
  }
  const wait = (ms) => new Promise((res) => setTimeout(res, ms));
  const pace = (e) => Math.max(120, (e.step === "retrieve" ? 260 : 750) / speed);

  function pushEvent(id, e) {
    const src = route(e);
    active = src;
    const pt = e.tokens?.prompt || 0, ct = e.tokens?.completion || 0;
    tokens = { prompt: tokens.prompt + pt, completion: tokens.completion + ct };
    feed = [...feed.slice(-200), { caseId: id, step: e.step, msg: e.msg, kind: KIND[e.step] || "mcp", tokens: { prompt: pt, completion: ct } }];
  }
  async function fetchDossier(id) {
    try {
      const r = await fetch(`cases/${id}${suffix}.json`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        if (!doneCases.some((x) => x.id === id))
          doneCases = [...doneCases, { id, verdict: d.case.verdict, p: d.case.fraud_probability }];
      }
    } catch (_) { /* artifact not written yet */ }
  }
  // ---- live mode: real execution via server.py ----
  async function liveRun() {
    if (running) return;
    const ids = liveCase === "all" ? index.map((c) => c.case_id) : [liveCase];
    const start = await fetch("api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: liveCase === "all" ? "all" : liveCase, variant }),
    });
    if (start.status === 409) {
      feed = [...feed, { caseId: "—", step: "done", msg: "server busy — another run in progress", kind: "finalize", tokens: {} }];
      return;
    }
    running = true;
    stopFlag = false;
    feed = [];
    doneCases = [];
    tokens = { prompt: 0, completion: 0 };
    liveSeen = {};
    active = null;
    const seenCount = {};
    let finished = false;
    while (!finished && !stopFlag) {
      await wait(1500);
      let st = { running: true, case: null };
      try {
        st = await (await fetch("api/status", { cache: "no-store" })).json();
        serverCase = st.case;
      } catch (_) { /* server went away */ }
      for (const id of ids) {
        try {
          const tr = await (await fetch(
            `api/trace?case=${id}&variant=${variant}`, { cache: "no-store" })).json();
          const evs = tr.events || [];
          const from = seenCount[id] || 0;
          for (const e of evs.slice(from)) pushEvent(id, e);
          seenCount[id] = evs.length;
          const last = evs[evs.length - 1];
          if (last?.step === "done") await fetchDossier(id);
        } catch (_) { /* keep polling */ }
      }
      finished = !st.running;
    }
    running = false;
    active = null;
  }
  async function liveStop() {
    stopFlag = true;
    try { await fetch("api/stop", { method: "POST" }); } catch (_) { /* noop */ }
  }
  // ---- replay mode: timed playback of recorded traces ----
  async function runAll() {
    if (running) return;
    running = true;
    stopFlag = false;
    feed = [];
    doneCases = [];
    tokens = { prompt: 0, completion: 0 };
    active = null;
    for (; qi < index.length && !stopFlag; qi++) {
      await runCase(index[qi].case_id);
    }
    if (!stopFlag) qi = 0;
    running = false;
    active = null;
  }
  async function runCase(id) {
    const events = await loadTrace(id);
    if (!events) {
      feed = [...feed, { caseId: id, step: "done", msg: "no trace file — run the agent CLI first", kind: "finalize", tokens: {} }];
      return;
    }
    for (const e of events) {
      if (stopFlag) return;
      const src = route(e);
      active = src;
      const pt = e.tokens?.prompt || 0, ct = e.tokens?.completion || 0;
      tokens = { prompt: tokens.prompt + pt, completion: tokens.completion + ct };
      feed = [...feed.slice(-160), { caseId: id, step: e.step, msg: e.msg, kind: KIND[e.step] || "mcp", tokens: { prompt: pt, completion: ct } }];
      await wait(pace(e));
    }
    try {
      const r = await fetch(`cases/${id}${suffix}.json`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        doneCases = [...doneCases, { id, verdict: d.case.verdict, p: d.case.fraud_probability }];
      }
    } catch (_) { /* offline artifact */ }
  }
  function stop() { stopFlag = true; }
  function reset() { qi = 0; feed = []; doneCases = []; tokens = { prompt: 0, completion: 0 }; active = null; }
</script>

<div class="card">
  <div class="demo-head">
    <div>
      <h3>Investigative demo — 20 cases, live replay of real agent traces</h3>
      {#if serverUp}
        <p class="livepill">● LIVE SERVER CONNECTED{serverCase ? ` — executing ${serverCase} now` : " — real agent runs available"}</p>
      {:else}
        <p class="meta">Static replay mode — start <code>python server.py</code> and reload for live execution.</p>
      {/if}
      <p class="meta">The orb is the agent. The glowing trail marks the source it is consulting right now; dim dashed trails are idle. Token counts stream from the recorded run.</p>
    </div>
    <div class="controls">
      {#if serverUp}
        <Button variant={mode === "live" ? "default" : "outline"} onclick={() => { if (!running) mode = "live"; }}>● Live</Button>
        <Button variant={mode === "replay" ? "default" : "outline"} onclick={() => { if (!running) mode = "replay"; }}>◌ Replay</Button>
      {:else}
        <span class="meta" title="Start python server.py for live execution">replay mode (server offline)</span>
      {/if}
      <label><input type="radio" name="dv" value="rule" bind:group={variant} disabled={running} /> rule</label>
      <label><input type="radio" name="dv" value="llm" bind:group={variant} disabled={running} /> LLM</label>
      {#if mode === "live" && serverUp}
        <select bind:value={liveCase} disabled={running} class="pick">
          <option value="all">all 20 cases</option>
          {#each index as c}<option value={c.case_id}>{c.case_id}</option>{/each}
        </select>
      {/if}
      <span class="speed"><span class="meta">speed {speed}x</span><Slider.Root bind:value={speedArr} min={0.5} max={4} step={0.5} class="w-28" /></span>
      {#if mode === "live" && serverUp}
        {#if !running}<Button onclick={liveRun}>▶ Run live</Button>
        {:else}<Button variant="outline" onclick={liveStop}>■ Stop</Button>{/if}
      {:else}
        {#if !running}<Button onclick={runAll}>▶ Run demo</Button>
        {:else}<Button variant="outline" onclick={stop}>■ Stop</Button>{/if}
      {/if}
      <Button variant="ghost" onclick={reset} disabled={running}>Reset</Button>
    </div>
  </div>
  <div class="meta">Progress: {doneCases.length}/{index.length} cases · {tokens.prompt + tokens.completion} tokens ({tokens.prompt} prompt / {tokens.completion} completion)</div>
  <Progress value={(100 * doneCases.length) / Math.max(index.length, 1)} class="mt-2" />
</div>

<div class="cols2">
  <div class="card stage">
    <div class="stagewrap">
    <svg viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <radialGradient id="orb" cx="38%" cy="32%" r="75%">
          <stop offset="0%" stop-color="#cfe0ff" />
          <stop offset="35%" stop-color="#5b7cff" />
          <stop offset="75%" stop-color="#22306e" />
          <stop offset="100%" stop-color="#0b0d12" />
        </radialGradient>
        <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="5" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <pattern id="grid" width="34" height="34" patternUnits="userSpaceOnUse">
          <path d="M 34 0 L 0 0 0 34" fill="none" stroke="rgba(91,124,255,.10)" stroke-width="1" />
        </pattern>
      </defs>
      <rect x="0" y="0" width={W} height={H} fill="url(#grid)" rx="12" />
      {#each SOURCES as s}
        {@const on = active === s.id}
        <path d={trail(s.id)} fill="none"
          stroke={on ? "#8ab4ff" : "rgba(139,144,160,.35)"}
          stroke-width={on ? 2.6 : 1.1}
          stroke-dasharray={on ? "none" : "5 6"}
          opacity={on ? 1 : 0.55}
          filter={on ? "url(#glow)" : null}>
          {#if on}<animate attributeName="opacity" values="1;.55;1" dur="1.1s" repeatCount="indefinite" />{/if}
        </path>
      {/each}
      {#each SOURCES as s}
        {@const p = nodePos[s.id]}
        {@const on = active === s.id}
        <g opacity={active && !on ? 0.55 : 1}>
          <rect x={p.x - 46} y={p.y - 24} width="92" height="48" rx="12"
            fill={on ? "rgba(91,124,255,.22)" : "rgba(23,26,35,.92)"}
            stroke={on ? "#8ab4ff" : "#2e303a"} stroke-width={on ? 2 : 1}
            filter={on ? "url(#glow)" : null} />
          <text x={p.x} y={p.y - 2} text-anchor="middle" class="nico">{s.ico}</text>
          <text x={p.x} y={p.y + 14} text-anchor="middle" class="nlabel">{s.label}</text>
        </g>
      {/each}
      <circle cx={CX} cy={CY} r="46" fill="none" stroke="rgba(91,124,255,.25)" />
      <text x={CX} y={CY + 58} text-anchor="middle" class="agentlabel">AGENT</text>
    </svg>
    <div class="orb3d"><GeometricOrb color="#8ab4ff" active={running} /></div>
    </div>
    {#if doneCases.length}
      <div class="chips">
        {#each doneCases as d}
          <Badge variant={d.verdict === "fraud" ? "destructive" : "secondary"} title={`${d.id}: p=${d.p}`}>{d.id.replace("HHG-", "")}</Badge>
        {/each}
      </div>
    {/if}
  </div>

  <div class="card stream">
    <h3>Token stream {running ? "● live" : "○ idle"}</h3>
    <ol>
      {#each feed as f}
        <li class="k-{f.kind}">
          <span class="mono dim">{f.caseId.replace("HHG-", "")}</span>
          <span class="kind">{f.step}</span>
          <span class="msg"><RichText compact text={f.msg} /></span>
          {#if f.tokens.prompt + f.tokens.completion > 0}
            <span class="mono dim">+{f.tokens.prompt + f.tokens.completion}</span>
          {/if}
        </li>
      {/each}
      {#if !feed.length}<li class="meta">
        {#if mode === "live" && serverUp}Press ▶ Run live — the server executes the real pipeline and steps stream here as they happen.
        {:else}Press ▶ Run demo — recorded traces replay here step by step. For live execution, start <code>python server.py</code>.{/if}
      </li>{/if}
    </ol>
  </div>
</div>

<style>
  .demo-head { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; align-items: flex-start; }
  .livepill { display: inline-block; font-size: 0.82rem; font-weight: 700; color: #34c77b; background: rgba(52,199,123,.12); border: 1px solid rgba(52,199,123,.4); border-radius: 999px; padding: 0.15rem 0.7rem; margin: 0.35rem 0; }
  .livepill { animation: pulse 2s infinite; }
  @keyframes pulse { 50% { opacity: 0.65; } }
  .controls { display: flex; gap: 0.9rem; align-items: center; font-size: 0.86rem; color: var(--muted-foreground); flex-wrap: wrap; }
  .progress { height: 8px; border-radius: 6px; background: rgba(255,255,255,.07); margin-top: 0.6rem; overflow: hidden; }
  .progress div { height: 100%; background: linear-gradient(90deg,#5b7cff,#8aa2ff); transition: width .4s; }
  .cols2 { display: grid; grid-template-columns: 1.15fr 1fr; gap: 1rem; }
  @media (max-width: 960px) { .cols2 { grid-template-columns: 1fr; } }
  .stage svg { width: 100%; height: 100%; display: block; }
  .stagewrap { position: relative; aspect-ratio: 560 / 480; }
  .stagewrap > svg { position: absolute; inset: 0; }
  .orb3d { position: absolute; left: 50%; top: 45.8%; width: 26%; aspect-ratio: 1; transform: translate(-50%, -50%); pointer-events: none; }
  .nico { fill: #c9cedb; font-size: 17px; }
  .nlabel { fill: #8b90a0; font-size: 10px; }
  .agentlabel { fill: #c9cedb; font-size: 11px; letter-spacing: 0.22em; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.6rem; }
  .stream ol { list-style: none; margin: 0.5rem 0 0; padding: 0; max-height: 560px; overflow-y: auto; display: flex; flex-direction: column; gap: 0.28rem; font-size: 0.83rem; }
  .stream li { display: flex; gap: 0.5rem; align-items: baseline; border-left: 3px solid var(--border); padding: 0.15rem 0 0.15rem 0.5rem; }
  .stream li.k-discovery { border-color: #8ab4ff; }
  .stream li.k-mcp { border-color: #3a4152; }
  .stream li.k-traversal { border-color: #c084fc; }
  .stream li.k-switching { border-color: #f5a524; }
  .stream li.k-clues { border-color: #30a46c; }
  .stream li.k-finalize { border-color: #e5484d; }
  .kind { background: rgba(255,255,255,.07); border-radius: 4px; padding: 0 0.35rem; font-size: 0.72rem; white-space: nowrap; }
  .pick { background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 0.35rem 0.5rem; font-family: var(--mono); font-size: 0.82rem; }
  .msg { flex: 1; color: #c9cedb; }
  .dim { opacity: 0.55; }
</style>
