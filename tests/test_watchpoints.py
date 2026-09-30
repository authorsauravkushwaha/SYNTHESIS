"""Watchpoint auto-evaluation (§11): the loop closes itself, traceably."""
from server.world import World


def test_matching_evidence_moves_confidence_and_attaches():
    w = World()
    h = w.hypotheses["hyp_442"]
    before = h["confidence"]
    w.obs_counter += 1
    eid = f"obs_{w.obs_counter}"
    w._evidence(eid, "test feed", "sensor", 0.9,
                "Visakhapatnam anchorage median dwell +43% vs baseline.", "maritime")
    assert h["confidence"] == round(before + 0.05, 2)      # wp_1 fired
    assert eid in h["evidence_ids"]                        # attached as support
    wp1 = next(wp for wp in h["watchpoints"] if wp["id"] == "wp_1")
    assert wp1["hits"] and wp1["hits"][-1]["evidence_id"] == eid


def test_negative_watchpoint_attaches_counter_evidence():
    w = World()
    artifact = w.hypotheses["hyp_444"]                     # measurement-artifact hypothesis
    before = artifact["confidence"]
    w.obs_counter += 1
    eid = f"obs_{w.obs_counter}"
    w._evidence(eid, "test feed", "sensor", 0.9,
                "Visakhapatnam dwell rising sharply.", "maritime")
    assert artifact["confidence"] < before                 # weakened
    assert eid in artifact["counter_evidence_ids"]         # attached as counter


def test_same_evidence_never_double_counted():
    w = World()
    h = w.hypotheses["hyp_442"]
    w.obs_counter += 1
    eid = f"obs_{w.obs_counter}"
    rec = w._evidence(eid, "test feed", "sensor", 0.9,
                      "Visakhapatnam dwell +50%.", "maritime")
    after_first = h["confidence"]
    w._evaluate_watchpoints(rec)                           # re-evaluate same record
    assert h["confidence"] == after_first


def test_unrelated_evidence_does_nothing():
    w = World()
    snapshot = {hid: h["confidence"] for hid, h in w.hypotheses.items()}
    w.obs_counter += 1
    w._evidence(f"obs_{w.obs_counter}", "test feed", "news", 0.5,
                "Completely unrelated statement about weather in Iceland.", "weather")
    assert snapshot == {hid: h["confidence"] for hid, h in w.hypotheses.items()}


def test_confidence_stays_clamped():
    w = World()
    h = w.hypotheses["hyp_442"]
    for i in range(30):
        w.obs_counter += 1
        w._evidence(f"obs_{w.obs_counter}", "test feed", "sensor", 0.9,
                    f"Visakhapatnam dwell anomaly reading {i}.", "maritime")
    assert h["confidence"] <= 0.97
