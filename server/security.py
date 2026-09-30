"""
SYNTHESIS — API security layer (vision §24, §41, §52).

Three things the security docs promise, turned into code:

  * rate limiting  — in-memory token buckets per client / method class;
  * authentication — optional API-key enforcement for privileged routes
    (set SYNTHESIS_ADMIN_KEY to enforce; unset = open demo mode, honestly
    reported at /api/security/status — never silently insecure);
  * audit trail    — every privileged action and every auth/rate-limit
    denial is appended to a **tamper-evident hash chain**, the same
    construction as the evidence chain, verifiable with the same C tool.

Secrets never live in code: the admin key comes from the environment.
"""

from __future__ import annotations

import hmac
import json
import os
import time

from .world import EvidenceChain, iso, now

ADMIN_KEY = os.environ.get("SYNTHESIS_ADMIN_KEY", "")
AUTH_MODE = "enforced" if ADMIN_KEY else "demo-open"

# routes that mutate trust boundaries → privileged when auth is enforced
PRIVILEGED_PREFIXES = ("/api/federation/peers", "/api/federation/sync")

RATE_LIMITS = {"GET": (240, 60.0), "POST": (40, 60.0)}   # (requests, per seconds)


def check_key(provided: str) -> bool:
    """Constant-time comparison; never log or echo the provided key."""
    if not ADMIN_KEY:
        return True
    return hmac.compare_digest(provided or "", ADMIN_KEY)


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
             f"auth={AUTH_MODE}; rate limits GET {RATE_LIMITS['GET'][0]}/min, "
             f"POST {RATE_LIMITS['POST'][0]}/min")


def status() -> dict:
    return {
        "auth_mode": AUTH_MODE,
        "note": ("Privileged routes (federation peer management) require the "
                 "X-Api-Key header." if AUTH_MODE == "enforced" else
                 "Open demo mode — set SYNTHESIS_ADMIN_KEY to enforce API keys "
                 "on privileged routes. This status is always reported honestly."),
        "privileged_routes": list(PRIVILEGED_PREFIXES),
        "rate_limits_per_min": {m: int(v[0]) for m, v in RATE_LIMITS.items()},
        "audit_records": len(AUDIT.entries),
        "audit_chain_head": AUDIT.chain.head,
        "principle": "Never trust an input merely because it is connected (§50).",
    }
