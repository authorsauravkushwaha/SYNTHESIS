# Changelog

## v0.1.0 — the complete vertical slice

The full intelligence loop from the vision document, running end to end:

**World model**
- Temporal causal world graph across 5 domains; impact cones with typed edges
  (observed → unknown), each carrying mechanism, lag, confidence
- Competing hypotheses (A/B/C) with evidence trails, counter-evidence,
  assumptions, falsifiers
- **Watchpoint engine (§11)**: incoming evidence auto-evaluated against every
  active hypothesis's watchpoints — confidence moves mechanically, and every
  adjustment is traceable to a hit
- Falsification Engine, Contradiction Engine (lifecycle with evidence
  preserved), Adversarial Agent (never increases confidence)
- Counterfactual branching (duration × recovery), Outcome Ledger with live
  forecast resolution, reliability diagram, per-sector Brier, forecasts
  pinned to model versions

**Trust architecture**
- Tamper-evident evidence chain; independent verifiers in **C, Python,
  TypeScript** (+ `synthesisctl`)
- Zero-trust live ingestion (USGS auto-events, Open-Meteo) — external content
  is data, never instructions; controlled degradation when offline
- API security (§24): token-bucket rate limiting, optional API-key auth with
  honest mode reporting, hash-chained audit trail verifiable with the same C tool
- Signed releases: SBOM (syft) + keyless Sigstore cosign + BuildKit provenance

**Federation — SYNTHESIS Protocol v0 (§43)**
- Ed25519-signed observation bundles; identity proven, never claimed
- Matching claims → corroboration; new claims → chained federated evidence
- v0.3: outcome ledger reprices peer trust (Beta posterior, outcomes ×2)
- v0.5: signed hypothesis exchange + **cross-node adversarial review** —
  peer hypotheses reviewed (UNFALSIFIABLE → rejected), never merged

**Product**
- Installable PWA (PC/Android/iOS), world map, realtime WebSocket channel,
  NEW EVENT DETECTED notifications, ops-center UI
- Python + TypeScript SDKs, `synthesisctl` terminal, reference PostGIS
  schema, $0 deployment guide, 40-test invariant suite in CI
