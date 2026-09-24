<script>
  let { caseId } = $props();
  let events = $state([]);
  let live = $state(true);
  let error = $state("");
  let timer = $state(null);

  async function poll() {
    try {
      const r = await fetch(`cases/${caseId}.trace.jsonl`, { cache: "no-store" });
      if (!r.ok) {
        error = `No trace for ${caseId} yet — run scripts/investigate.py --case ${caseId}`;
        return;
      }
      error = "";
      const text = await r.text();
      events = text
        .trim()
        .split("\n")
        .filter(Boolean)
        .map((l) => JSON.parse(l));
    } catch (e) {
      error = String(e.message || e);
    }
  }

  $effect(() => {
    poll();
    if (timer) clearInterval(timer);
    if (live) timer = setInterval(poll, 2000);
    return () => timer && clearInterval(timer);
  });
  $effect(() => caseId && poll());

  const totals = $derived(
    events.reduce(
      (s, e) => ({
        prompt: s.prompt + (e.tokens?.prompt || 0),
        completion: s.completion + (e.tokens?.completion || 0),
      }),
      { prompt: 0, completion: 0 },
    ),
  );
</script>

<div class="card">
  <div class="head">
    <h3>Live run — {caseId}</h3>
    <label><input type="checkbox" bind:checked={live} /> live poll (2s)</label>
    <button onclick={poll}>refresh</button>
    <span class="meta">
      {events.length} steps · {totals.prompt + totals.completion} tokens
      ({totals.prompt} prompt / {totals.completion} completion)
    </span>
  </div>
  {#if error}<p class="meta">{error}</p>{/if}
  <ol class="feed">
    {#each events as e}
      <li>
        <span class="t">{e.t?.slice(11, 19) ?? ""}</span>
        <span class="step">{e.step}</span>
        <span class="msg">{e.msg}</span>
        {#if e.tokens?.prompt + e.tokens?.completion > 0}
          <span class="meta">+{e.tokens.prompt + e.tokens.completion} tok</span>
        {/if}
      </li>
    {/each}
  </ol>
  <p class="meta">
    Tip: run <code>python scripts/investigate.py --case {caseId}</code> (or
    <code>llm_investigate.py</code>) in a terminal and watch this feed update —
    trigger → retrieve → assess → actions → memorize.
  </p>
</div>

<style>
  .head { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
  .feed { max-height: 420px; overflow-y: auto; padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.86rem; }
  .feed li { display: flex; gap: 0.5rem; align-items: baseline; border-bottom: 1px solid #2a2f3a; padding-bottom: 0.25rem; }
  .t { font-family: monospace; opacity: 0.6; }
  .step { background: #4f6bed; color: #fff; border-radius: 4px; padding: 0 0.4rem; font-size: 0.75rem; white-space: nowrap; }
  .msg { flex: 1; }
  button { background: #2a2f3a; color: inherit; border: 1px solid #3a4152; border-radius: 6px; padding: 0.25rem 0.7rem; cursor: pointer; }
</style>
