"""
SYNTHESIS — API gateway (MVP).

Serves the evidence-carrying causal world model API and the installable
web client (PWA). Every response is analysis/decision-support only —
SYNTHESIS is not an autonomous decision-maker.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .world import WORLD, MODEL_VERSION
from .ingest import INGESTOR
from .federation import NODE
from . import security

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="SYNTHESIS",
    description="The Evidence-Carrying Causal World Model — MVP vertical slice.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        client = request.client.host if request.client else "unknown"
        # 1. rate limiting (§24)
        ok, _remaining = security.LIMITER.allow(client, request.method)
        if not ok:
            security.AUDIT.record(client, "rate_limited", path)
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        # 2. authentication for privileged routes (§24) — enforced only when
        #    SYNTHESIS_ADMIN_KEY is set; mode is always reported honestly
        if request.method == "POST" and path.startswith(security.PRIVILEGED_PREFIXES):
            if not security.check_key(request.headers.get("x-api-key", "")):
                security.AUDIT.record(client, "auth_denied", path)
                return JSONResponse({"detail": "invalid or missing X-Api-Key"}, status_code=401)
            security.AUDIT.record(client, "privileged_call", path)
        elif request.method == "POST":
            security.AUDIT.record(client, "analysis_call", path)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return resp


@app.on_event("startup")
async def start_live_ingest():
    import asyncio
    asyncio.create_task(INGESTOR.run())
    asyncio.create_task(NODE.run())


# ------------------------------------------------------ federation (§43) ----

class PeerRequest(BaseModel):
    url: str = Field(min_length=8, max_length=200)


@app.get("/api/federation/identity")
def federation_identity():
    """This node's provable identity: node_id = sha256(pubkey)[:12]."""
    return NODE.identity.to_dict()


@app.get("/api/federation/observations")
def federation_observations():
    """Ed25519-signed observation bundle for peers (SYNTHESIS Protocol v0)."""
    return NODE.outbound_bundle()


@app.get("/api/federation/status")
def federation_status():
    return NODE.status()


@app.get("/api/federation/hypotheses")
def federation_hypotheses():
    """Signed bundle of active hypotheses (protocol v0.5) — shared as
    claims-with-falsifiers for peer adversarial review, never as facts."""
    return NODE.outbound_hypotheses()


@app.get("/api/federation/reviews")
def federation_reviews():
    """Cross-node adversarial reviews this node performed on peer hypotheses."""
    return {"reviews": NODE.reviews[::-1],
            "principle": ("Peer hypotheses are never merged — they are reviewed. "
                          "Disagreement between nodes is information.")}


