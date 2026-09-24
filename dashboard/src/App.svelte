<script>
  import * as Select from "$lib/components/ui/select";
  import { loadIndex } from "./lib/data.js";
  import Overview from "./lib/Overview.svelte";
  import CaseDetail from "./lib/CaseDetail.svelte";
  import Compare from "./lib/Compare.svelte";
  import DemoRun from "./lib/DemoRun.svelte";

  let index = $state([]);
  let error = $state("");
  let loading = $state(true);
  let tab = $state("overview"); // overview | case | compare | demo
  let caseId = $state("HHG-002");
  let variant = $state("rule"); // rule | llm
  let trigFilter = $state("all");

  async function loadAll(retries = 3) {
    loading = true;
    error = "";
    for (let i = 0; i < retries; i++) {
      try {
        const ctrl = new AbortController();
        const to = setTimeout(() => ctrl.abort(), 15000);
        const r = await fetch("cases/index.json", { cache: "no-store", signal: ctrl.signal });
        clearTimeout(to);
        if (!r.ok) throw new Error(`index.json HTTP ${r.status} — run scripts/sync_dashboard_data.py`);
        const d = await r.json();
        index = d;
        if (!d.some((c) => c.case_id === caseId)) caseId = d[0]?.case_id ?? "";
        loading = false;
        return;
      } catch (e) {
        if (i === retries - 1) {
          error = `Cannot load case data (${e.name === "AbortError" ? "timeout" : e.message}). ` +
            `If using server.py, restart it; otherwise run scripts/sync_dashboard_data.py and rebuild.`;
          loading = false;
        } else await new Promise((res) => setTimeout(res, 1500));
      }
    }
  }
  loadAll();

  const tabs = [
    ["overview", "◎", "Overview"],
    ["case", "▤", "Cases"],
    ["compare", "◫", "Rule vs LLM"],
    ["demo", "▶", "Demo run"],
  ];
</script>

<div class="shell">
  <aside class="sidebar">
    <div class="brand"><span class="logo">◈</span><span>FraudScope AI<small>HHGOA investigations</small></span></div>
    <div class="nav-label">Main menu</div>
    {#each tabs as [id, ico, label]}
      <button class="nav-item" class:active={tab === id} onclick={() => (tab = id)}>
        <span class="ico">{ico}</span>{label}
      </button>
    {/each}
    <div class="nav-label">Source</div>
    <button class="nav-item" class:active={variant === "rule"} onclick={() => (variant = "rule")}><span class="ico">⧉</span>Rule-based</button>
    <button class="nav-item" class:active={variant === "llm"} onclick={() => (variant = "llm")}><span class="ico">✦</span>LLM + Laya</button>
  </aside>

  <div class="main">
    <div class="topbar">
      <div><h1>Fraud investigations</h1><div class="sub">Evidence-cited case dossiers with policy actions</div></div>
    </div>

    {#if error}<div class="card error">{error} <button class="btn" onclick={loadAll}>Retry</button></div>{/if}
    {#if loading && !index.length}<div class="card"><p class="meta">Loading case index…</p></div>{/if}

    {#if tab === "overview" && index.length}
      <Overview {index} source={variant} />
    {/if}

    {#if tab === "case" && index.length}
    <div class="toolbar">
      <Select.Root type="single" bind:value={caseId}>
        <Select.Trigger class="w-56"><Select.Value placeholder="case" /></Select.Trigger>
        <Select.Content>
          {#each index as c}<Select.Item value={c.case_id}>{c.case_id} · {c.trigger}</Select.Item>{/each}
        </Select.Content>
      </Select.Root>
    </div>
      {#key caseId + variant}<CaseDetail {caseId} {variant} />{/key}
    {/if}

  {#if tab === "compare" && index.length}
    <Compare {index} onpick={(id) => { caseId = id; tab = "case"; }} />
  {/if}

  {#if tab === "demo" && index.length}
    <DemoRun {index} />
  {/if}
  </div>
</div>
