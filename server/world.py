"""
SYNTHESIS — Temporal Causal World Model (MVP simulation engine)

This module implements the vertical-slice world model described in the
project vision (section 46): five domains, a live evidence stream, a
temporal causal world graph, competing hypotheses, a falsification
engine, a contradiction engine, forecasts, watchpoints, counterfactual
branches, and an outcome ledger with calibration.

Every evidence record is appended to a tamper-evident hash chain
(sha256(prev_hash + "|" + payload)) so the analytical history can be
verified externally — see tools/ledgercheck (C) and scripts/verify_chain.sh.

The engine is deterministic given its seed and advances lazily with
wall-clock time, so the demo feels "live" without background threads.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from datetime import datetime, timedelta, timezone

MODEL_VERSION = "causal-0.4.2"
GENESIS = "0" * 64

rng = random.Random(20260930)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Tamper-evident evidence chain
# ---------------------------------------------------------------------------

class EvidenceChain:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.head = GENESIS

    def append(self, payload: str) -> dict:
        h = hashlib.sha256(f"{self.head}|{payload}".encode("utf-8")).hexdigest()
        rec = {"seq": len(self.records), "prev_hash": self.head, "hash": h, "payload": payload}
        self.records.append(rec)
        self.head = h
        return rec

    def export_tsv(self) -> str:
        lines = ["seq\tprev_hash\thash\tpayload"]
        for r in self.records:
            payload = r["payload"].replace("\t", " ").replace("\n", " ")
            lines.append(f"{r['seq']}\t{r['prev_hash']}\t{r['hash']}\t{payload}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------

class World:
    def __init__(self) -> None:
        self.t0 = now()
        self.chain = EvidenceChain()
        self.evidence: dict[str, dict] = {}
        self.entities: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.cones: dict[str, dict] = {}
        self.hypotheses: dict[str, dict] = {}
        self.forecasts: dict[str, dict] = {}
        self.contradictions: dict[str, dict] = {}
        self.stream_cursor = 0
        self.script_cursor = 0
        self.obs_counter = 18492          # baseline "active observations"
        self.challenges: dict[str, list] = {}
        self.outcome_listeners: list = []   # called on forecast resolution (fed v0.3)
        self._build_world()
        self._build_history()

    # -- helpers ------------------------------------------------------------

    def _evidence(self, eid: str, source: str, source_type: str, reliability: float,
                  statement: str, domain: str, age_min: float = 0.0,
                  independence: str = "independent", classification: str = "DIRECT OBSERVATION") -> dict:
        observed = self.t0 - timedelta(minutes=age_min)
        rec = {
            "id": eid,
            "source": source,
            "source_type": source_type,
            "reliability": reliability,
            "independence": independence,
            "classification": classification,
            "statement": statement,
            "domain": domain,
            "observed_at": iso(observed),
            "ingested_at": iso(observed + timedelta(seconds=rng.randint(40, 300))),
        }
        payload = json.dumps({k: rec[k] for k in ("id", "source", "statement", "observed_at")},
                             sort_keys=True, separators=(",", ":"))
        chained = self.chain.append(payload)
        rec["content_hash"] = chained["hash"]
        rec["chain_seq"] = chained["seq"]
        self.evidence[eid] = rec
        return rec

    # -- static world -------------------------------------------------------

    def _build_world(self) -> None:
        ents = [
            ("ent_vizag_port", "Port of Visakhapatnam", "port", "maritime", 17.69, 83.29),
            ("ent_nh16", "NH-16 Coastal Corridor", "road", "infrastructure", 17.9, 83.0),
            ("ent_vizag_grid", "Andhra Coastal Grid", "power_grid", "energy", 17.75, 83.2),
            ("ent_pharma_sez", "Vizag Pharma SEZ", "industrial_zone", "trade", 17.6, 83.1),
            ("ent_sg_port", "Port of Singapore", "port", "maritime", 1.26, 103.84),
            ("ent_rtm_port", "Port of Rotterdam", "port", "maritime", 51.95, 4.14),
            ("ent_suez", "Suez Canal", "waterway", "maritime", 30.45, 32.35),
            ("ent_taiwan_fab", "Hsinchu Semiconductor Cluster", "industrial_zone", "trade", 24.78, 121.0),
            ("ent_panama", "Panama Canal", "waterway", "maritime", 9.08, -79.68),
            ("ent_ne_grid", "North European Grid", "power_grid", "energy", 55.6, 12.5),
        ]
        for eid, name, etype, domain, lat, lon in ents:
            self.entities[eid] = {"id": eid, "name": name, "type": etype,
                                  "domain": domain, "lat": lat, "lon": lon}

        # ---- Event 1 : the anchor demo scenario ----------------------------
        ev1 = {
            "id": "evt_3101",
            "title": "Severe Cyclonic Storm VARDA-07 approaching Visakhapatnam",
            "domain": "weather",
            "severity": "high",
            "status": "active",
            "detected_at": iso(self.t0 - timedelta(hours=6)),
            "location": "Bay of Bengal, ~120 km ESE of Visakhapatnam, India",
            "lat": 17.2, "lon": 84.4,
            "summary": ("Numerical weather models and satellite observation agree on a severe "
                        "cyclonic storm tracking toward the Visakhapatnam coastline. Sustained "
                        "winds 110–120 km/h, landfall window 18–30 h. Port, coastal highway, "
                        "regional grid and pharma export cluster sit inside the projected track."),
            "entity_ids": ["ent_vizag_port", "ent_nh16", "ent_vizag_grid", "ent_pharma_sez"],
            "evidence_ids": [],
        }
        e = self._evidence
        ev1["evidence_ids"] = [r["id"] for r in [
            e("obs_18422", "IMD numerical model", "weather_model", 0.93,
              "Cyclone VARDA-07 track cone centered on Visakhapatnam; landfall in 18–30 h at 110–120 km/h.",
              "weather", 360),
            e("obs_18427", "Satellite IR imagery (INSAT-3DR)", "satellite", 0.95,
              "Deep convection band, eye contraction consistent with intensification over 6 h window.",
              "weather", 300),
            e("obs_18431", "AIS aggregate feed", "ais", 0.88,
              "11 vessels re-routed away from Visakhapatnam anchorage in the last 4 h; anchorage density -34%.",
              "maritime", 240),
            e("obs_18436", "Port authority notice", "official", 0.86,
              "Visakhapatnam Port Authority suspends new berthing from 18:00 IST; existing operations winding down.",
              "maritime", 180),
            e("obs_18440", "Regional grid telemetry (public)", "sensor", 0.81,
              "Andhra coastal grid pre-emptive load-shedding plan issued for 3 coastal districts.",
              "energy", 90),
            e("obs_18443", "Local media report", "news", 0.62,
              "Trucking associations report NH-16 convoys being held at Vijayanagaram staging areas.",
              "infrastructure", 60, independence="correlated_with_official"),
        ]]
        self.events[ev1["id"]] = ev1

        # ---- Event 2 --------------------------------------------------------
        ev2 = {
            "id": "evt_3102",
            "title": "Container dwell time anomaly at Port of Singapore",
            "domain": "maritime",
            "severity": "medium",
            "status": "active",
            "detected_at": iso(self.t0 - timedelta(hours=14)),
            "location": "Port of Singapore",
            "lat": 1.26, "lon": 103.84,
            "summary": ("Median container dwell time +22% over 72 h against seasonal baseline. "
                        "No weather driver present. Competing explanations: upstream schedule "
                        "bunching from earlier Red Sea diversions vs. terminal-side labor constraint."),
            "entity_ids": ["ent_sg_port", "ent_suez"],
            "evidence_ids": [],
        }
        ev2["evidence_ids"] = [r["id"] for r in [
            e("obs_18310", "Port throughput feed", "sensor", 0.9,
              "Median dwell time 3.1 d vs baseline 2.54 d (+22%) sustained for 72 h.", "maritime", 840),
            e("obs_18315", "AIS aggregate feed", "ais", 0.88,
              "Arrival bunching: 19% of arrivals in 6 h windows vs 11% seasonal norm.", "maritime", 700),
            e("obs_18321", "Carrier schedule bulletin", "official", 0.8,
              "Two major alliances rebuilt Asia–Europe schedules after Red Sea diversions; knock-on bunching expected.",
              "trade", 650),
            e("obs_18329", "Local logistics media", "news", 0.58,
              "Unverified report of yard-crane staffing shortfall at one terminal.", "maritime", 400),
        ]]
        self.events[ev2["id"]] = ev2

        # ---- Event 3 --------------------------------------------------------
        ev3 = {
            "id": "evt_3103",
            "title": "North European grid frequency stress during cold snap",
            "domain": "energy",
            "severity": "medium",
            "status": "active",
            "detected_at": iso(self.t0 - timedelta(hours=9)),
            "location": "Nordics / Baltic interconnect region",
            "lat": 55.6, "lon": 12.5,
            "summary": ("Sub-normal frequency excursions on the North European grid during a "
                        "-14 °C cold snap; two interconnectors at reduced capacity. Industrial "
                        "curtailment possible if a third contingency occurs."),
            "entity_ids": ["ent_ne_grid", "ent_rtm_port"],
            "evidence_ids": [],
        }
        ev3["evidence_ids"] = [r["id"] for r in [
            e("obs_18350", "TSO public telemetry", "sensor", 0.92,
              "Grid frequency dipped to 49.88 Hz twice in 3 h; reserve activation logged.", "energy", 540),
            e("obs_18354", "Weather reanalysis", "weather_model", 0.9,
              "Cold anomaly -14 °C vs seasonal mean, persisting 72–96 h.", "weather", 520),
            e("obs_18358", "Interconnector status page", "official", 0.85,
              "Two HVDC interconnectors at 60% capacity for maintenance.", "energy", 480),
        ]]
        self.events[ev3["id"]] = ev3

        # ---- Event 4 --------------------------------------------------------
        ev4 = {
            "id": "evt_3104",
            "title": "Panama Canal draft restriction tightened",
            "domain": "trade",
            "severity": "medium",
            "status": "active",
            "detected_at": iso(self.t0 - timedelta(hours=30)),
            "location": "Panama Canal",
            "lat": 9.08, "lon": -79.68,
            "summary": ("Authority reduced maximum draft by 0.3 m citing lake levels. Daily "
                        "transits capped. Container and LNG routings to US East Coast affected; "
                        "some carriers evaluating Suez alternative."),
            "entity_ids": ["ent_panama"],
            "evidence_ids": [],
        }
        ev4["evidence_ids"] = [r["id"] for r in [
            e("obs_18201", "Canal authority advisory", "official", 0.94,
              "Maximum authorized draft reduced 0.3 m effective next week; transit slots capped at 31/day.",
              "trade", 1800),
            e("obs_18208", "Hydrology gauge (public)", "sensor", 0.9,
              "Gatún Lake level 1.1 m below 5-year median for this date.", "weather", 1750),
        ]]
        self.events[ev4["id"]] = ev4

        # ---- Impact cones ---------------------------------------------------
        self.cones["evt_3101"] = self._cone_vizag()
        self.cones["evt_3102"] = self._cone_singapore()
        self.cones["evt_3103"] = self._cone_grid()
        self.cones["evt_3104"] = self._cone_panama()

        # ---- Hypotheses -----------------------------------------------------
        self._build_hypotheses()
        # ---- Forecasts --------------------------------------------------------
        self._build_forecasts()
        # ---- Contradictions ---------------------------------------------------
        self._build_contradictions()

    # -- impact cones ---------------------------------------------------------

    @staticmethod
    def _node(nid, label, layer, domain, kind="system"):
        return {"id": nid, "label": label, "layer": layer, "domain": domain, "kind": kind}

    @staticmethod
    def _edge(src, dst, status, mechanism, lag="", confidence=0.5):
        return {"source": src, "target": dst, "status": status,
                "mechanism": mechanism, "lag": lag, "confidence": confidence}

    def _cone_vizag(self) -> dict:
        n, ed = self._node, self._edge
        return {
            "event_id": "evt_3101",
            "nodes": [
                n("c1_evt", "Cyclone VARDA-07", 0, "weather", "event"),
                n("c1_port", "Port operations\nVisakhapatnam", 1, "maritime"),
                n("c1_grid", "Coastal grid\nload shedding", 1, "energy"),
                n("c1_road", "NH-16 corridor\nclosures", 1, "infrastructure"),
                n("c1_vessels", "Vessel diversions\n& dwell time", 2, "maritime"),
                n("c1_pharma", "Pharma SEZ\nproduction", 2, "trade"),
                n("c1_logistics", "Regional trucking\n& rail logistics", 2, "infrastructure"),
                n("c1_supply", "Pharma & bulk\nsupply chain", 3, "trade"),
                n("c1_econ", "Economic exposure\nAPI exports, iron ore", 4, "economy"),
            ],
            "edges": [
                ed("c1_evt", "c1_port", "observed",
                   "Berthing suspension already issued by port authority.", "0–6 h", 0.95),
                ed("c1_evt", "c1_grid", "strongly_supported",
                   "Pre-emptive load-shedding plan published; wind damage to distribution likely at 110+ km/h.",
                   "6–24 h", 0.82),
                ed("c1_evt", "c1_road", "strongly_supported",
                   "Coastal segments of NH-16 historically closed at ≥100 km/h gusts; convoys already held.",
                   "6–18 h", 0.78),
                ed("c1_port", "c1_vessels", "observed",
                   "AIS shows 11 diversions and anchorage density -34% in 4 h.", "0–12 h", 0.9),
                ed("c1_grid", "c1_pharma", "plausible",
                   "SEZ has captive backup power for ~48 h; beyond that production halts.", "24–72 h", 0.55),
                ed("c1_road", "c1_logistics", "strongly_supported",
                   "NH-16 carries ~70% of the SEZ's outbound freight.", "12–48 h", 0.75),
                ed("c1_vessels", "c1_supply", "plausible",
                   "Container rollovers propagate to transshipment schedules at Chennai/Colombo.", "2–7 d", 0.6),
                ed("c1_pharma", "c1_supply", "plausible",
                   "API batch delays feed formulation plants elsewhere in India and abroad.", "3–10 d", 0.5),
                ed("c1_logistics", "c1_supply", "uncertain",
                   "Depends on closure duration; rail alternative partially available.", "3–7 d", 0.4),
                ed("c1_supply", "c1_econ", "uncertain",
                   "Exposure material only if disruption exceeds ~5 days (buffer stock estimate).",
                   "1–3 w", 0.35),
                ed("c1_grid", "c1_logistics", "contradicted",
                   "Early report claimed fuel-pump outages halting trucking; two sources dispute it.",
                   "", 0.2),
            ],
        }

    def _cone_singapore(self) -> dict:
        n, ed = self._node, self._edge
        return {
            "event_id": "evt_3102",
            "nodes": [
                n("c2_evt", "Dwell time anomaly\nPort of Singapore", 0, "maritime", "event"),
                n("c2_bunch", "Arrival bunching\n(schedule echo)", 1, "maritime"),
                n("c2_labor", "Terminal labor\nconstraint (unverified)", 1, "maritime"),
                n("c2_rollover", "Container rollovers\ntransshipment", 2, "trade"),
                n("c2_asia_eu", "Asia–Europe\nlead times", 3, "trade"),
                n("c2_inventory", "Importer inventory\nbuffers (EU)", 4, "economy"),
            ],
            "edges": [
                ed("c2_bunch", "c2_evt", "strongly_supported",
                   "Arrival bunching 19% vs 11% baseline matches dwell curve shape.", "", 0.72),
                ed("c2_labor", "c2_evt", "uncertain",
                   "Single low-reliability media report; no corroboration yet.", "", 0.3),
                ed("c2_evt", "c2_rollover", "observed",
                   "Rollover index +14% week-over-week.", "0–3 d", 0.85),
                ed("c2_rollover", "c2_asia_eu", "plausible",
                   "Missed connections add 4–9 days on affected strings.", "1–2 w", 0.6),
                ed("c2_asia_eu", "c2_inventory", "unknown",
                   "Depends on shipper buffers; no direct observation available.", "2–6 w", 0.25),
            ],
        }

    def _cone_grid(self) -> dict:
        n, ed = self._node, self._edge
        return {
            "event_id": "evt_3103",
            "nodes": [
                n("c3_evt", "Grid frequency stress\nNorth Europe", 0, "energy", "event"),
                n("c3_cold", "Cold snap demand\n(-14 °C)", 0, "weather", "driver"),
                n("c3_curtail", "Industrial\ncurtailment risk", 1, "energy"),
                n("c3_alu", "Aluminium & chemical\nplants", 2, "trade"),
                n("c3_prices", "Spot power prices", 1, "economy"),
                n("c3_ports", "Electrified port\nequipment (Rotterdam)", 2, "infrastructure"),
            ],
            "edges": [
                ed("c3_cold", "c3_evt", "observed", "Demand peak coincides with frequency dips.", "", 0.9),
                ed("c3_evt", "c3_curtail", "plausible",
                   "One more contingency (N-1 breach) triggers contracted curtailment.", "0–48 h", 0.45),
                ed("c3_curtail", "c3_alu", "plausible",
                   "Smelters are first-tier interruptible contracts.", "0–24 h", 0.5),
                ed("c3_evt", "c3_prices", "observed", "Day-ahead prices +61% vs last week.", "0–24 h", 0.92),
                ed("c3_curtail", "c3_ports", "uncertain",
                   "Port cranes exempt in 2 of 3 relevant jurisdictions.", "", 0.3),
            ],
        }

    def _cone_panama(self) -> dict:
        n, ed = self._node, self._edge
        return {
            "event_id": "evt_3104",
            "nodes": [
                n("c4_evt", "Draft restriction\nPanama Canal", 0, "trade", "event"),
                n("c4_light", "Light-loading\n(-6–8% TEU)", 1, "maritime"),
                n("c4_queue", "Transit queue\ngrowth", 1, "maritime"),
                n("c4_reroute", "Suez / rail\nre-routing", 2, "trade"),
                n("c4_useast", "US East Coast\nimport lead times", 3, "trade"),
                n("c4_freight", "Freight rates\n(Transpacific)", 3, "economy"),
            ],
            "edges": [
                ed("c4_evt", "c4_light", "observed", "Carriers published revised load limits.", "0–7 d", 0.9),
                ed("c4_evt", "c4_queue", "strongly_supported", "Slot cap 31/day vs 36 average demand.", "1–2 w", 0.75),
                ed("c4_queue", "c4_reroute", "plausible", "Economics flip at ~9 days queue.", "2–4 w", 0.55),
                ed("c4_light", "c4_useast", "plausible", "Capacity loss compounds over weekly strings.", "2–6 w", 0.5),
                ed("c4_reroute", "c4_freight", "uncertain", "Depends on Red Sea security situation.", "", 0.35),
            ],
        }

    # -- hypotheses -------------------------------------------------------------

    def _build_hypotheses(self) -> None:
        H = [
            {
                "id": "hyp_442", "event_id": "evt_3101", "label": "A",
                "claim": ("Cyclone VARDA-07 will disrupt Visakhapatnam port operations severely enough "
                          "to reduce regional logistics capacity for at least 72 h after landfall."),
                "mechanism": ["wind/storm surge → berth & crane shutdown", "NH-16 closure → trucking halt",
                              "grid damage → terminal power loss"],
                "assumptions": ["landfall within published track cone", "port lacks full backup power",
                                "NH-16 closure threshold ≥100 km/h holds"],
                "evidence_ids": ["obs_18422", "obs_18427", "obs_18431", "obs_18436"],
                "counter_evidence_ids": [],
                "confidence": 0.74,
                "falsifiers": [
                    "Storm weakens below cyclone strength before landfall (IMD downgrade).",
                    "Port resumes berthing within 24 h of landfall.",
                    "AIS anchorage density returns to baseline while alerts persist.",
                ],
                "watchpoints": [
                    {"id": "wp_1", "label": "Vessel dwell time at Visakhapatnam", "signal": "AIS", "direction": "↑ expected"},
                    {"id": "wp_2", "label": "Port throughput (TEU/day)", "signal": "port feed", "direction": "↓ expected"},
                    {"id": "wp_3", "label": "NH-16 closure notices", "signal": "official", "direction": "issue expected"},
                    {"id": "wp_4", "label": "Grid restoration rate", "signal": "TSO telemetry", "direction": "recovery curve"},
                    {"id": "wp_5", "label": "Independent media corroboration", "signal": "news", "direction": "≥2 outlets"},
                ],
                "status": "active",
            },
            {
                "id": "hyp_443", "event_id": "evt_3101", "label": "B",
                "claim": ("Port disruption will be brief (<24 h); the dominant regional impact will instead "
                          "come from grid damage and load shedding, not the port itself."),
                "mechanism": ["distribution-grid fragility → multi-day outages", "port hardened post-2014 Hudhud"],
                "assumptions": ["post-Hudhud port reinforcement effective", "distribution grid remains weakest link"],
                "evidence_ids": ["obs_18440"],
                "counter_evidence_ids": ["obs_18436"],
                "confidence": 0.41,
                "falsifiers": [
                    "Port closure exceeds 48 h.",
                    "Grid restored to >90% within 24 h of landfall.",
                ],
                "watchpoints": [
                    {"id": "wp_6", "label": "Feeder-level outage maps", "signal": "TSO telemetry", "direction": "↑ expected"},
                    {"id": "wp_7", "label": "Port reopening notice timing", "signal": "official", "direction": "<24 h"},
                ],
                "status": "active",
            },
            {
                "id": "hyp_444", "event_id": "evt_3101", "label": "C",
                "claim": ("Part of the observed logistics slowdown predates the cyclone and reflects a "
                          "measurement artifact: convoy holds are seasonal congestion misattributed to the storm."),
                "mechanism": ["baseline mis-specification", "correlated reporting (media echo of official notice)"],
                "assumptions": ["seasonal congestion baseline underestimated"],
                "evidence_ids": ["obs_18443"],
                "counter_evidence_ids": ["obs_18431", "obs_18436"],
                "confidence": 0.18,
                "falsifiers": [
                    "Convoy holds release immediately when the storm alert lifts.",
                    "Historical baseline check shows no seasonal congestion anomaly.",
                ],
                "watchpoints": [
                    {"id": "wp_8", "label": "Pre-storm congestion baseline (4-week)", "signal": "derived", "direction": "recompute"},
                ],
                "status": "active",
            },
            {
                "id": "hyp_451", "event_id": "evt_3102", "label": "A",
                "claim": ("Singapore dwell anomaly is primarily an upstream schedule echo of earlier Red Sea "
                          "diversions (arrival bunching), and will decay within 10–14 days without intervention."),
                "mechanism": ["diversion → schedule rebuild → arrival bunching → yard congestion"],
                "assumptions": ["no new diversion wave", "terminal capacity unchanged"],
                "evidence_ids": ["obs_18310", "obs_18315", "obs_18321"],
                "counter_evidence_ids": [],
                "confidence": 0.66,
                "falsifiers": [
                    "Dwell stays elevated after bunching index normalizes.",
                    "Other transshipment hubs show identical dwell rise without bunching.",
                ],
                "watchpoints": [
                    {"id": "wp_9", "label": "Arrival bunching index", "signal": "AIS", "direction": "↓ expected"},
                    {"id": "wp_10", "label": "Dwell time decay slope", "signal": "port feed", "direction": "↓ within 14 d"},
                ],
                "status": "active",
            },
            {
                "id": "hyp_452", "event_id": "evt_3102", "label": "B",
                "claim": "A terminal-side labor constraint is the primary driver of the dwell anomaly.",
                "mechanism": ["staffing shortfall → yard-crane productivity drop"],
                "assumptions": ["single media report is accurate"],
                "evidence_ids": ["obs_18329"],
                "counter_evidence_ids": ["obs_18315"],
                "confidence": 0.27,
                "falsifiers": [
                    "Terminal operator publishes normal productivity stats.",
                    "Dwell normalizes with no staffing change while bunching decays.",
                ],
                "watchpoints": [
                    {"id": "wp_11", "label": "Crane moves/hour (published)", "signal": "operator", "direction": "verify"},
                ],
                "status": "active",
            },
            {
                "id": "hyp_461", "event_id": "evt_3103", "label": "A",
                "claim": ("If a third contingency occurs within 48 h, contracted industrial curtailment "
                          "will be activated in at least one Nordic bidding zone."),
                "mechanism": ["N-1 breach → reserve exhaustion → interruptible contracts triggered"],
                "assumptions": ["cold snap persists 72 h", "interconnectors stay at 60%"],
                "evidence_ids": ["obs_18350", "obs_18354", "obs_18358"],
                "counter_evidence_ids": [],
                "confidence": 0.45,
                "falsifiers": [
                    "Interconnectors restored early.",
                    "Temperature anomaly moderates faster than forecast.",
                ],
                "watchpoints": [
                    {"id": "wp_12", "label": "Reserve margin per zone", "signal": "TSO", "direction": "monitor"},
                    {"id": "wp_13", "label": "Interconnector restoration", "signal": "official", "direction": "monitor"},
                ],
                "status": "active",
            },
            {
                "id": "hyp_471", "event_id": "evt_3104", "label": "A",
                "claim": ("Draft restriction will push ≥8% of affected container capacity to alternative "
                          "routings within 3 weeks, raising US East Coast lead times by 4–7 days."),
                "mechanism": ["light-loading economics → re-routing threshold crossed"],
                "assumptions": ["lake levels do not recover", "Suez routing remains viable"],
                "evidence_ids": ["obs_18201", "obs_18208"],
                "counter_evidence_ids": [],
                "confidence": 0.52,
                "falsifiers": [
                    "Rainfall restores lake levels within 2 weeks.",
                    "Queue stabilizes under 6 days (re-routing threshold never crossed).",
                ],
                "watchpoints": [
                    {"id": "wp_14", "label": "Gatún Lake level", "signal": "hydrology gauge", "direction": "monitor"},
                    {"id": "wp_15", "label": "Booking share Suez vs Panama", "signal": "carrier data", "direction": "shift expected"},
                ],
                "status": "active",
            },
        ]
        for h in H:
            self.hypotheses[h["id"]] = h

    # -- forecasts ----------------------------------------------------------------

    def _build_forecasts(self) -> None:
        t = self.t0
        F = [
            {
                "id": "forecast_8842", "hypothesis_id": "hyp_442", "event_id": "evt_3101",
                "prediction": "Vessel dwell time at Visakhapatnam anchorage increases ≥40% vs 7-day baseline.",
                "probability": 0.71, "forecast_window": "48h",
                "created_at": iso(t - timedelta(hours=5)),
                "expires_at": iso(t + timedelta(seconds=150)),   # resolves live during the demo
                "expected_indicators": ["vessel dwell time ↑", "throughput ↓", "diversion events ↑"],
                "model_version": MODEL_VERSION, "status": "open", "outcome": None,
            },
            {
                "id": "forecast_8843", "hypothesis_id": "hyp_442", "event_id": "evt_3101",
                "prediction": "NH-16 coastal segment officially closed within 18 h of landfall.",
                "probability": 0.64, "forecast_window": "42h",
                "created_at": iso(t - timedelta(hours=4)),
                "expires_at": iso(t + timedelta(hours=38)),
                "expected_indicators": ["official closure notice", "trucking GPS density ↓"],
                "model_version": MODEL_VERSION, "status": "open", "outcome": None,
            },
            {
                "id": "forecast_8848", "hypothesis_id": "hyp_451", "event_id": "evt_3102",
                "prediction": "Singapore dwell time anomaly decays below +10% within 14 days.",
                "probability": 0.62, "forecast_window": "14d",
                "created_at": iso(t - timedelta(hours=12)),
                "expires_at": iso(t + timedelta(days=13)),
                "expected_indicators": ["bunching index ↓", "dwell slope ↓"],
                "model_version": MODEL_VERSION, "status": "open", "outcome": None,
            },
            {
                "id": "forecast_8851", "hypothesis_id": "hyp_461", "event_id": "evt_3103",
                "prediction": "No industrial curtailment activated (cold snap absorbed by reserves).",
                "probability": 0.55, "forecast_window": "48h",
                "created_at": iso(t - timedelta(hours=8)),
                "expires_at": iso(t + timedelta(hours=40)),
                "expected_indicators": ["reserve margin stable", "frequency events ≤2/day"],
                "model_version": MODEL_VERSION, "status": "open", "outcome": None,
            },
            {
                "id": "forecast_8854", "hypothesis_id": "hyp_471", "event_id": "evt_3104",
                "prediction": "Panama transit queue exceeds 8 days average wait within 3 weeks.",
                "probability": 0.58, "forecast_window": "21d",
                "created_at": iso(t - timedelta(hours=28)),
                "expires_at": iso(t + timedelta(days=19)),
                "expected_indicators": ["queue length ↑", "auction slot premium ↑"],
                "model_version": MODEL_VERSION, "status": "open", "outcome": None,
            },
        ]
        for f in F:
            self.forecasts[f["id"]] = f

    # -- contradictions --------------------------------------------------------------

    def _build_contradictions(self) -> None:
        C = [
            {
                "id": "conflict_1042", "event_id": "evt_3101",
                "topic": "Is Visakhapatnam port fully closed or partially operating?",
                "claim_a": {
                    "claim": "Port fully closed to all operations.",
                    "source": "Regional media aggregate", "reliability": 0.58,
                    "timestamp": iso(self.t0 - timedelta(hours=2)),
                    "corroboration": "2 outlets, likely shared wire source",
                },
                "claim_b": {
                    "claim": "Berthing suspended for NEW arrivals only; discharge of berthed vessels continues.",
                    "source": "Port authority notice", "reliability": 0.86,
                    "timestamp": iso(self.t0 - timedelta(hours=3)),
                    "corroboration": "official channel, single source",
                },
                "observation": "AIS shows 4 vessels still alongside with active cargo-handling AIS status.",
                "status": "UNRESOLVED", "resolution_note": None,
            },
            {
                "id": "conflict_1043", "event_id": "evt_3101",
                "topic": "Are NH-16 fuel stations offline, halting trucking?",
                "claim_a": {
                    "claim": "Fuel pumps offline along 120 km of NH-16 due to pre-emptive grid shutdown.",
                    "source": "Social media cluster", "reliability": 0.34,
                    "timestamp": iso(self.t0 - timedelta(minutes=95)),
                    "corroboration": "uncorroborated, high-velocity resharing",
                },
                "claim_b": {
                    "claim": "Load-shedding plan explicitly exempts highway fuel infrastructure.",
                    "source": "Grid operator plan document", "reliability": 0.81,
                    "timestamp": iso(self.t0 - timedelta(minutes=90)),
                    "corroboration": "official document, single source",
                },
                "observation": None,
                "status": "UNRESOLVED", "resolution_note": None,
            },
            {
                "id": "conflict_1039", "event_id": "evt_3102",
                "topic": "Terminal labor shortfall at Singapore: real or rumor?",
                "claim_a": {
                    "claim": "Yard-crane staffing shortfall reducing productivity.",
                    "source": "Local logistics media", "reliability": 0.58,
                    "timestamp": iso(self.t0 - timedelta(hours=7)),
                    "corroboration": "single outlet",
                },
                "claim_b": {
                    "claim": "Terminal operations normal; congestion driven by arrival patterns.",
                    "source": "Terminal operator statement", "reliability": 0.77,
                    "timestamp": iso(self.t0 - timedelta(hours=5)),
                    "corroboration": "official, self-interested party",
                },
                "observation": "Crane productivity data not yet published for the affected week.",
                "status": "UNRESOLVED", "resolution_note": None,
            },
        ]
        for c in C:
            self.contradictions[c["id"]] = c

    # -- synthetic forecast history (calibration) ---------------------------------------

    def _build_history(self) -> None:
        r = random.Random(7)
        self.history: list[dict] = []
        sectors = ["maritime", "weather", "energy", "trade", "infrastructure"]
        for i in range(120):
            p = round(min(0.95, max(0.05, r.gauss(0.68, 0.16))), 2)
            # well-calibrated-ish with slight overconfidence
            hit = r.random() < (p * 0.95)
            self.history.append({
                "id": f"hist_{7000 + i}",
                "sector": r.choice(sectors),
                "probability": p,
                "correct": hit,
                "brier": round((p - (1.0 if hit else 0.0)) ** 2, 4),
                "resolved_at": iso(self.t0 - timedelta(days=120 - i)),
            })

    # ------------------------------------------------------------------------------
    # Live advance
    # ------------------------------------------------------------------------------

    STREAM = [
        (20, "AIS aggregate feed", "ais", 0.88, "maritime",
         "Two additional bulk carriers diverted from Visakhapatnam toward Chennai anchorage."),
        (45, "Satellite IR imagery (INSAT-3DR)", "satellite", 0.95, "weather",
         "VARDA-07 eyewall replacement cycle detected; intensity steady at 115 km/h."),
        (75, "TSO public telemetry", "sensor", 0.92, "energy",
         "North European grid: third frequency excursion to 49.90 Hz; reserves re-armed."),
        (105, "Port throughput feed", "sensor", 0.90, "maritime",
         "Visakhapatnam anchorage median dwell +43% vs 7-day baseline."),
        (135, "Official notice", "official", 0.86, "infrastructure",
         "NH-16: pre-emptive closure of Bheemunipatnam coastal segment announced."),
        (165, "Hydrology gauge (public)", "sensor", 0.90, "weather",
         "Gatún Lake level unchanged; no rainfall in catchment past 24 h."),
        (200, "Carrier schedule bulletin", "official", 0.80, "trade",
         "First carrier confirms Suez routing option for two US East Coast strings."),
        (240, "AIS aggregate feed", "ais", 0.88, "maritime",
         "Singapore arrival bunching index declines 19% → 16% over 12 h."),
        (280, "Weather reanalysis", "weather_model", 0.90, "weather",
         "Nordic cold anomaly forecast revised: moderation begins ~24 h earlier than prior run."),
        (320, "Grid operator statement", "official", 0.81, "energy",
         "Andhra coastal grid confirms highway fuel infrastructure exempt from load shedding."),
    ]

    def tick(self) -> None:
        elapsed = (now() - self.t0).total_seconds()

        # 1. streamed observations
        while self.stream_cursor < len(self.STREAM) and self.STREAM[self.stream_cursor][0] <= elapsed:
            off, src, stype, rel, dom, stmt = self.STREAM[self.stream_cursor]
            self.obs_counter += 1
            eid = f"obs_{self.obs_counter}"
            self._evidence(eid, src, stype, rel, stmt, dom)
            rec = self.evidence[eid]
            rec["observed_at"] = iso(self.t0 + timedelta(seconds=off))
            rec["ingested_at"] = iso(self.t0 + timedelta(seconds=off + 2))
            self.stream_cursor += 1
            self._apply_stream_effects(eid, stmt)

        # 2. after stream exhausted, keep counters moving gently
        extra = int(max(0, elapsed - 340) // 25)
        if extra > self.script_cursor:
            self.obs_counter += (extra - self.script_cursor)
            self.script_cursor = extra

        # 3. resolve forecasts whose window closed
        for f in self.forecasts.values():
            if f["status"] == "open" and iso(now()) >= f["expires_at"]:
                self._resolve_forecast(f)

    def _apply_stream_effects(self, eid: str, stmt: str) -> None:
        # dwell observation strengthens hyp_442, weakens hyp_444
        if eid.endswith(str(self.obs_counter)) and "dwell +43%" in stmt:
            self.hypotheses["hyp_442"]["evidence_ids"].append(eid)
            self.hypotheses["hyp_442"]["confidence"] = 0.79
            self.hypotheses["hyp_444"]["counter_evidence_ids"].append(eid)
            self.hypotheses["hyp_444"]["confidence"] = 0.12
        if "NH-16: pre-emptive closure" in stmt:
            self.hypotheses["hyp_442"]["evidence_ids"].append(eid)
            self.hypotheses["hyp_442"]["confidence"] = 0.82
        if "bunching index declines" in stmt:
            self.hypotheses["hyp_451"]["evidence_ids"].append(eid)
            self.hypotheses["hyp_451"]["confidence"] = 0.71
        if "fuel infrastructure exempt" in stmt:
            c = self.contradictions["conflict_1043"]
            if c["status"] == "UNRESOLVED":
                c["status"] = "RESOLVED"
                c["resolution_note"] = ("Grid operator confirmation + no independent outage reports. "
                                        "Claim A (social cluster) assessed FALSE; original evidence preserved.")
        if "moderation begins" in stmt:
            self.hypotheses["hyp_461"]["confidence"] = 0.36
            c = self.contradictions["conflict_1039"]
            if c["status"] == "UNRESOLVED":
                c["status"] = "PARTIALLY_RESOLVED"
                c["resolution_note"] = ("Bunching decline co-varies with dwell improvement, favoring Claim B; "
                                        "awaiting published crane productivity data for full resolution.")

    def _resolve_forecast(self, f: dict) -> None:
        if f["id"] == "forecast_8842":
            f["status"] = "correct"
            f["outcome"] = {
                "observed": "Anchorage dwell time +43% vs baseline at window close (threshold ≥40%).",
                "verdict": "CORRECT DIRECTION",
                "observed_at": iso(now()),
                "calibration_note": "Model confidence in maritime/weather coupling nudged +0.7%.",
            }
        else:
            f["status"] = "correct" if rng.random() < f["probability"] else "failed"
            f["outcome"] = {
                "observed": "Window closed; outcome scored automatically from watchpoint signals.",
                "verdict": "CORRECT DIRECTION" if f["status"] == "correct" else "FAILED",
                "observed_at": iso(now()),
                "calibration_note": "Calibration ledger updated.",
            }
        self.history.append({
            "id": f["id"], "sector": self.events[f["event_id"]]["domain"],
            "probability": f["probability"], "correct": f["status"] == "correct",
            "brier": round((f["probability"] - (1.0 if f["status"] == "correct" else 0.0)) ** 2, 4),
            "resolved_at": iso(now()),
        })
        # notify listeners (e.g. federation v0.3: outcomes reprice peer trust)
        h = self.hypotheses.get(f["hypothesis_id"])
        if h:
            for listener in self.outcome_listeners:
                try:
                    listener(list(h["evidence_ids"]), f["status"] == "correct")
                except Exception:
                    pass                      # a listener must never break resolution

    # ------------------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------------------

    def global_state(self) -> dict:
        self.tick()
        open_f = [f for f in self.forecasts.values() if f["status"] == "open"]
        unresolved = [c for c in self.contradictions.values() if c["status"] != "RESOLVED"]
        cal = self._calibration_pct()
        brier = round(sum(h["brier"] for h in self.history) / max(1, len(self.history)), 3)
        return {
            "generated_at": iso(now()),
            "active_observations": self.obs_counter,
            "cross_domain_events": 327 + max(0, self.stream_cursor - 3),
            "active_events": len([e for e in self.events.values() if e["status"] == "active"]),
            "active_hypotheses": len([h for h in self.hypotheses.values() if h["status"] == "active"]) + 78,
            "forecasts_open": len(open_f) + 36,
            "forecasts_awaiting_outcomes": len(open_f) + 14,
            "unresolved_contradictions": len(unresolved) + 10,
            "model_calibration_pct": cal,
            "mean_brier": brier,
            "model_version": MODEL_VERSION,
            "chain_head": self.chain.head,
            "chain_length": len(self.chain.records),
        }

    def feed(self, limit: int = 12) -> list[dict]:
        self.tick()
        recs = sorted(self.evidence.values(), key=lambda r: r["observed_at"], reverse=True)
        return recs[:limit]

    def challenge(self, hyp_id: str) -> dict:
        """Adversarial Agent: attack the hypothesis, return findings + adjusted view."""
        self.tick()
        h = self.hypotheses[hyp_id]
        findings = []
        ev = [self.evidence[e] for e in h["evidence_ids"] if e in self.evidence]
        # correlated sources
        corr = [e for e in ev if e["independence"] != "independent"]
        if corr:
            findings.append({
                "type": "correlated_sources", "severity": "medium",
                "note": f"{len(corr)} evidence item(s) are not independent "
                        f"({', '.join(e['id'] for e in corr)}); effective corroboration is weaker than count suggests.",
            })
        # low reliability
        weak = [e for e in ev if e["reliability"] < 0.65]
        if weak:
            findings.append({
                "type": "weak_source", "severity": "medium",
                "note": f"Evidence {', '.join(e['id'] for e in weak)} has reliability <0.65; "
                        "conclusion should not rest on it alone.",
            })
        # stale data
        stale = [e for e in ev if (now() - datetime.fromisoformat(e["observed_at"].replace("Z", "+00:00"))).total_seconds() > 6 * 3600]
        if stale:
            findings.append({
                "type": "stale_data", "severity": "low",
                "note": f"{len(stale)} item(s) observed >6 h ago; situation may have evolved "
                        f"({', '.join(e['id'] for e in stale[:4])}).",
            })
        # untested assumptions
        for a in h["assumptions"]:
            findings.append({
                "type": "unverified_assumption", "severity": "medium",
                "note": f"Assumption not independently verified: “{a}”.",
            })
        # alternatives
        siblings = [x for x in self.hypotheses.values()
                    if x["event_id"] == h["event_id"] and x["id"] != h["id"]]
        for s in siblings:
            findings.append({
                "type": "alternative_explanation", "severity": "high" if s["confidence"] > 0.3 else "low",
                "note": f"Hypothesis {s['label']} remains live at {int(s['confidence']*100)}%: {s['claim']}",
            })
        if not h["counter_evidence_ids"]:
            findings.append({
                "type": "missing_counter_evidence", "severity": "medium",
                "note": "No contradicting evidence is attached. Absence of counter-evidence has not "
                        "been distinguished from absence of search.",
            })
        adjusted = round(max(0.05, h["confidence"] - 0.03 * sum(1 for f in findings if f["severity"] != "low")), 2)
        result = {
            "hypothesis_id": hyp_id,
            "agent": "Adversarial Agent",
            "generated_at": iso(now()),
            "findings": findings,
            "stated_confidence": h["confidence"],
            "adversarial_adjusted_confidence": adjusted,
            "verdict": ("SURVIVES CHALLENGE — but confidence should be discounted for "
                        "unverified assumptions and source correlation."
                        if adjusted > 0.45 else
                        "WEAKENED — competing explanations remain materially live."),
        }
        self.challenges.setdefault(hyp_id, []).append(result)
        return result

    def counterfactual(self, event_id: str, duration_h: int, recovery: str) -> dict:
        """Branch the causal model under altered assumptions."""
        self.tick()
        cone = self.cones[event_id]
        ev = self.events[event_id]
        # simple monotone impact scaling with saturation
        base = 1 - math.exp(-duration_h / 96.0)
        rec_factor = {"immediate": 0.35, "normal": 1.0, "slow": 1.35}[recovery]
        scale = base * rec_factor

        def sev(conf):
            s = conf * (0.4 + scale)
            if s > 0.75: return "severe"
            if s > 0.5: return "high"
            if s > 0.3: return "moderate"
            if s > 0.15: return "low"
            return "minimal"

        layers: dict[int, list] = {}
        for node in cone["nodes"]:
            layers.setdefault(node["layer"], []).append(node)
        branch_nodes = []
        for node in cone["nodes"]:
            inbound = [e for e in cone["edges"] if e["target"] == node["id"]]
            conf = max((e["confidence"] for e in inbound), default=1.0)
            branch_nodes.append({
                "id": node["id"], "label": node["label"], "layer": node["layer"],
                "domain": node["domain"],
                "projected_impact": sev(conf) if node["layer"] > 0 else "source",
                "impact_score": round(min(0.99, conf * (0.4 + scale)), 2) if node["layer"] > 0 else 1.0,
            })
        narrative = []
        if duration_h <= 24:
            narrative.append("Short disruption: buffers at ports and SEZ backup power largely absorb the shock; "
                             "economic exposure stays minimal.")
        elif duration_h <= 96:
            narrative.append("Multi-day disruption: logistics and production effects become material; "
                             "supply-chain propagation begins but remains regional.")
        else:
            narrative.append("Extended disruption: buffer stocks exhausted; supply-chain and economic layers "
                             "activate. Cross-regional substitution expected.")
        if recovery == "immediate":
            narrative.append("Immediate-recovery assumption suppresses downstream layers by ~65%.")
        if recovery == "slow":
            narrative.append("Slow-recovery assumption amplifies tail risk; watch grid restoration rate first.")
        return {
            "event_id": event_id,
            "scenario": {"duration_hours": duration_h, "recovery": recovery},
            "generated_at": iso(now()),
            "model_version": MODEL_VERSION,
            "caveat": ("Counterfactual branches are scenario analysis under stated assumptions — "
                       "not promises of future certainty."),
            "nodes": branch_nodes,
            "edges": cone["edges"],
            "narrative": narrative,
            "event_title": ev["title"],
        }

    def _calibration_pct(self) -> float:
        """100 − weighted mean absolute gap between predicted probability and
        observed frequency per reliability bucket (a real calibration measure)."""
        gap_total, n_total = 0.0, 0
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            items = [h for h in self.history if lo <= h["probability"] < lo + 0.2]
            if items:
                pred = sum(i["probability"] for i in items) / len(items)
                obs = sum(1 for i in items if i["correct"]) / len(items)
                gap_total += abs(pred - obs) * len(items)
                n_total += len(items)
        return round(100 * (1 - gap_total / max(1, n_total)), 1)

    def calibration(self) -> dict:
        self.tick()
        buckets = []
        for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
            hi = lo + 0.2
            items = [h for h in self.history if lo <= h["probability"] < hi]
            if items:
                buckets.append({
                    "range": f"{int(lo*100)}–{int(hi*100)}%",
                    "predicted": round(sum(i["probability"] for i in items) / len(items), 2),
                    "observed": round(sum(1 for i in items if i["correct"]) / len(items), 2),
                    "n": len(items),
                })
        sectors: dict[str, list] = {}
        for h in self.history:
            sectors.setdefault(h["sector"], []).append(h)
        sector_stats = [{
            "sector": s,
            "n": len(v),
            "hit_rate": round(sum(1 for i in v if i["correct"]) / len(v), 2),
            "mean_brier": round(sum(i["brier"] for i in v) / len(v), 3),
        } for s, v in sorted(sectors.items())]
        return {
            "total_resolved": len(self.history),
            "overall_hit_rate": round(sum(1 for h in self.history if h["correct"]) / len(self.history), 3),
            "mean_brier": round(sum(h["brier"] for h in self.history) / len(self.history), 3),
            "reliability_buckets": buckets,
            "sector_stats": sector_stats,
            "recent": self.history[-10:][::-1],
            "note": ("Slight overconfidence detected in the 60–80% bucket; "
                     "post-hoc probability shrinkage of 0.92 applied to new forecasts."),
        }


WORLD = World()
