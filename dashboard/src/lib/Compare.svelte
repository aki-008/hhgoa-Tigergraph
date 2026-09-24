<script>
  import { Badge } from "$lib/components/ui/badge";
  import * as Table from "$lib/components/ui/table";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import { verdictColor } from "./data.js";
  let { index, onpick = null } = $props();
  const labels = ["fraud", "uncertain", "legitimate"];
  const matrix = $derived.by(() => {
    const m = Object.fromEntries(labels.map((r) => [r, Object.fromEntries(labels.map((c) => [c, []]))]));
    for (const c of index) {
      if (c.llm && m[c.rule.verdict]?.[c.llm.verdict]) m[c.rule.verdict][c.llm.verdict].push(c);
    }
    return m;
  });
  const agree = $derived(index.filter((c) => c.llm && c.rule.verdict === c.llm.verdict).length);
  const patAgree = $derived(index.filter((c) => c.llm && c.rule.pattern === c.llm.pattern).length);
  const maxCell = $derived(Math.max(1, ...labels.flatMap((r) => labels.map((c) => matrix[r][c].length))));
  const pct = $derived(Math.round((100 * agree) / Math.max(index.length, 1)));
</script>

<div class="card">
  <div class="mhead">
    <div>
      <h3>Verdict agreement</h3>
      <p class="meta">rule rows × LLM columns · click a case chip to open its dossier</p>
    </div>
    <div class="score" style="--p:{pct}">
      <span>{agree}/{index.length}</span>
      <small>agree</small>
    </div>
  </div>
  <div class="mx">
    <div class="mx-corner"></div>
    {#each labels as c}<div class="mx-col"><span class="dot" style="background:{verdictColor(c)}"></span>{c} <span class="meta">LLM</span></div>{/each}
    {#each labels as r}
      <div class="mx-row"><span class="dot" style="background:{verdictColor(r)}"></span>{r} <span class="meta">rule</span></div>
      {#each labels as c}
        {@const cell = matrix[r][c]}
        {@const heat = cell.length / maxCell}
        <div
          class="mx-cell"
          class:diag={r === c}
          class:hot={cell.length > 0}
          style="--heat:{heat}"
        >
          <span class="mx-n">{cell.length || "·"}</span>
          {#if cell.length}
            <div class="chips">
              {#each cell as k}
                <Tooltip.Provider>
                  <Tooltip.Root>
                    <Tooltip.Trigger>
                      <Badge
                        variant={r === c ? "secondary" : "outline"}
                        class="chipbtn"
                        onclick={() => onpick?.(k.case_id)}
                      >{k.case_id.replace("HHG-", "")}</Badge>
                    </Tooltip.Trigger>
                    <Tooltip.Content>
                      {k.case_id}: rule {k.rule.verdict} {k.rule.p.toFixed(2)} → LLM {k.llm.verdict} {k.llm.p.toFixed(2)}
                    </Tooltip.Content>
                  </Tooltip.Root>
                </Tooltip.Provider>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    {/each}
  </div>
  <div class="mfoot">
    <Badge variant={patAgree === index.length ? "default" : "secondary"}>pattern agreement {patAgree}/{index.length}</Badge>
    <span class="meta">Diagonal = both heads agree. The uncertain→legitimate cell is the LLM's calibration gain over hedging.</span>
  </div>
</div>

<div class="card">
  <h3>Rule-based vs LLM per case</h3>
  <Table.Root>
    <Table.Header>
      <Table.Row><Table.Head>case</Table.Head><Table.Head>rule verdict</Table.Head><Table.Head>p</Table.Head><Table.Head>LLM verdict</Table.Head><Table.Head>p</Table.Head><Table.Head>Δ</Table.Head></Table.Row>
    </Table.Header>
    <Table.Body>
      {#each index as c}
        {@const d = (c.llm?.p ?? 0) - (c.rule.p ?? 0)}
        <Table.Row class={c.rule.verdict !== c.llm?.verdict ? "diff" : ""}>
          <Table.Cell class="mono">
            {#if onpick}<button class="link" onclick={() => onpick(c.case_id)}>{c.case_id}</button>
            {:else}{c.case_id}{/if}
          </Table.Cell>
          <Table.Cell><span class="dot" style="background: {verdictColor(c.rule.verdict)}"></span>{c.rule.verdict}</Table.Cell>
          <Table.Cell class="mono">{c.rule.p.toFixed(2)}</Table.Cell>
          <Table.Cell><span class="dot" style="background: {verdictColor(c.llm?.verdict ?? '')}"></span>{c.llm?.verdict ?? "—"}</Table.Cell>
          <Table.Cell class="mono">{c.llm ? c.llm.p.toFixed(2) : "—"}</Table.Cell>
          <Table.Cell class="mono">{c.llm ? (d >= 0 ? "+" : "") + d.toFixed(2) : "—"}</Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
</div>

<style>
  .mono { font-family: monospace; }
  .dot { display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%; margin-right: 0.4rem; }
  :global(tr.diff) { background: rgba(245, 165, 36, 0.07); }
  .link { all: unset; cursor: pointer; font-family: monospace; color: #8ab4ff; }
  .link:hover { text-decoration: underline; }
  .mhead { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.8rem; }
  .mhead h3 { margin: 0; }
  .score { --p: 0; width: 76px; height: 76px; border-radius: 50%; display: grid; place-content: center; text-align: center;
    background: conic-gradient(var(--accent) calc(var(--p) * 1%), rgba(255,255,255,.08) 0);
    position: relative; font-weight: 800; }
  .score::before { content: ""; position: absolute; inset: 8px; border-radius: 50%; background: var(--panel); }
  .score span, .score small { position: relative; }
  .score small { font-size: 0.62rem; color: var(--muted-foreground); font-weight: 500; }
  .mx { display: grid; grid-template-columns: 7.5rem repeat(3, 1fr); gap: 0.45rem; align-items: stretch; }
  .mx-col, .mx-row { font-size: 0.82rem; font-weight: 600; display: flex; align-items: center; gap: 0.35rem; }
  .mx-col { justify-content: center; }
  .mx-cell { border: 1px solid var(--border); border-radius: 12px; padding: 0.55rem 0.65rem; min-height: 4.2rem;
    background: rgba(255,255,255,.02); }
  .mx-cell.hot { border-color: color-mix(in srgb, var(--accent) calc(var(--heat) * 60%), var(--border));
    background: color-mix(in srgb, var(--accent) calc(var(--heat) * 14%), transparent); }
  .mx-cell.diag.hot { border-color: color-mix(in srgb, #34c77b calc(var(--heat) * 65%), var(--border));
    background: color-mix(in srgb, #34c77b calc(var(--heat) * 13%), transparent); }
  .mx-n { font-size: 1.25rem; font-weight: 800; font-family: var(--mono); }
  .chips { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.4rem; }
  .chip { background: rgba(255,255,255,.07); border: 1px solid var(--border); color: var(--text);
    border-radius: 999px; padding: 0.1rem 0.55rem; font-size: 0.74rem; font-family: var(--mono); cursor: pointer; }
  .chip:hover { border-color: var(--accent); color: #fff; }
  .mfoot { display: flex; gap: 0.8rem; align-items: center; margin-top: 0.8rem; flex-wrap: wrap; }
  @media (max-width: 700px) { .mx { grid-template-columns: 5.5rem repeat(3, 1fr); } }
</style>
