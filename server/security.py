"""
SYNTHESIS — API security layer (vision §24, §41, §52).

Three things the security docs promise, turned into code:

  * rate limiting  — in-memory token buckets per client / method class;
  * authentication — optional API-key enforcement for privileged routes
    (set SYNTHESIS_ADMIN_KEY to enforce; unset = open demo mode, honestly
    reported at /api/security/status — never silently insecure);
  * RBAC + rotation — admin / analyst / viewer roles with runtime key
    rotation that invalidates the old key immediately (§24);
  * audit trail    — every privileged action and every auth/rate-limit
    denial is appended to a **tamper-evident hash chain**, the same
    construction as the evidence chain, verifiable with the same C tool.

Secrets never live in code: the admin key comes from the environment.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time

from .world import EvidenceChain, iso, now

# RBAC (§24): two credentialed roles + the implicit read-only viewer.
#   admin   — trust-boundary mutations (federation peers/sync, key rotation)
#   analyst — analysis mutations (adversarial challenge, counterfactuals),
#             enforced only once an analyst key exists
#   viewer  — all GET endpoints; never needs a key
# Keys live in mutable module state so they can be ROTATED at runtime
# (POST /api/security/rotate, admin-only). Restart reverts to the env vars —
# the demo is deliberately stateless.
KEYS = {
    "admin": os.environ.get("SYNTHESIS_ADMIN_KEY", ""),
    "analyst": os.environ.get("SYNTHESIS_ANALYST_KEY", ""),
}

# routes that mutate trust boundaries → privileged when auth is enforced
PRIVILEGED_PREFIXES = ("/api/federation/peers", "/api/federation/sync",
                       "/api/security/rotate")
# analysis mutations → analyst-or-admin once an analyst key is configured
ANALYST_PREFIXES = ("/api/hypotheses", "/api/counterfactual")

RATE_LIMITS = {"GET": (240, 60.0), "POST": (40, 60.0)}   # (requests, per seconds)


def auth_mode() -> str:
    return "enforced" if KEYS["admin"] else "demo-open"


def role_of(provided: str) -> str | None:
    """Map a presented key to its role. Constant-time; never logs the key."""
    p = provided or ""
    if KEYS["admin"] and hmac.compare_digest(p, KEYS["admin"]):
        return "admin"
    if KEYS["analyst"] and hmac.compare_digest(p, KEYS["analyst"]):
        return "analyst"
    return None


def check_key(provided: str) -> bool:
    """Admin gate. Open demo mode (no admin key) admits everyone — honestly."""
    if not KEYS["admin"]:
        return True
    return role_of(provided) == "admin"


def analyst_allowed(provided: str) -> bool:
    """Analyst gate: open until an analyst key exists; then analyst or admin."""
    if not KEYS["analyst"]:
        return True
    return role_of(provided) in ("admin", "analyst")


def rotate(role: str) -> str:
    """Mint a fresh key for `role`, invalidating the old one immediately.
    Admin-only (enforced by the middleware); rejected in demo-open mode.
    Rotating a not-yet-configured analyst key MINTS it, enabling the gate.
    The key itself is returned exactly once and never written to the audit."""
    if role not in KEYS:
        raise ValueError(f"unknown role: {role!r}")
    if not KEYS["admin"]:
        raise RuntimeError("demo-open mode has no keys to rotate — "
                           "set SYNTHESIS_ADMIN_KEY first")
    new_key = secrets.token_hex(24)
    minted = not KEYS[role]
    KEYS[role] = new_key
    AUDIT.record("admin", "key_minted" if minted else "key_rotated",
                 f"role:{role}", "old key invalidated immediately" if not minted
                 else "gate now enforced for this role")
    return new_key


class RateLimiter:
    """Token bucket per (client, method-class). In-memory by design for the
    MVP — the production target is the Redis bucket in docker-compose."""

    def __init__(self, limits: dict | None = None) -> None:
        self.limits = limits or RATE_LIMITS
        self.buckets: dict[tuple, list] = {}     # key -> [tokens, last_refill]

    def allow(self, client: str, method: str, now_s: float | None = None) -> tuple[bool, int]:
        cap, per = self.limits.get(method) or self.limits.get("GET") or (240, 60.0)
        t = time.monotonic() if now_s is None else now_s
        tokens, last = self.buckets.get((client, method), (float(cap), t))
        tokens = min(float(cap), tokens + (t - last) * cap / per)
        if tokens >= 1.0:
            self.buckets[(client, method)] = [tokens - 1.0, t]
            return True, int(tokens - 1)
        self.buckets[(client, method)] = [tokens, t]
        return False, 0


class AuditLog:
    """Append-only, hash-chained audit trail (§42 applied to §24)."""

    def __init__(self) -> None:
        self.chain = EvidenceChain()
        self.entries: list[dict] = []

    def record(self, actor: str, action: str, obj: str, detail: str = "") -> dict:
        entry = {
            "seq": len(self.entries),
            "at": iso(now()),
            "actor": actor[:80],
            "action": action[:40],
            "object": obj[:120],
            "detail": detail[:200],
        }
        payload = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        chained = self.chain.append(payload)
        entry["hash"] = chained["hash"]
        self.entries.append(entry)
        return entry

    def tail(self, n: int = 50) -> list[dict]:
        return self.entries[-n:][::-1]


LIMITER = RateLimiter()
AUDIT = AuditLog()
AUDIT.record("system", "startup", "security-layer",
             f"auth={auth_mode()}; rate limits GET {RATE_LIMITS['GET'][0]}/min, "
             f"POST {RATE_LIMITS['POST'][0]}/min")


def status() -> dict:
    mode = auth_mode()
    return {
        "auth_mode": mode,
        "note": ("Privileged routes (federation peer management, key rotation) "
                 "require the X-Api-Key header." if mode == "enforced" else
                 "Open demo mode — set SYNTHESIS_ADMIN_KEY to enforce API keys "
                 "on privileged routes. This status is always reported honestly."),
        "rbac": {
            "roles": {
                "admin": "configured" if KEYS["admin"] else "not configured",
                "analyst": ("configured" if KEYS["analyst"] else
                            "not configured — analysis routes open"),
                "viewer": "implicit (all GET endpoints, no key)",
            },
            "analyst_routes": [p + " (POST)" for p in ANALYST_PREFIXES],
            "rotation": "POST /api/security/rotate {role} — admin-only; "
                        "old key invalidated immediately",
        },
        "privileged_routes": list(PRIVILEGED_PREFIXES),
        "rate_limits_per_min": {m: int(v[0]) for m, v in RATE_LIMITS.items()},
        "audit_records": len(AUDIT.entries),
        "audit_chain_head": AUDIT.chain.head,
        "principle": "Never trust an input merely because it is connected (§50).",
    }
