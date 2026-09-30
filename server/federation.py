"""
SYNTHESIS Protocol v0 — federated signed-observation exchange (vision §43).

Instead of requiring every organization to send all data to one central
system, each SYNTHESIS node keeps local data and exchanges **signed
observation bundles**:

    NODE A (India)  ⇄  NODE B (Europe)  ⇄  NODE C (Africa)

Design rules (unique to SYNTHESIS — federation as *epistemology*, not sync):

  * Every bundle is Ed25519-signed over its canonical JSON; the node id is
    derived from the public key (sha256(pubkey)[:12]) so identity cannot be
    claimed, only proven.
  * A peer's observation that MATCHES local evidence becomes **independent
    corroboration** (it strengthens, it does not duplicate).
  * A peer's observation that is NEW is imported as evidence with explicit
    federated provenance — and it enters the local tamper-evident chain like
    any other evidence.
  * Peers are untrusted by default (§18): size caps, schema validation,
    signature verification BEFORE any content is read as data; text is
    clamped and stored as data, never instructions.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

from .ingest import _clean_text, _clamp, MAX_BYTES, FETCH_TIMEOUT
from .world import WORLD, iso, now

PROTOCOL = "synthesis-fed/0.1"
SYNC_SECONDS = 60


def canonical(obj: dict) -> bytes:
    """Canonical JSON: the only representation that is ever signed."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def node_id_for(pubkey_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()[:12]


# ---------------------------------------------------------------- identity --

class NodeIdentity:
    def __init__(self) -> None:
        seed = os.environ.get("SYNTHESIS_NODE_SEED")
        if seed:  # deterministic identity for reproducible demos
            raw = hashlib.sha256(seed.encode()).digest()
            self._key = Ed25519PrivateKey.from_private_bytes(raw)
        else:
            self._key = Ed25519PrivateKey.generate()
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat)
        self.pubkey_hex = self._key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw).hex()
        self.node_id = node_id_for(self.pubkey_hex)
        self.name = _clean_text(os.environ.get("SYNTHESIS_NODE_NAME", "node-local"), 40)

    def sign(self, payload: bytes) -> str:
        return self._key.sign(payload).hex()

    def to_dict(self) -> dict:
        return {"protocol": PROTOCOL, "node_id": self.node_id,
                "name": self.name, "pubkey": self.pubkey_hex}


def verify_bundle(bundle: dict) -> tuple[bool, str]:
    """Verify identity derivation + Ed25519 signature BEFORE trusting content."""
    try:
        node = bundle["node"]
        pubkey_hex, claimed_id = node["pubkey"], node["node_id"]
        if node_id_for(pubkey_hex) != claimed_id:
            return False, "node_id does not derive from public key"
        sig = bytes.fromhex(bundle["signature"])
        unsigned = {k: v for k, v in bundle.items() if k != "signature"}
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(pubkey_hex)).verify(sig, canonical(unsigned))
        return True, "ok"
    except InvalidSignature:
        return False, "invalid signature"
    except (KeyError, ValueError, TypeError) as exc:
        return False, f"malformed bundle: {type(exc).__name__}"


# ---------------------------------------------------------------- node -----

@dataclass
class PeerState:
    url: str
    node_id: str = ""
    name: str = ""
    pubkey: str = ""
    reachable: bool | None = None
    last_sync: str | None = None
    imported_new: int = 0
    corroborated: int = 0
    rejected: int = 0
    last_error: str | None = None


