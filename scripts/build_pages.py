#!/usr/bin/env python3
"""Build the static GitHub Pages edition of the SYNTHESIS console.

Boots two real, peered SYNTHESIS nodes, lets the world evolve long enough for
the watchpoint engine to fire, contradictions to resolve and cross-node
reviews to complete — then freezes every read endpoint into ./data/*.json and
packages the PWA into dist/pages/.

The published site is therefore not a mock: it is a genuine snapshot produced
by the same engine, and the web client falls back to it automatically when no
live API is present (see api() in web/app.js).

Usage:  python scripts/build_pages.py            # full-fidelity (~150 s wait)
        SNAPSHOT_WAIT=5 python scripts/...       # fast build for smoke tests
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "pages"
PORT_A, PORT_B = 8123, 8124
BASE = f"http://127.0.0.1:{PORT_A}"
WAIT = int(os.environ.get("SNAPSHOT_WAIT", "150"))

# every GET the web client can issue (query strings resolved to defaults)
FIXED = [
    "/api/state", "/api/events", "/api/contradictions", "/api/ledger",
    "/api/calibration", "/api/feed?limit=14", "/api/agents",
    "/api/security/status", "/api/audit?limit=25",
    "/api/federation/status", "/api/federation/reviews", "/api/ingest/status",
]


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())


def post(url: str, payload: dict):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def static_name(path: str) -> str:
    return path.removeprefix("/api/").split("?")[0].replace("/", "__") + ".json"


def spawn(port: int, name: str, seed: str) -> subprocess.Popen:
    env = {**os.environ, "SYNTHESIS_NODE_NAME": name, "SYNTHESIS_NODE_SEED": seed}
    env.pop("SYNTHESIS_ADMIN_KEY", None)          # open mode: script peers freely
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env, start_new_session=True)


def wait_ready(port: int) -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2):
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"node on :{port} never became ready")


def main() -> None:
    print(f"[pages] booting two peered nodes (snapshot wait: {WAIT}s)")
    a = spawn(PORT_A, "node-pages", "demo-pages")
    b = spawn(PORT_B, "node-pages-peer", "demo-pages-peer")
    try:
        wait_ready(PORT_A)
        wait_ready(PORT_B)
        post(f"http://127.0.0.1:{PORT_A}/api/federation/peers",
             {"url": f"http://127.0.0.1:{PORT_B}"})
        post(f"http://127.0.0.1:{PORT_B}/api/federation/peers",
             {"url": f"http://127.0.0.1:{PORT_A}"})
        print("[pages] peered A<->B; letting the world evolve …")
        for done in range(0, WAIT, 30):
            time.sleep(min(30, WAIT - done))
            print(f"[pages]   … {min(done + 30, WAIT)}/{WAIT}s")

        data: dict[str, object] = {}
        for path in FIXED:
            data[static_name(path)] = get(path)

        for evt in data["events.json"]:
            eid = evt["id"]
            for sub in (f"/api/events/{eid}", f"/api/events/{eid}/cone",
                        f"/api/events/{eid}/hypotheses"):
                data[static_name(sub)] = get(sub)

        hyp_ids = {h["id"]
                   for k, v in list(data.items()) if k.endswith("__hypotheses.json")
                   for h in v}
        for hid in sorted(hyp_ids):
            data[static_name(f"/api/hypotheses/{hid}")] = get(f"/api/hypotheses/{hid}")

        # evidence: fixpoint over every obs_* id referenced anywhere
        seen: set[str] = set()
        for _ in range(3):
            ids = set(re.findall(r"obs_\d+", json.dumps(list(data.values())))) - seen
            if not ids:
                break
            for oid in sorted(ids):
                seen.add(oid)
                try:
                    data[static_name(f"/api/evidence/{oid}")] = get(f"/api/evidence/{oid}")
                except Exception:
                    pass                              # referenced but not a record

        # ledger/audit TSV exports so the download buttons keep working
        exports = {}
        for name, path in [("api/ledger/export", "/api/ledger/export"),
                           ("api/audit/export", "/api/audit/export")]:
            with urllib.request.urlopen(BASE + path, timeout=10) as r:
                exports[name] = r.read()
    finally:
        for p in (a, b):
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                pass

    # ---- package -----------------------------------------------------------
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "web", DIST)
    (DIST / ".nojekyll").write_text("")
    ddir = DIST / "data"
    ddir.mkdir()
    for name, payload in data.items():
        (ddir / name).write_text(json.dumps(payload, ensure_ascii=False))
    (ddir / "meta.json").write_text(json.dumps({
        "built_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "note": ("Frozen snapshot produced by the real SYNTHESIS engine "
                 "(two peered nodes). Run a node for live streams."),
    }))
    for rel, blob in exports.items():
        out = DIST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)

    n_ev = len(list(ddir.glob("evidence__*.json")))
    print(f"[pages] wrote {len(data)} JSON snapshots ({n_ev} evidence records) "
          f"+ 2 TSV exports -> {DIST}")


if __name__ == "__main__":
    main()
