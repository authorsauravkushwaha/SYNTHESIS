# SYNTHESIS Protocol v0 (`synthesis-fed/0.1`)

Federated signed-observation exchange between SYNTHESIS nodes (vision §43).
Design goal: **federation as epistemology, not sync** — exchanging claims
between independent nodes must *strengthen* the evidence model, never
duplicate or corrupt it.

## 1. Identity — proven, never claimed

Each node holds an Ed25519 keypair. Its identity is *derived*:

```
node_id = hex( sha256( raw_public_key ) )[:12]
```

A node cannot claim an id — receivers recompute the derivation from the
public key in every bundle. `GET /api/federation/identity`:

```json
{
  "protocol": "synthesis-fed/0.1",
  "node_id": "3fb2a1c04d9e",
  "name": "node-india",
  "pubkey": "<64 hex chars, raw Ed25519 public key>"
}
```

Deterministic demo identities: set `SYNTHESIS_NODE_SEED` (key material is
sha256 of the seed) and `SYNTHESIS_NODE_NAME`.

## 2. Observation bundle

`GET /api/federation/observations` returns:

```json
{
  "protocol": "synthesis-fed/0.1",
  "node": { "protocol": "...", "node_id": "...", "name": "...", "pubkey": "..." },
  "generated_at": "2026-10-01T09:00:00Z",
  "observations": [
    {
      "id": "obs_18422",
      "source": "IMD numerical model",
      "source_type": "weather_model",
      "statement": "…",
      "domain": "weather",
      "reliability": 0.93,
      "observed_at": "2026-10-01T02:00:00Z",
      "content_hash": "<local chain hash at origin node>"
    }
  ],
  "signature": "<hex Ed25519 signature>"
}
```

### Signing

```
signature = Ed25519_sign( private_key,
                          canonical_json( bundle_without_signature ) )
canonical_json = JSON, sorted keys, separators (",", ":"), UTF-8
```

## 3. Receiver obligations (in order — no step may be skipped)

1. **Size cap** the response (2 MB) before parsing.
2. **Verify identity derivation**: `node_id == sha256(pubkey)[:12]`.
3. **Verify signature** over canonical JSON minus `signature`.
4. Only then read observations — each one **schema-validated, clamped and
   truncated**; statements are data, never instructions.
5. Classify each observation:
   - statement matches local evidence → mark local record
     `corroborated_by:<node_id>` (**corroboration**, not duplication);
   - statement is new → append to the local tamper-evident chain with
     `independence = federated:<node_id>` and reliability discounted ×0.95
     (transitive trust decays).
6. Rejected items/bundles are **counted and reported** in
   `GET /api/federation/status` — failure is visible, never silent (§51).

## 4. Peering

```
POST /api/federation/peers   { "url": "https://node-b.example.org" }
POST /api/federation/sync    (manual)  — otherwise auto-sync every 60 s
GET  /api/federation/status  identity + per-peer imported/corroborated/rejected
```

Peering is **pull-only**: a node fetches from peers; nothing is pushed into
it. Combined with signature-before-content, a malicious peer's maximum power
is to offer bad *data* — which then competes in the normal evidence model
(reliability, independence, contradiction objects) like any other source.

## 5. Non-goals of v0

No consensus, no global ordering, no shared database. Nodes may disagree —
disagreement between nodes is *information* and can surface as contradiction
objects, exactly like disagreeing sources.

## 6. Learned peer trust (v0.2 — implemented)

Trust is earned from behavior, never asserted:

```
trust = (1 + corroborated) / (2 + corroborated + rejected)     # Beta posterior mean
import_discount = min(0.98, 0.65 + 0.6 × trust)
```

Corroborations are successes, rejections (bad signatures, malformed items)
are failures, novel imports stay neutral until the outcome ledger can score
them (v0.3). A neutral peer's imports are discounted ×0.95; a hostile peer
decays toward ×0.65; a consistently corroborated peer caps at ×0.98 —
federated evidence can never quite reach first-hand reliability.

## 7. Roadmap

- v0.3: peer trust fed by the **outcome ledger** — a node whose observations
  keep being falsified loses weight, mechanically
- v0.4: bundle pagination + since-cursor; per-observation origin signatures
- v0.5: exchange of hypotheses/forecasts/outcomes under the same envelope
