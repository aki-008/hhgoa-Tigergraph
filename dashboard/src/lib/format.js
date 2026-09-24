// Inline rich-text segmentation for investigation prose.
// Splits plain strings into styled segments: amounts, IDs, risk, dates.
const PATTERNS = [
  { kind: "amount", re: /\$[\d,]+(?:\.\d{1,2})?/g },
  { kind: "txn", re: /\bT\d{5,}\b/g },
  { kind: "card", re: /\bC\d{4,}-K\d\b/g },
  { kind: "customer", re: /\bC\d{4,}\b/g },
  { kind: "case", re: /\b(?:HHG-\d+|CC-\d+)\b/g },
  { kind: "risk", re: /\brisk\s*(?:score\s*)?(?:of\s*|is\s*|=|:)?\s*0?\.\d+/gi },
  { kind: "prob", re: /\bp\s*=\s*0?\.\d+/g },
  { kind: "date", re: /\b\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?\b/g },
  { kind: "pct", re: /\b\d+(?:\.\d+)?x\b/g },
];

export function segment(text) {
  const s = String(text ?? "");
  const hits = [];
  for (const { kind, re } of PATTERNS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(s))) hits.push({ kind, start: m.index, end: m.index + m[0].length, text: m[0] });
  }
  hits.sort((a, b) => a.start - b.start || b.end - a.end);
  const out = [];
  let pos = 0;
  for (const h of hits) {
    if (h.start < pos) continue; // overlapping: first (longest) wins
    if (h.start > pos) out.push({ kind: "text", text: s.slice(pos, h.start) });
    out.push(h);
    pos = h.end;
  }
  if (pos < s.length) out.push({ kind: "text", text: s.slice(pos) });
  return out;
}

export function sentences(text) {
  return String(text ?? "")
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}
