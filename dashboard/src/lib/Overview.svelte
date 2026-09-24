<script>
  import { verdictColor } from "./data.js";
  let { index, source } = $props();
  const rows = $derived(index.map((c) => ({ id: c.case_id, ...c[source] })));
  const counts = $derived({
    fraud: rows.filter((r) => r.verdict === "fraud").length,
    legitimate: rows.filter((r) => r.verdict === "legitimate").length,
    uncertain: rows.filter((r) => r.verdict === "uncertain").length,
  });
  const exposure = $derived(rows.reduce((s, r) => s + (r.exposure || 0), 0));
  const sar = $derived(rows.filter((r) => r.sar).length);
  const maxP = 1;
</script>

<div class="grid">
  <div class="card stat"><span class="num">{counts.fraud}</span><span>fraud</span></div>
  <div class="card stat"><span class="num">{counts.legitimate}</span><span>legitimate</span></div>
  <div class="card stat"><span class="num">{counts.uncertain}</span><span>uncertain</span></div>
  <div class="card stat"><span class="num">${exposure.toFixed(0)}</span><span>exposure USD</span></div>
  <div class="card stat"><span class="num">{sar}</span><span>SARs filed</span></div>
</div>

<div class="card">
  <h3>Fraud probability per case ({source === "llm" ? "LLM" : "rule-based"})</h3>
  <div class="bars">
    {#each rows as r}
      <div class="bar-row">
        <span class="bar-id">{r.id}</span>
        <div class="bar-track">
          <div
            class="bar-fill"
            style="width: {(r.p / maxP) * 100}%; background: {verdictColor(r.verdict)}"
          ></div>
        </div>
        <span class="bar-p">{r.p.toFixed(2)}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.75rem; margin-bottom: 1rem; }
  .stat { text-align: center; padding: 0.9rem 0.5rem; }
  .num { display: block; font-size: 1.6rem; font-weight: 700; }
  .bars { display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.5rem; }
  .bar-row { display: grid; grid-template-columns: 5.5rem 1fr 3rem; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
  .bar-id { font-family: monospace; }
  .bar-track { background: #2a2f3a; border-radius: 4px; height: 14px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; }
  .bar-p { font-family: monospace; text-align: right; }
</style>
