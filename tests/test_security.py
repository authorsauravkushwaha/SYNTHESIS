"""§24 security-layer invariants: rate limits, audit chain, key comparison."""
import hashlib

from server.security import AuditLog, RateLimiter, check_key
from server.world import GENESIS


def test_rate_limiter_allows_then_blocks():
    rl = RateLimiter({"POST": (3, 60.0)})
    t = 1000.0
    results = [rl.allow("1.2.3.4", "POST", t)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_rate_limiter_refills_over_time():
    rl = RateLimiter({"POST": (3, 60.0)})
    t = 1000.0
    for _ in range(3):
        rl.allow("c", "POST", t)
    assert rl.allow("c", "POST", t)[0] is False
    assert rl.allow("c", "POST", t + 25.0)[0] is True     # ~1 token refilled


def test_rate_limiter_isolates_clients():
    rl = RateLimiter({"POST": (1, 60.0)})
    t = 500.0
    assert rl.allow("a", "POST", t)[0] is True
    assert rl.allow("a", "POST", t)[0] is False
    assert rl.allow("b", "POST", t)[0] is True            # other client unaffected


def test_audit_log_is_hash_chained():
    log = AuditLog()
    log.record("1.2.3.4", "auth_denied", "/api/federation/peers")
    log.record("1.2.3.4", "privileged_call", "/api/federation/peers", "retry with key")
    prev = GENESIS
    for rec in log.chain.records:
        assert rec["prev_hash"] == prev
        assert hashlib.sha256(f"{prev}|{rec['payload']}".encode()).hexdigest() == rec["hash"]
        prev = rec["hash"]
    assert prev == log.chain.head


def test_audit_entries_truncate_hostile_input():
    log = AuditLog()
    e = log.record("x" * 500, "y" * 500, "z" * 500, "w" * 500)
    assert len(e["actor"]) <= 80 and len(e["action"]) <= 40
    assert len(e["object"]) <= 120 and len(e["detail"]) <= 200


def test_check_key_open_mode_by_default():
    # ADMIN_KEY unset in the test environment → demo-open mode admits all
    assert check_key("") is True
    assert check_key("anything") is True
