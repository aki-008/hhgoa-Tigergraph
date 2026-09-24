<script>
  import { loadIndex } from "./lib/data.js";
  import Overview from "./lib/Overview.svelte";
  import CaseDetail from "./lib/CaseDetail.svelte";
  import Compare from "./lib/Compare.svelte";
  import LiveRun from "./lib/LiveRun.svelte";

  let index = $state([]);
  let error = $state("");
  let tab = $state("overview"); // overview | case | compare | live
  let caseId = $state("HHG-002");
  let variant = $state("rule"); // rule | llm

  loadIndex().then(
    (d) => {
      index = d;
      if (!d.some((c) => c.case_id === caseId)) caseId = d[0]?.case_id ?? "";
    },
    (e) => (error = e.message),
  );
</script>

<main>
  <header>
    <h1>HHGOA Fraud Investigations</h1>
    <nav>
      <button class:active={tab === "overview"} onclick={() => (tab = "overview")}>Overview</button>
      <button class:active={tab === "case"} onclick={() => (tab = "case")}>Case</button>
      <button class:active={tab === "compare"} onclick={() => (tab = "compare")}>Rule vs LLM</button>
      <button class:active={tab === "live"} onclick={() => (tab = "live")}>Live run</button>
    </nav>
  </header>

  {#if error}<div class="card error">{error}</div>{/if}

  {#if tab === "overview" && index.length}
    <div class="toolbar">
      <label><input type="radio" name="src" value="rule" bind:group={variant} /> rule-based</label>
      <label><input type="radio" name="src" value="llm" bind:group={variant} /> LLM</label>
    </div>
    <Overview {index} source={variant} />
  {/if}

  {#if tab === "case" && index.length}
    <div class="toolbar">
      <select bind:value={caseId}>
        {#each index as c}<option value={c.case_id}>{c.case_id}</option>{/each}
      </select>
      <label><input type="radio" name="v" value="rule" bind:group={variant} /> rule-based</label>
      <label><input type="radio" name="v" value="llm" bind:group={variant} /> LLM</label>
    </div>
    {#key caseId + variant}<CaseDetail {caseId} {variant} />{/key}
  {/if}

  {#if tab === "compare" && index.length}
    <Compare {index} />
  {/if}

  {#if tab === "live" && index.length}
    <div class="toolbar">
      <select bind:value={caseId}>
        {#each index as c}<option value={c.case_id}>{c.case_id}</option>{/each}
      </select>
    </div>
    {#key caseId}<LiveRun {caseId} />{/key}
  {/if}
</main>

<style>
  main { max-width: 1000px; margin: 0 auto; padding: 1rem; }
  header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
  h1 { font-size: 1.3rem; margin: 0; }
  nav { display: flex; gap: 0.4rem; }
  button { background: #2a2f3a; color: inherit; border: 1px solid #3a4152; border-radius: 6px; padding: 0.35rem 0.8rem; cursor: pointer; }
  button.active { background: #4f6bed; border-color: #4f6bed; color: #fff; }
  .toolbar { display: flex; gap: 1rem; align-items: center; margin-bottom: 1rem; font-size: 0.9rem; }
  select { background: #2a2f3a; color: inherit; border: 1px solid #3a4152; border-radius: 6px; padding: 0.3rem 0.5rem; font-family: monospace; }
</style>
