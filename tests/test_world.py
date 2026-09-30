"""SYNTHESIS world-model invariants — the properties the vision promises."""
import hashlib

import pytest

from server.world import World, GENESIS


@pytest.fixture(scope="module")
def w():
    return World()


# ---- tamper-evident chain (§21, §42) ---------------------------------------

def test_chain_valid(w):
    prev = GENESIS
    for rec in w.chain.records:
        assert rec["prev_hash"] == prev
        computed = hashlib.sha256(f"{prev}|{rec['payload']}".encode()).hexdigest()
        assert computed == rec["hash"]
        prev = rec["hash"]
    assert prev == w.chain.head


def test_chain_detects_tampering(w):
    prev = GENESIS
    broken = 0
    for i, rec in enumerate(w.chain.records):
        payload = rec["payload"] + "x" if i == 1 else rec["payload"]  # tamper record 1
        if hashlib.sha256(f"{prev}|{payload}".encode()).hexdigest() != rec["hash"]:
            broken += 1
        prev = rec["hash"]
    assert broken == 1


# ---- evidence discipline (§15, §28) ------------------------------------------

def test_every_hypothesis_evidence_exists(w):
    for h in w.hypotheses.values():
        for eid in h["evidence_ids"] + h["counter_evidence_ids"]:
            assert eid in w.evidence, f"{h['id']} references missing evidence {eid}"


def test_every_hypothesis_is_falsifiable(w):
    for h in w.hypotheses.values():
        assert h["falsifiers"], f"{h['id']} has no falsification conditions"
        assert h["watchpoints"], f"{h['id']} generates no watchpoints"
        assert 0.0 <= h["confidence"] <= 1.0


def test_evidence_metadata_complete(w):
    for e in w.evidence.values():
        for field in ("source", "reliability", "independence", "classification",
                      "observed_at", "ingested_at", "content_hash"):
            assert e.get(field) not in (None, ""), f"{e['id']} missing {field}"


# ---- impact cones (§6) ----------------------------------------------------------

VALID_EDGE_STATUS = {"observed", "strongly_supported", "plausible",
                     "uncertain", "contradicted", "unknown"}


def test_cone_edges_typed_and_wired(w):
    for cone in w.cones.values():
        ids = {n["id"] for n in cone["nodes"]}
        for e in cone["edges"]:
            assert e["status"] in VALID_EDGE_STATUS
            assert e["source"] in ids and e["target"] in ids
            assert e["mechanism"], "every edge must state its mechanism"


# ---- counterfactuals (§12) --------------------------------------------------------

def test_counterfactual_monotone_in_duration(w):
    short = w.counterfactual("evt_3101", 12, "normal")
    long = w.counterfactual("evt_3101", 336, "normal")
    s = {n["id"]: n["impact_score"] for n in short["nodes"] if n["layer"] > 0}
    l = {n["id"]: n["impact_score"] for n in long["nodes"] if n["layer"] > 0}
    assert all(l[k] >= s[k] for k in s), "longer disruption must never reduce impact"


def test_counterfactual_recovery_assumption(w):
    slow = w.counterfactual("evt_3101", 168, "slow")
    fast = w.counterfactual("evt_3101", 168, "immediate")
    assert sum(n["impact_score"] for n in slow["nodes"]) > \
           sum(n["impact_score"] for n in fast["nodes"])
    assert "caveat" in slow  # scenario analysis, not certainty


# ---- adversarial agent (§14) ---------------------------------------------------------

def test_challenge_never_increases_confidence(w):
    for hid in ("hyp_442", "hyp_451", "hyp_461"):
        r = w.challenge(hid)
        assert r["adversarial_adjusted_confidence"] <= r["stated_confidence"]
        assert r["findings"], "agreement is not truth — the agent must always probe"


def test_challenge_flags_correlated_sources(w):
    r = w.challenge("hyp_442")
    # obs_18443 sibling correlation must surface somewhere in event's hypotheses
    types = {f["type"] for f in r["findings"]}
    assert "alternative_explanation" in types
    assert "unverified_assumption" in types


# ---- calibration & ledger (§10, §36) ---------------------------------------------------

def test_calibration_buckets_sane(w):
    cal = w.calibration()
    assert cal["total_resolved"] >= 100
    for b in cal["reliability_buckets"]:
        assert 0 <= b["predicted"] <= 1 and 0 <= b["observed"] <= 1
    assert 0 < cal["mean_brier"] < 0.5


def test_forecasts_pinned_to_model_version(w):
    for f in w.forecasts.values():
        assert f["model_version"], "forecast must stay pinned to its model version"


def test_contradictions_preserve_both_claims(w):
    for c in w.contradictions.values():
        assert c["claim_a"]["claim"] and c["claim_b"]["claim"]
        assert c["status"] in {"UNRESOLVED", "PARTIALLY_RESOLVED", "RESOLVED"}