@app.post("/api/federation/peers")
def federation_add_peer(req: PeerRequest):
    try:
        peer = NODE.add_peer(req.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    NODE.sync_peer(peer)
    return vars(peer)


@app.post("/api/federation/sync")
def federation_sync():
    NODE.sync_all()
    return NODE.status()


# ---------------------------------------------------------------- API ----

@app.get("/api/ingest/status")
def ingest_status():
    """Live Data Adapter status — LIVE when real sources are reachable,
    SIMULATION ONLY otherwise (controlled failure, vision §51)."""
    return INGESTOR.status()


@app.get("/api/state")
def state():
    return WORLD.global_state()


@app.get("/api/feed")
def feed(limit: int = 12):
    return WORLD.feed(min(max(limit, 1), 50))


@app.get("/api/events")
def events():
    WORLD.tick()
    return list(WORLD.events.values())


@app.get("/api/events/{event_id}")
def event(event_id: str):
    WORLD.tick()
    ev = WORLD.events.get(event_id)
    if not ev:
        raise HTTPException(404, "unknown event")
    return ev


@app.get("/api/events/{event_id}/cone")
def cone(event_id: str):
    WORLD.tick()
    c = WORLD.cones.get(event_id)
    if not c:
        raise HTTPException(404, "no impact cone for event")
    return c


@app.get("/api/events/{event_id}/hypotheses")
def event_hypotheses(event_id: str):
    WORLD.tick()
    hs = [h for h in WORLD.hypotheses.values() if h["event_id"] == event_id]
    if not hs:
        raise HTTPException(404, "no hypotheses for event")
    return sorted(hs, key=lambda h: h["label"])


@app.get("/api/hypotheses/{hyp_id}")
def hypothesis(hyp_id: str):
    WORLD.tick()
    h = WORLD.hypotheses.get(hyp_id)
    if not h:
        raise HTTPException(404, "unknown hypothesis")
    out = dict(h)
    out["evidence"] = [WORLD.evidence[e] for e in h["evidence_ids"] if e in WORLD.evidence]
    out["counter_evidence"] = [WORLD.evidence[e] for e in h["counter_evidence_ids"] if e in WORLD.evidence]
    return out


@app.post("/api/hypotheses/{hyp_id}/challenge")
def challenge(hyp_id: str):
    if hyp_id not in WORLD.hypotheses:
        raise HTTPException(404, "unknown hypothesis")
    return WORLD.challenge(hyp_id)


@app.get("/api/evidence/{ev_id}")
def evidence(ev_id: str):
    WORLD.tick()
    e = WORLD.evidence.get(ev_id)
    if not e:
        raise HTTPException(404, "unknown evidence")
    return e


@app.get("/api/contradictions")
def contradictions():
    WORLD.tick()
    return list(WORLD.contradictions.values())


@app.get("/api/forecasts")
def forecasts():
    WORLD.tick()
    return list(WORLD.forecasts.values())


@app.get("/api/ledger")
def ledger():
    WORLD.tick()
    resolved = [f for f in WORLD.forecasts.values() if f["status"] != "open"]
    return {
        "resolved_forecasts": resolved,
        "open_forecasts": [f for f in WORLD.forecasts.values() if f["status"] == "open"],
        "model_version": MODEL_VERSION,
    }


@app.get("/api/ledger/export", response_class=PlainTextResponse)
def ledger_export():
    """Tamper-evident evidence chain (TSV). Verify with tools/ledgercheck (C)
    or scripts/verify_chain.sh."""
    WORLD.tick()
    return WORLD.chain.export_tsv()


@app.get("/api/calibration")
def calibration():
    return WORLD.calibration()


class CounterfactualRequest(BaseModel):
    event_id: str
    duration_hours: int = Field(ge=1, le=2160, default=168)
    recovery: str = Field(default="normal", pattern="^(immediate|normal|slow)$")


@app.post("/api/counterfactual")
def counterfactual(req: CounterfactualRequest):
    if req.event_id not in WORLD.cones:
        raise HTTPException(404, "unknown event")
    return WORLD.counterfactual(req.event_id, req.duration_hours, req.recovery)


@app.get("/api/agents")
def agents():
    WORLD.tick()
    roster = [
        ("Climate Agent", "environmental & weather signals", "analyzing VARDA-07 track ensemble"),
        ("Maritime Agent", "vessels, ports, routes", "tracking 11 diversions + SG dwell anomaly"),
        ("Energy Agent", "grids, demand, dependencies", "watching N-1 margin, Nordic zone"),
        ("Infrastructure Agent", "critical infrastructure links", "NH-16 closure exposure model"),
        ("Trade Agent", "goods movement, economic deps", "Panama draft re-routing economics"),
        ("Causal Agent", "constructs candidate causal chains", "4 active impact cones"),
        ("Forecasting Agent", "testable forecasts", "5 forecasts under observation"),
        ("Verification Agent", "claims vs evidence", "3 contradiction objects open"),
        ("Adversarial Agent", "attacks current explanations", "standing by — invoke via Challenge"),
        ("Calibration Agent", "historical performance", f"{len(WORLD.history)} outcomes scored"),
    ]
    return [{
        "name": n, "scope": s, "current_task": t,
        "permissions": {"read": "scoped datasets", "write": "proposals only",
                        "cannot": ["modify policy", "deploy software", "delete evidence"]},
        "sandboxed": True, "status": "active",
    } for n, s, t in roster]


@app.get("/healthz")
def healthz():
    return {"ok": True, "model_version": MODEL_VERSION}


# ------------------------------------------------------- security (§24) ----

@app.get("/api/security/status")
def security_status():
    return security.status()


@app.get("/api/audit")
def audit_tail(limit: int = 50):
    """Tamper-evident audit trail — privileged actions and denials."""
    return {"entries": security.AUDIT.tail(min(max(limit, 1), 200)),
            "chain_head": security.AUDIT.chain.head,
            "chain_length": len(security.AUDIT.chain.records)}


@app.get("/api/audit/export", response_class=PlainTextResponse)
def audit_export():
    """Audit hash chain (TSV) — verifiable with the same C tool as evidence:
    curl -s <host>/api/audit/export | ./tools/ledgercheck/ledgercheck"""
    return security.AUDIT.chain.export_tsv()


@app.websocket("/ws")
async def live_push(ws: WebSocket):
    """Real-time push of global state + evidence stream (no polling needed).
    Read-only: the socket carries world state outward; it accepts no commands —
    clients cannot mutate anything through this channel (least privilege, §19)."""
    import asyncio
    await ws.accept()
    try:
        while True:
            WORLD.tick()
            await ws.send_json({
                "type": "world_update",
                "state": WORLD.global_state(),
                "feed": WORLD.feed(14),
                "ingest_mode": INGESTOR.status()["mode"],
            })
            await asyncio.sleep(3)
    except (WebSocketDisconnect, RuntimeError):
        pass


# ------------------------------------------------------------- static ----

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
