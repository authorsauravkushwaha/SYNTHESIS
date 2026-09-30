<!-- SYNTHESIS PR = a hypothesis with evidence. -->

## Claim
<!-- What does this change make true? One sentence. -->

## Evidence
<!-- Tests added/updated, benchmark output, screenshots, reproduction. -->

## Assumptions
<!-- What must hold for this to be correct? -->

## Falsifiers
<!-- What outcome after merge would prove this change wrong? -->

## Invariants checklist
- [ ] `python -m pytest tests/ -q` passes
- [ ] History stays append-only (no rewriting chain records / resolved outcomes)
- [ ] External content stays data, never instructions
- [ ] New analytical output exposes its evidence trail
- [ ] No paid dependency introduced
