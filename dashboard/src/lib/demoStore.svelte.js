// Shared demo-run state: lives outside any component so tab switches
// never reset an in-progress run. All async loops keep referencing this
// module state, so playback/polling continues while the UI is remounted.
export const SOURCES = [
  { id: "casefile", label: "Case file", ico: "▤" },
  { id: "tigergraph", label: "TigerGraph", ico: "◈" },
  { id: "mcp", label: "MCP tools", ico: "⛭" },
  { id: "memory", label: "Case memory", ico: "❖" },
  { id: "policy", label: "Policy engine", ico: "⚖" },
  { id: "judge", label: "LLM judge", ico: "✦" },
  { id: "desk", label: "Actors & scribe", ico: "✎" },
];
// trace step -> source node
export function route(e) {
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
}
export const KIND = { trigger: "discovery", retrieve: "mcp", traverse: "traversal", memory: "discovery",
  assess: "switching", llm_judge: "switching", laya_decide: "switching",
  evidence_request: "clues", action: "clues", memorize: "clues", done: "finalize" };

export const demo = $state({
  variant: "rule",
  running: false,
  speedArr: [1],
  qi: 0,
  feed: [],
  active: null,
  doneCases: [],
  tokens: { prompt: 0, completion: 0 },
  stopFlag: false,
  mode: "replay", // replay | live (live needs python server.py)
  serverUp: false,
  serverCase: null,
  liveCase: "all",
});

let probing = false;
export async function probeServer() {
  try {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw 0;
    const s = await r.json();
    const was = demo.serverUp;
    demo.serverUp = true;
    demo.serverCase = s.case;
    if (!was && !s.running) demo.mode = "live";
    return s;
  } catch (_) {
    demo.serverUp = false;
    demo.serverCase = null;
    return null;
  }
}
export function startProbing() {
  if (probing) return;
  probing = true;
  probeServer();
  setInterval(() => { if (!demo.running) probeServer(); }, 5000);
}

const wait = (ms) => new Promise((res) => setTimeout(res, ms));
const suffix = () => (demo.variant === "llm" ? ".llm" : "");
const pace = (e) => Math.max(120, (e.step === "retrieve" ? 260 : 750) / (demo.speedArr[0] ?? 1));

async function loadTrace(id) {
  const r = await fetch(`cases/${id}${suffix()}.trace.jsonl`, { cache: "no-store" });
  if (!r.ok) return null;
  return (await r.text()).trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
}
function pushEvent(id, e) {
  demo.active = route(e);
  const pt = e.tokens?.prompt || 0, ct = e.tokens?.completion || 0;
  demo.tokens = { prompt: demo.tokens.prompt + pt, completion: demo.tokens.completion + ct };
  demo.feed = [...demo.feed.slice(-200),
    { caseId: id, step: e.step, msg: e.msg, kind: KIND[e.step] || "mcp",
      tokens: { prompt: pt, completion: ct } }];
}
async function fetchDossier(id) {
  try {
    const r = await fetch(`cases/${id}${suffix()}.json`, { cache: "no-store" });
    if (r.ok) {
      const d = await r.json();
      if (!demo.doneCases.some((x) => x.id === id))
        demo.doneCases = [...demo.doneCases, { id, verdict: d.case.verdict, p: d.case.fraud_probability }];
    }
  } catch (_) { /* artifact not written yet */ }
}

// ---- live mode: real execution via server.py ----
export async function liveRun(index) {
  if (demo.running) return;
  const ids = demo.liveCase === "all" ? index.map((c) => c.case_id) : [demo.liveCase];
  const start = await fetch("api/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: demo.liveCase === "all" ? "all" : demo.liveCase, variant: demo.variant }),
  });
  if (start.status === 409) {
    demo.feed = [...demo.feed, { caseId: "—", step: "done", msg: "server busy — another run in progress", kind: "finalize", tokens: {} }];
    return;
  }
  demo.running = true;
  demo.stopFlag = false;
  demo.feed = [];
  demo.doneCases = [];
  demo.tokens = { prompt: 0, completion: 0 };
  demo.active = null;
  const seenCount = {};
  let finished = false;
  while (!finished && !demo.stopFlag) {
    await wait(1500);
    let st = { running: true, case: null };
    try {
      st = await (await fetch("api/status", { cache: "no-store" })).json();
      demo.serverCase = st.case;
    } catch (_) { /* server went away */ }
    for (const id of ids) {
      try {
        const tr = await (await fetch(
          `api/trace?case=${id}&variant=${demo.variant}`, { cache: "no-store" })).json();
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
  demo.running = false;
  demo.active = null;
}
export async function liveStop() {
  demo.stopFlag = true;
  try { await fetch("api/stop", { method: "POST" }); } catch (_) { /* noop */ }
}
// ---- replay mode: timed playback of recorded traces ----
export async function runAll(index) {
  if (demo.running) return;
  demo.running = true;
  demo.stopFlag = false;
  demo.feed = [];
  demo.doneCases = [];
  demo.tokens = { prompt: 0, completion: 0 };
  demo.active = null;
  for (; demo.qi < index.length && !demo.stopFlag; demo.qi++) {
    await runCase(index[demo.qi].case_id);
  }
  if (!demo.stopFlag) demo.qi = 0;
  demo.running = false;
  demo.active = null;
}
export async function runCase(id) {
  const events = await loadTrace(id);
  if (!events) {
    demo.feed = [...demo.feed, { caseId: id, step: "done", msg: "no trace file — run the agent CLI first", kind: "finalize", tokens: {} }];
    return;
  }
  for (const e of events) {
    if (demo.stopFlag) return;
    pushEvent(id, e);
    await wait(pace(e));
  }
  await fetchDossier(id);
}
export function stop() { demo.stopFlag = true; }
export function reset() {
  demo.qi = 0;
  demo.feed = [];
  demo.doneCases = [];
  demo.tokens = { prompt: 0, completion: 0 };
  demo.active = null;
}
