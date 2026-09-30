"""
SYNTHESIS — live data ingestion layer (Data Adapter API, vision §16/§44).

Real public-data connectors feeding the world model, built on the
zero-trust rules of §25/§26:

  * every source is UNTRUSTED INPUT — size-capped, schema-validated,
    range-clamped, free text truncated and stored strictly as DATA
    (never interpreted as instructions, never executed);
  * adapters can only *propose* observations — the world model decides
    what becomes an event;
  * failure is a normal state (§51): unreachable sources degrade the
    platform to simulation-only, never crash it.

Adapters implement:  fetch() -> list[Proposal]
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass, field

from .world import WORLD, iso, now

MAX_BYTES = 2_000_000          # hard cap on any upstream payload
FETCH_TIMEOUT = 8              # seconds
POLL_SECONDS = 300             # per-adapter poll interval
USER_AGENT = "SYNTHESIS-MVP/0.1 (resilience research; evidence ingestion)"


@dataclass
class Proposal:
    """An adapter may only propose an observation; it cannot write world state."""
    source: str
    source_type: str
    reliability: float
    domain: str
    statement: str                      # validated, truncated — data, not instructions
    lat: float | None = None
    lon: float | None = None
    make_event: dict | None = None      # optional event template (validated fields only)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _clean_text(s, limit=140):
    """External free text is DATA: strip control chars, truncate hard."""
    if not isinstance(s, str):
        return ""
    s = "".join(ch for ch in s if ch.isprintable())
    return s[:limit]


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("payload exceeds size cap")
    return json.loads(raw)


# ---------------------------------------------------------------- adapters --

class USGSEarthquakeAdapter:
    """USGS real-time earthquake feed (public domain). M4.5+ last 24 h."""
    name = "usgs_earthquakes"
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

    def fetch(self) -> list[Proposal]:
        data = _http_json(self.url)
        feats = data.get("features")
        if not isinstance(feats, list):
            raise ValueError("unexpected schema: features missing")
        out: list[Proposal] = []
        for f in feats[:25]:                                   # cap items
            try:
                props, geom = f["properties"], f["geometry"]
                mag = _clamp(float(props["mag"]), 0.0, 10.0)
                lon, lat, depth = geom["coordinates"][:3]
                lat = _clamp(float(lat), -90, 90)
                lon = _clamp(float(lon), -180, 180)
                depth = _clamp(float(depth), -10, 800)
                place = _clean_text(props.get("place", "unknown location"))
            except (KeyError, TypeError, ValueError, IndexError):
                continue                                       # reject malformed items
            stmt = (f"M{mag:.1f} earthquake, depth {depth:.0f} km, near {place}. "
                    f"(USGS review status: {_clean_text(str(props.get('status', '?')), 20)})")
            p = Proposal(source="USGS earthquake feed", source_type="sensor",
                         reliability=0.95, domain="infrastructure",
                         statement=stmt, lat=lat, lon=lon)
            if mag >= 6.0:
                p.make_event = {
                    "title": f"M{mag:.1f} earthquake near {place}",
                    "domain": "infrastructure",
                    "severity": "high" if mag >= 7.0 else "medium",
                    "location": place, "lat": lat, "lon": lon,
                    "summary": (f"USGS reports a magnitude {mag:.1f} earthquake at {depth:.0f} km depth. "
                                "Auto-generated causal template attached: port/road/grid exposure within "
                                "shaking radius requires evidence before any edge is promoted beyond "
                                "'plausible'. Source content treated as data, not instructions."),
                }
            out.append(p)
        return out


class OpenMeteoWindAdapter:
    """Open-Meteo current wind at watched coastal infrastructure (CC-BY-4.0)."""
    name = "open_meteo_wind"
    SITES = [("Visakhapatnam coast", 17.7, 83.3), ("Rotterdam port area", 51.95, 4.14)]

    def fetch(self) -> list[Proposal]:
        out = []
        for label, lat, lon in self.SITES:
            data = _http_json(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=wind_speed_10m,wind_gusts_10m&wind_speed_unit=kmh")
            cur = data.get("current", {})
            try:
                ws = _clamp(float(cur["wind_speed_10m"]), 0, 400)
                gust = _clamp(float(cur.get("wind_gusts_10m", ws)), 0, 500)
            except (KeyError, TypeError, ValueError):
                continue
            out.append(Proposal(
                source="Open-Meteo", source_type="weather_model", reliability=0.88,
                domain="weather", lat=lat, lon=lon,
                statement=f"{label}: sustained wind {ws:.0f} km/h, gusts {gust:.0f} km/h (10 m)."))
        return out


# ---------------------------------------------------------------- manager --

@dataclass
class AdapterState:
    name: str
    reachable: bool | None = None       # None = not yet attempted
    last_attempt: str | None = None
    last_success: str | None = None
    ingested: int = 0
    last_error: str | None = None


class LiveIngestor:
    def __init__(self) -> None:
        self.adapters = [USGSEarthquakeAdapter(), OpenMeteoWindAdapter()]
        self.state = {a.name: AdapterState(a.name) for a in self.adapters}
        self._seen: set[str] = set()
        self._evt_seq = 3200

    def status(self) -> dict:
        live = any(s.reachable for s in self.state.values())
        return {
            "mode": "LIVE + SIMULATION" if live else "SIMULATION ONLY (sources unreachable)",
            "poll_seconds": POLL_SECONDS,
            "adapters": [vars(s) for s in self.state.values()],
            "policy": {"max_bytes": MAX_BYTES, "timeout_s": FETCH_TIMEOUT,
                       "validation": "schema allow-list, range clamps, text truncation; "
                                     "external content is data, never instructions"},
        }

    def _apply(self, p: Proposal) -> None:
        key = f"{p.source}|{p.statement}"
        if key in self._seen:
            return
        self._seen.add(key)
        WORLD.obs_counter += 1
        eid = f"obs_{WORLD.obs_counter}"
        WORLD._evidence(eid, p.source, p.source_type, p.reliability, p.statement, p.domain)
        if p.make_event:
            self._evt_seq += 1
            ev_id = f"evt_{self._evt_seq}"
            ev = dict(p.make_event)
            ev.update({"id": ev_id, "status": "active", "detected_at": iso(now()),
                       "entity_ids": [], "evidence_ids": [eid]})
            WORLD.events[ev_id] = ev
            WORLD.cones[ev_id] = self._template_cone(ev_id, ev["title"])
            self._template_hypotheses(ev_id, ev)

    def _template_cone(self, ev_id: str, title: str) -> dict:
        n, e = World_node, World_edge
        return {
            "event_id": ev_id,
            "nodes": [
                n(f"{ev_id}_evt", title[:34], 0, "infrastructure", "event"),
                n(f"{ev_id}_roads", "Road / rail\nnetwork", 1, "infrastructure"),
                n(f"{ev_id}_grid", "Power\ndistribution", 1, "energy"),
                n(f"{ev_id}_ports", "Nearby ports\n& airports", 1, "maritime"),
                n(f"{ev_id}_logi", "Regional\nlogistics", 2, "infrastructure"),
                n(f"{ev_id}_supply", "Supply chain\nexposure", 3, "trade"),
            ],
            "edges": [
                e(f"{ev_id}_evt", f"{ev_id}_roads", "plausible",
                  "Shaking-intensity vs infrastructure fragility — awaiting damage reports.", "0–24 h", 0.5),
                e(f"{ev_id}_evt", f"{ev_id}_grid", "plausible",
                  "Substation/line vulnerability within felt radius — unverified.", "0–24 h", 0.45),
                e(f"{ev_id}_evt", f"{ev_id}_ports", "unknown",
                  "No port-status observation ingested yet.", "", 0.2),
                e(f"{ev_id}_roads", f"{ev_id}_logi", "uncertain",
                  "Depends on damage extent; no closures confirmed.", "0–48 h", 0.35),
                e(f"{ev_id}_logi", f"{ev_id}_supply", "unknown",
                  "Requires confirmed disruption evidence first.", "", 0.2),
            ],
        }

    def _template_hypotheses(self, ev_id: str, ev: dict) -> None:
        hid = f"hyp_{ev_id.split('_')[1]}a"
        WORLD.hypotheses[hid] = {
            "id": hid, "event_id": ev_id, "label": "A",
            "claim": f"{ev['title']} causes material infrastructure disruption in the affected region.",
            "mechanism": ["ground shaking → structural/lifeline damage"],
            "assumptions": ["population/infrastructure density near epicenter",
                            "shaking intensity exceeds local fragility thresholds"],
            "evidence_ids": list(ev["evidence_ids"]), "counter_evidence_ids": [],
            "confidence": 0.35,
            "falsifiers": ["No damage reports within 24 h from ≥2 independent sources.",
                           "Official all-clear from local authority."],
            "watchpoints": [
                {"id": f"wp_{ev_id}_1", "label": "Damage reports (independent)", "signal": "news/official", "direction": "monitor"},
                {"id": f"wp_{ev_id}_2", "label": "Grid outage maps", "signal": "TSO", "direction": "monitor"},
            ],
            "status": "active",
        }
        hid_b = f"hyp_{ev_id.split('_')[1]}b"
        WORLD.hypotheses[hid_b] = {
            "id": hid_b, "event_id": ev_id, "label": "B",
            "claim": "Event occurs in a low-exposure area; systemic impact remains negligible.",
            "mechanism": ["offshore/remote epicenter", "depth attenuates surface shaking"],
            "assumptions": ["exposure database is current"],
            "evidence_ids": [], "counter_evidence_ids": [], "confidence": 0.55,
            "falsifiers": ["Verified damage reports emerge."],
            "watchpoints": [{"id": f"wp_{ev_id}_3", "label": "Felt reports vs population grid",
                             "signal": "derived", "direction": "recompute"}],
            "status": "active",
        }

    async def run(self) -> None:
        await asyncio.sleep(3)   # let the app finish booting
        while True:
            for a in self.adapters:
                st = self.state[a.name]
                st.last_attempt = iso(now())
                try:
                    proposals = await asyncio.to_thread(a.fetch)
                    for p in proposals:
                        self._apply(p)
                    st.reachable = True
                    st.last_success = iso(now())
                    st.ingested += len(proposals)
                    st.last_error = None
                except Exception as exc:                       # controlled failure (§51)
                    st.reachable = False
                    st.last_error = _clean_text(f"{type(exc).__name__}: {exc}", 120)
            await asyncio.sleep(POLL_SECONDS)


# node/edge helpers shared with world cones
def World_node(nid, label, layer, domain, kind="system"):
    return {"id": nid, "label": label, "layer": layer, "domain": domain, "kind": kind}


def World_edge(src, dst, status, mechanism, lag="", confidence=0.5):
    return {"source": src, "target": dst, "status": status,
            "mechanism": mechanism, "lag": lag, "confidence": confidence}


INGESTOR = LiveIngestor()
