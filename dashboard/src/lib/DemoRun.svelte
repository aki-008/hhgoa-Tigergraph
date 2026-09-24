<script>
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Progress } from "$lib/components/ui/progress";
  import { Slider } from "$lib/components/ui/slider";
  import RichText from "./RichText.svelte";
  import { demo, liveRun, liveStop, reset, runAll, startProbing, stop, SOURCES } from "./demoStore.svelte.js";
  let { index } = $props();
  startProbing();
  startProbing();

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
</script>

<div class="card">
  <div class="demo-head">
    <div>
      <h3>Investigative demo — 20 cases, streaming agent execution</h3>
      {#if demo.serverUp}
        <p class="livepill">● LIVE SERVER CONNECTED{demo.serverCase ? ` — executing ${demo.serverCase} now` : " — real agent runs available"}</p>
      {:else}
        <p class="meta">Static replay mode — start <code>python server.py</code> and reload for live execution.</p>
      {/if}
      <p class="meta">The orb is the agent. The glowing trail marks the source it is consulting right now; dim dashed trails are idle. State persists across tabs until the run finishes.</p>
    </div>
    <div class="controls">
      {#if demo.serverUp}
        <Button variant={demo.mode === "live" ? "default" : "outline"} onclick={() => { if (!demo.running) demo.mode = "live"; }}>● Live</Button>
        <Button variant={demo.mode === "replay" ? "default" : "outline"} onclick={() => { if (!demo.running) demo.mode = "replay"; }}>◌ Replay</Button>
      {:else}
        <span class="meta" title="Start python server.py for live execution">replay mode (server offline)</span>
      {/if}
      <label><input type="radio" name="dv" value="rule" bind:group={demo.variant} disabled={demo.running} /> rule</label>
      <label><input type="radio" name="dv" value="llm" bind:group={demo.variant} disabled={demo.running} /> LLM</label>
      {#if demo.mode === "live" && demo.serverUp}
        <select bind:value={demo.liveCase} disabled={demo.running} class="pick">
          <option value="all">all 20 cases</option>
          {#each index as c}<option value={c.case_id}>{c.case_id}</option>{/each}
        </select>
      {/if}
      <span class="speed"><span class="meta">speed {demo.speedArr[0] ?? 1}x</span><Slider.Root bind:value={demo.speedArr} min={0.5} max={4} step={0.5} class="w-28" /></span>
      {#if demo.mode === "live" && demo.serverUp}
        {#if !demo.running}<Button onclick={() => liveRun(index)}>▶ Run live</Button>
        {:else}<Button variant="outline" onclick={liveStop}>■ Stop</Button>{/if}
      {:else}
        {#if !demo.running}<Button onclick={() => runAll(index)}>▶ Run demo</Button>
        {:else}<Button variant="outline" onclick={stop}>■ Stop</Button>{/if}
      {/if}
      <Button variant="ghost" onclick={reset} disabled={demo.running}>Reset</Button>
    </div>
  </div>
  <div class="meta">Progress: {demo.doneCases.length}/{index.length} cases · {demo.tokens.prompt + demo.tokens.completion} tokens ({demo.tokens.prompt} prompt / {demo.tokens.completion} completion)</div>
  <Progress value={(100 * demo.doneCases.length) / Math.max(index.length, 1)} class="mt-2" />
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
        {@const on = demo.active === s.id}
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
        {@const on = demo.active === s.id}
        <g opacity={demo.active && !on ? 0.55 : 1}>
          <rect x={p.x - 46} y={p.y - 24} width="92" height="48" rx="12"
            fill={on ? "rgba(91,124,255,.22)" : "rgba(23,26,35,.92)"}
            stroke={on ? "#8ab4ff" : "#2e303a"} stroke-width={on ? 2 : 1}
            filter={on ? "url(#glow)" : null} />
          <text x={p.x} y={p.y - 2} text-anchor="middle" class="nico">{s.ico}</text>
          <text x={p.x} y={p.y + 14} text-anchor="middle" class="nlabel">{s.label}</text>
        </g>
      {/each}
      <circle cx={CX} cy={CY} r="46" fill="none" stroke="rgba(91,124,255,.25)" />
      <circle cx={CX} cy={CY} r="34" fill="url(#orb)" filter="url(#glow)">
        <animate attributeName="r" values="34;37;34" dur="2.4s" repeatCount="indefinite" />
      </circle>
      <text x={CX} y={CY + 58} text-anchor="middle" class="agentlabel">AGENT</text>
    </svg>
    </div>
    {#if demo.doneCases.length}
      <div class="chips">
        {#each demo.doneCases as d}
          <Badge variant={d.verdict === "fraud" ? "destructive" : "secondary"} title={`${d.id}: p=${d.p}`}>{d.id.replace("HHG-", "")}</Badge>
        {/each}
      </div>
    {/if}
  </div>

  <div class="card stream">
    <h3>Token stream {demo.running ? "● live" : "○ idle"}</h3>
    <ol>
      {#each demo.feed as f}
        <li class="k-{f.kind}">
          <span class="mono dim">{f.caseId.replace("HHG-", "")}</span>
          <span class="kind">{f.step}</span>
          <span class="msg"><RichText compact text={f.msg} /></span>
          {#if f.tokens.prompt + f.tokens.completion > 0}
            <span class="mono dim">+{f.tokens.prompt + f.tokens.completion}</span>
          {/if}
        </li>
      {/each}
      {#if !demo.feed.length}<li class="meta">
        {#if demo.mode === "live" && demo.serverUp}Press ▶ Run live — the server executes the real pipeline and steps stream here as they happen.
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
  .meta { font-size: 0.8rem; color: var(--muted-foreground); }
  .progress { height: 8px; border-radius: 6px; background: rgba(255,255,255,.07); margin-top: 0.6rem; overflow: hidden; }
  .progress div { height: 100%; background: linear-gradient(90deg,#5b7cff,#8aa2ff); transition: width .4s; }
  .cols2 { display: grid; grid-template-columns: 1.15fr 1fr; gap: 1rem; }
  @media (max-width: 960px) { .cols2 { grid-template-columns: 1fr; } }
  .stage svg { width: 100%; height: 100%; display: block; }
  .stagewrap { position: relative; aspect-ratio: 560 / 480; }
  .stagewrap > svg { position: absolute; inset: 0; }
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
  .mono { font-family: var(--mono); }
  .speed { display: flex; align-items: center; gap: 0.5rem; }
</style>
