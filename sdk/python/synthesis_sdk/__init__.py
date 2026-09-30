"""
synthesis-sdk — minimal, dependency-free Python client for the SYNTHESIS
Evidence-Carrying Causal World Model (vision §44: SDK / API / Validation API).

    from synthesis_sdk import SynthesisClient
    c = SynthesisClient("http://localhost:8000")
    print(c.state()["model_calibration_pct"])
    for ev in c.events():
        cone = c.impact_cone(ev["id"])
    ok, n, head = c.verify_chain()      # independent integrity check

The SDK never hides uncertainty: responses are returned exactly as the
platform emits them — evidence ids, confidence, falsifiers and all.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request

__version__ = "0.1.0"
GENESIS = "0" * 64


class SynthesisClient:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 10.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    # ---- transport ------------------------------------------------------
    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read())

    def _post(self, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    # ---- world state ----------------------------------------------------
    def state(self):                     return self._get("/api/state")
    def feed(self, limit: int = 12):     return self._get(f"/api/feed?limit={limit}")
    def events(self):                    return self._get("/api/events")
    def event(self, event_id: str):      return self._get(f"/api/events/{event_id}")
    def impact_cone(self, event_id: str):return self._get(f"/api/events/{event_id}/cone")
    def hypotheses(self, event_id: str): return self._get(f"/api/events/{event_id}/hypotheses")
    def hypothesis(self, hyp_id: str):   return self._get(f"/api/hypotheses/{hyp_id}")
    def evidence(self, ev_id: str):      return self._get(f"/api/evidence/{ev_id}")
    def contradictions(self):            return self._get("/api/contradictions")
    def forecasts(self):                 return self._get("/api/forecasts")
    def ledger(self):                    return self._get("/api/ledger")
    def calibration(self):               return self._get("/api/calibration")
    def agents(self):                    return self._get("/api/agents")
    def ingest_status(self):             return self._get("/api/ingest/status")

    # ---- analysis actions -------------------------------------------------
    def challenge(self, hyp_id: str):
        """Invoke the Adversarial Agent against a hypothesis."""
        return self._post(f"/api/hypotheses/{hyp_id}/challenge")

    def counterfactual(self, event_id: str, duration_hours: int = 168,
                       recovery: str = "normal"):
        """Branch the causal model under altered assumptions."""
        return self._post("/api/counterfactual", {
            "event_id": event_id, "duration_hours": duration_hours,
            "recovery": recovery})

    # ---- validation API ----------------------------------------------------
    def export_chain(self) -> str:
        with urllib.request.urlopen(self.base + "/api/ledger/export",
                                    timeout=self.timeout) as r:
            return r.read().decode()

    def verify_chain(self) -> tuple[bool, int, str]:
        """Re-verify the tamper-evident evidence chain client-side,
        without trusting the server's own arithmetic.
        Returns (valid, record_count, head_hash)."""
        lines = self.export_chain().strip().split("\n")[1:]     # skip header
        prev, n = GENESIS, 0
        for line in lines:
            seq, prev_hash, stored, payload = line.split("\t", 3)
            if prev_hash != prev:
                return False, n, prev
            computed = hashlib.sha256(f"{prev_hash}|{payload}".encode()).hexdigest()
            if computed != stored:
                return False, n, prev
            prev, n = stored, n + 1
        return True, n, prev
