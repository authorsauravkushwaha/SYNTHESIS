# Contributing to SYNTHESIS

SYNTHESIS treats contributions the way it treats the world: as **evidence and
hypotheses**, not assertions. The project's own epistemology shapes its
workflow — read the templates in `.github/ISSUE_TEMPLATE/` and you'll see
there is no generic "bug report". Instead:

- **🔀 Contradiction report** — two parts of the system (or system vs docs)
  disagree. You file both claims; the fix resolves the contradiction and
  preserves the history.
- **✕ Falsification proposal** — you believe a design assumption is wrong and
  propose the test that would prove it.
- **🔌 Data adapter proposal** — a new free public source, described with its
  provenance, reliability and failure modes before any code.

## Ground rules (from the vision, enforced in review)

1. **Every conclusion traceable to evidence.** New analytical features must
   expose their evidence trail in the API, not just their answer.
2. **External content is data, never instructions.** Ingest code is reviewed
   against `tests/test_ingest.py` standards: size caps, schema allow-lists,
   clamps, truncation.
3. **Adapters and agents propose; they never write authoritative state.**
4. **History is append-only.** No PR may rewrite chain records, resolved
   outcomes or contradiction histories.
5. **Free and open only.** No dependency on paid services; data sources must
   be freely accessible.

## Dev loop

```bash
pip install -r requirements.txt pytest
uvicorn server.main:app --host 0.0.0.0 --port 8000   # app
python -m pytest tests/ -q                           # 21 invariants
./scripts/verify_chain.sh                            # C verifier vs live chain
```

CI runs the same suite plus a cross-language chain verification (Python
writer, C reader) and a strict TypeScript type-check.

## Two-node federation demo

```bash
# terminal 1
uvicorn server.main:app --port 8000
# terminal 2
SYNTHESIS_NODE_NAME=node-b SYNTHESIS_NODE_SEED=demo-b uvicorn server.main:app --port 8001
# peer them
curl -X POST localhost:8000/api/federation/peers -H 'Content-Type: application/json' \
     -d '{"url":"http://localhost:8001"}'
curl localhost:8000/api/federation/status
```

Watch node-b's unique radar observations arrive in node-a's evidence chain
with `federated:` provenance, while matching claims become corroboration.