class FederationNode:
    def __init__(self) -> None:
        self.identity = NodeIdentity()
        self.peers: dict[str, PeerState] = {}
        self._imported: set[str] = set()          # (peer_id, statement) keys
        self._fed_seq = 0
        self._seed_local_observations()

    # -- unique local signal (so cross-node exchange is visible in demos) ----
    def _seed_local_observations(self) -> None:
        if self.identity.name == "node-local":
            return
        WORLD.obs_counter += 1
        WORLD._evidence(
            f"obs_{WORLD.obs_counter}",
            f"{self.identity.name} coastal radar", "sensor", 0.84,
            f"[{self.identity.name}] Independent radar: 3 vessels holding 25 km "
            "offshore Visakhapatnam, consistent with anchorage dispersal.",
            "maritime")
        WORLD.obs_counter += 1
        WORLD._evidence(
            f"obs_{WORLD.obs_counter}",
            f"{self.identity.name} field report", "official", 0.8,
            f"[{self.identity.name}] District control room confirms NH-16 staging "
            "areas at 90% truck capacity.",
            "infrastructure")

    # -- outbound ---------------------------------------------------------
    def outbound_bundle(self, limit: int = 25) -> dict:
        WORLD.tick()
        obs = sorted(WORLD.evidence.values(),
                     key=lambda r: r["observed_at"], reverse=True)[:limit]
        bundle = {
            "protocol": PROTOCOL,
            "node": self.identity.to_dict(),
            "generated_at": iso(now()),
            "observations": [{
                "id": o["id"], "source": o["source"], "source_type": o["source_type"],
                "statement": o["statement"], "domain": o["domain"],
                "reliability": o["reliability"], "observed_at": o["observed_at"],
                "content_hash": o["content_hash"],
            } for o in obs],
        }
        bundle["signature"] = self.identity.sign(canonical(bundle))
        return bundle

    # -- inbound ------------------------------------------------------------
    def ingest_bundle(self, bundle: dict, peer: PeerState) -> None:
        ok, reason = verify_bundle(bundle)
        if not ok:
            peer.rejected += 1
            peer.last_error = f"bundle rejected: {reason}"
            return
        node = bundle["node"]
        peer.node_id, peer.name = node["node_id"], _clean_text(node["name"], 40)
        peer.pubkey = node["pubkey"]
        local_statements = {e["statement"]: e for e in WORLD.evidence.values()}
        for o in bundle.get("observations", [])[:50]:
            try:
                stmt = _clean_text(str(o["statement"]), 300)
                rel = _clamp(float(o["reliability"]), 0.0, 1.0)
                domain = _clean_text(str(o["domain"]), 20) or "unknown"
                stype = _clean_text(str(o["source_type"]), 20) or "federated"
                src = _clean_text(str(o["source"]), 60)
            except (KeyError, TypeError, ValueError):
                peer.rejected += 1
                continue
            key = f"{peer.node_id}|{stmt}"
            if key in self._imported:
                continue
            self._imported.add(key)
            if stmt in local_statements:
                # federation as corroboration: same claim, independent node
                local = local_statements[stmt]
                local["independence"] = f"corroborated_by:{peer.node_id}"
                peer.corroborated += 1
            else:
                WORLD.obs_counter += 1
                eid = f"obs_{WORLD.obs_counter}"
                WORLD._evidence(
                    eid, f"{src} ⇄ {peer.name}", stype, round(rel * 0.95, 2),
                    stmt, domain, independence=f"federated:{peer.node_id}")
                peer.imported_new += 1

    # -- peer management --------------------------------------------------------
    def add_peer(self, url: str) -> PeerState:
        url = url.rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("peer url must be http(s)")
        peer = self.peers.get(url) or PeerState(url=url)
        self.peers[url] = peer
        return peer

    def sync_peer(self, peer: PeerState) -> None:
        try:
            req = urllib.request.Request(
                peer.url + "/api/federation/observations",
                headers={"User-Agent": f"SYNTHESIS-fed/{self.identity.node_id}"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("bundle exceeds size cap")
            self.ingest_bundle(json.loads(raw), peer)
            peer.reachable = True
            peer.last_sync = iso(now())
            if not (peer.last_error or "").startswith("bundle rejected"):
                peer.last_error = None
        except Exception as exc:                      # controlled failure (§51)
            peer.reachable = False
            peer.last_error = _clean_text(f"{type(exc).__name__}: {exc}", 120)

    def sync_all(self) -> None:
        for peer in list(self.peers.values()):
            self.sync_peer(peer)

    def status(self) -> dict:
        return {
            "identity": self.identity.to_dict(),
            "peers": [vars(p) for p in self.peers.values()],
            "principle": ("Federation is epistemology, not sync: matching claims from "
                          "independent nodes become corroboration; new claims enter the "
                          "local evidence chain with federated provenance; every bundle "
                          "is signature-verified before its content is read as data."),
        }

    async def run(self) -> None:
        import asyncio
        await asyncio.sleep(10)
        while True:
            self.sync_all()
            await asyncio.sleep(SYNC_SECONDS)


NODE = FederationNode()
