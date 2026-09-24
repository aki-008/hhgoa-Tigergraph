<script>
  import { Badge } from "$lib/components/ui/badge";
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

<div class="card hero">
  <div class="cap">Total fraud exposure · {source === "llm" ? "LLM + Laya" : "rule-based"} · {rows.length} cases</div>
  <div class="big">${exposure.toLocaleString("en-US", { maximumFractionDigits: 0 })}</div>
  <div class="cap">{sar} SAR{sar === 1 ? "" : "s"} filed · {counts.fraud} confirmed fraud</div>
</div>

<div class="grid stats">
  <div class="card stat"><span class="k">Fraud</span><span class="v" style="color:#f2555a">{counts.fraud}</span></div>
  <div class="card stat"><span class="k">Legitimate</span><span class="v" style="color:#34c77b">{counts.legitimate}</span></div>
  <div class="card stat"><span class="k">Uncertain</span><span class="v" style="color:#f5a524">{counts.uncertain}</span></div>
  <div class="card stat"><span class="k">SAR filed</span><span class="v">{sar}</span></div>
</div>

<div class="card">
  <h3>Fraud probability per case</h3>
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
        {#if r.verdict === "fraud"}<Badge variant="destructive">fraud</Badge>
        {:else if r.verdict === "legitimate"}<Badge class="b-green">legitimate</Badge>
        {:else}<Badge class="b-amber">uncertain</Badge>{/if}
      </div>
    {/each}
  </div>
  <p class="meta">Legend — <Badge variant="destructive">fraud</Badge> <Badge class="b-amber">uncertain</Badge> <Badge class="b-green">legitimate</Badge> · bar length = fraud probability</p>
</div>

<style>
  .bars { display: flex; flex-direction: column; gap: 0.32rem; margin-top: 0.5rem; }
  .bar-row { display: grid; grid-template-columns: 5.5rem 1fr 3rem 6.5rem; align-items: center; gap: 0.6rem; font-size: 0.85rem; }
  .bar-id { font-family: var(--mono); color: var(--muted-foreground); }
  .bar-track { background: rgba(255, 255, 255, 0.06); border-radius: 6px; height: 12px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 6px; }
  .bar-p { font-family: var(--mono); text-align: right; }
  :global(.b-green) { background: rgba(52,199,123,.13); color: #34c77b; border-color: transparent; }
  :global(.b-amber) { background: rgba(245,165,36,.13); color: #f5a524; border-color: transparent; }
</style>
