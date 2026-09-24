<script>
  import { verdictColor } from "./data.js";
  let { index } = $props();
</script>

<div class="card">
  <h3>Rule-based vs LLM per case</h3>
  <table>
    <thead><tr><th>case</th><th>rule verdict</th><th>p</th><th>LLM verdict</th><th>p</th><th>Δ</th></tr></thead>
    <tbody>
      {#each index as c}
        {@const d = (c.llm?.p ?? 0) - (c.rule.p ?? 0)}
        <tr class:diff={c.rule.verdict !== c.llm?.verdict}>
          <td class="mono">{c.case_id}</td>
          <td><span class="dot" style="background: {verdictColor(c.rule.verdict)}"></span>{c.rule.verdict}</td>
          <td class="mono">{c.rule.p.toFixed(2)}</td>
          <td><span class="dot" style="background: {verdictColor(c.llm?.verdict ?? '')}"></span>{c.llm?.verdict ?? "—"}</td>
          <td class="mono">{c.llm ? c.llm.p.toFixed(2) : "—"}</td>
          <td class="mono">{c.llm ? (d >= 0 ? "+" : "") + d.toFixed(2) : "—"}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid #2a2f3a; }
  .mono { font-family: monospace; }
  .dot { display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%; margin-right: 0.4rem; }
  tr.diff { background: rgba(245, 165, 36, 0.07); }
</style>
