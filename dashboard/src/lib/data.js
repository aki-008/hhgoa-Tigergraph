// Data layer: live fetch first (fresh runs), bundled snapshot fallback
// (works offline / misconfigured static hosting), hard error last.
import { CASE_FILES, CASE_INDEX } from "./casefiles.js";

async function fetchJson(path) {
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), 15000);
  try {
    const r = await fetch(path, { cache: "no-store", signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(to);
  }
}

export async function loadIndex() {
  try {
    return await fetchJson("cases/index.json");
  } catch (_) {
    if (CASE_INDEX?.length) return CASE_INDEX;
    throw new Error("index.json missing and no bundled fallback — run scripts/sync_dashboard_data.py");
  }
}
export async function loadCase(id, variant) {
  const key = `${id}${variant === "llm" ? ".llm" : ""}`;
  try {
    return await fetchJson(`cases/${key}.json`);
  } catch (_) {
    if (CASE_FILES[key]) return CASE_FILES[key];
    return null;
  }
}
export const verdictColor = (v) =>
  v === "fraud" ? "#e5484d" : v === "legitimate" ? "#30a46c" : "#f5a524";
