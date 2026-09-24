"""FraudScope demo server (stdlib only).

Serves the dashboard build + LIVE repo data, and executes real agent runs:
  GET  /                        -> dashboard/dist/index.html (+ static assets)
  GET  /cases/<file>            -> live repo cases/ (fresh traces + dossiers)
  GET  /api/status              -> {"running": bool, "case": id|null}
  POST /api/run                 -> {"case_id"|"all", "variant": "rule"|"llm"}
  POST /api/stop                -> stop after the current case
  GET  /api/trace?case=X&variant=rule|llm -> {"events": [...]}

Run:  python server.py [--port 8000]
Then: http://127.0.0.1:8000  (Demo run tab -> live mode)

Localhost only. Secrets stay server-side in .env; the browser never sees keys.
"""
import argparse
import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DIST = ROOT / "dashboard" / "dist"
CASES = ROOT / "cases"

_state = {"running": False, "case": None, "stop": False}
_lock = threading.Lock()


def run_case_sync(case_id, variant):
    script = "scripts/investigate.py" if variant == "rule" else "scripts/llm_investigate.py"
    cmd = [sys.executable, script, "--case", case_id, "--out-dir", "cases"]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    return p.returncode, (p.stdout or "")[-500:] + (p.stderr or "")[-500:]


def worker(case_ids, variant):
    with _lock:
        _state["running"] = True
        _state["stop"] = False
    try:
        for cid in case_ids:
            with _lock:
                if _state["stop"]:
                    break
                _state["case"] = cid
            code, tail = run_case_sync(cid, variant)
            print(f"[worker] {cid} exit={code} {tail[-120:]}", flush=True)
    finally:
        with _lock:
            _state["running"] = False
            _state["case"] = None
            _state["stop"] = False


def case_list():
    import csv
    with open(CASES.parent / "data" / "case_pack.csv", newline="", encoding="utf-8") as f:
        return [r["case_id"] for r in csv.DictReader(f)]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/status":
            with _lock:
                return self._json({"running": _state["running"], "case": _state["case"]})
        if url.path == "/api/trace":
            q = parse_qs(url.query)
            cid = (q.get("case") or [""])[0]
            variant = (q.get("variant") or ["rule"])[0]
            name = f"{cid}.llm.trace.jsonl" if variant == "llm" else f"{cid}.trace.jsonl"
            fp = CASES / name
            if not fp.exists():
                return self._json({"events": []})
            events = [json.loads(line) for line in
                      fp.read_text(encoding="utf-8").splitlines() if line.strip()]
            return self._json({"events": events[-400:]})
        if url.path.startswith("/cases/"):
            rel = url.path[len("/cases/"):]
            fp = CASES / rel
            if not (fp.is_file() and fp.resolve().is_relative_to(CASES.resolve())):
                # fall back to the dashboard build snapshot (e.g. index.json,
                # which lives in public/cases, not in the live answer dir)
                fp = DIST / "cases" / rel
            if fp.is_file():
                return self._serve_file(fp)
            return self._json({"error": "not found"}, 404)
        # static dashboard build
        rel = url.path.lstrip("/") or "index.html"
        fp = (DIST / rel)
        if fp.is_dir():
            fp = fp / "index.html"
        if fp.is_file() and fp.resolve().is_relative_to(DIST.resolve()):
            return self._serve_file(fp)
        return self._serve_file(DIST / "index.html")

    def _serve_file(self, fp):
        ctype = "application/octet-stream"
        if fp.suffix == ".html":
            ctype = "text/html"
        elif fp.suffix == ".js":
            ctype = "text/javascript"
        elif fp.suffix == ".css":
            ctype = "text/css"
        elif fp.suffix in (".json", ".jsonl"):
            ctype = "application/json"
        elif fp.suffix == ".svg":
            ctype = "image/svg+xml"
        body = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        if url.path == "/api/stop":
            with _lock:
                _state["stop"] = True
            return self._json({"stopping": True})
        if url.path == "/api/run":
            with _lock:
                if _state["running"]:
                    return self._json({"error": "already running", "case": _state["case"]}, 409)
            variant = payload.get("variant", "rule")
            if variant not in ("rule", "llm"):
                return self._json({"error": "variant must be rule|llm"}, 400)
            target = payload.get("case_id", "all")
            ids = case_list() if target in ("all", "", None) else [target]
            known = set(case_list())
            if any(c not in known for c in ids):
                return self._json({"error": "unknown case_id"}, 400)
            threading.Thread(target=worker, args=(ids, variant), daemon=True).start()
            return self._json({"started": True, "cases": ids, "variant": variant})
        return self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if not (DIST / "index.html").exists():
        print("dashboard/dist missing: run `npm run build` in dashboard/ first")
        sys.exit(1)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"FraudScope demo server: http://127.0.0.1:{args.port}  (Demo run tab)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
