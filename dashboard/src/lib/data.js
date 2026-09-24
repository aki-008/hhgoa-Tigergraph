// Data layer: index + per-case files from public/cases/
export async function loadIndex() {
  const r = await fetch("cases/index.json");
  if (!r.ok) throw new Error("index.json missing — run scripts/sync_dashboard_data.py");
  return r.json();
}
export async function loadCase(id, variant) {
  const suffix = variant === "llm" ? ".llm.json" : ".json";
  const r = await fetch(`cases/${id}${suffix}`);
  if (!r.ok) return null;
  return r.json();
}
export const verdictColor = (v) =>
  v === "fraud" ? "#e5484d" : v === "legitimate" ? "#30a46c" : "#f5a524";
