<script>
  import { segment } from "./format.js";
  let { text = "", compact = false } = $props();
  const parts = $derived(segment(text));
</script>

<span class="rich" class:compact>
  {#each parts as p, i}
    {#if p.kind === "text"}{p.text}
    {:else if p.kind === "amount"}<strong class="amt" key={i}>{p.text}</strong>
    {:else if p.kind === "risk" || p.kind === "prob"}<span class="risk" key={i}>{p.text}</span>
    {:else if p.kind === "pct"}<em class="mult" key={i}>{p.text}</em>
    {:else}<code class="eid" key={i}>{p.text}</code>
    {/if}
  {/each}
</span>

<style>
  .rich { line-height: 1.55; }
  .rich.compact { font-size: 0.85rem; }
  .amt { color: #ffd479; font-weight: 700; white-space: nowrap; }
  .risk { background: rgba(245, 165, 36, 0.14); color: #f5a524; border-radius: 5px; padding: 0 0.35rem; font-size: 0.85em; font-weight: 600; white-space: nowrap; }
  .mult { color: #8ab4ff; font-style: normal; font-weight: 700; white-space: nowrap; }
  .eid { font-family: var(--mono); font-size: 0.85em; background: rgba(91, 124, 255, 0.13); color: #9db1ff; border-radius: 5px; padding: 0 0.35rem; white-space: nowrap; }
</style>
