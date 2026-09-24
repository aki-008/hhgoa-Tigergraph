"""Sync agent outputs into dashboard/public/cases + index.json.
Run: python scripts/sync_dashboard_data.py
"""
import json
import shutil
from pathlib import Path

BASE = Path(__file__).parent.parent
DST = BASE / "dashboard" / "public" / "cases"
DST.mkdir(parents=True, exist_ok=True)

index = []
for fp in sorted((BASE / "cases").glob("HHG-*.json")):
    if fp.suffixes[-2:] == [".llm", ".json"]:
        continue
    if fp.name.endswith(".brief.json"):
        continue
    d = json.loads(fp.read_text(encoding="utf-8"))
    cid = d["case_id"]
    shutil.copy(fp, DST / fp.name)
    llm_fp = BASE / "cases" / f"{cid}.llm.json"
    llm = json.loads(llm_fp.read_text(encoding="utf-8")) if llm_fp.exists() else None
    if llm:
        shutil.copy(llm_fp, DST / llm_fp.name)
    c, case = d["case"], llm["case"] if llm else {}
    index.append({
        "case_id": cid,
        "rule": {"verdict": c["verdict"], "p": c["fraud_probability"],
                 "pattern": c["pattern"], "exposure": c["exposure_usd"],
                 "sar": d["sar"]["file"]},
        "llm": ({"verdict": case["verdict"], "p": case["fraud_probability"],
                 "pattern": case["pattern"], "exposure": case["exposure_usd"],
                 "sar": llm["sar"]["file"]} if llm else None),
    })
(DST / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
print(f"synced {len(index)} cases -> {DST}")
