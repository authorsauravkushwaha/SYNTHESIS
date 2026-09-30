#!/usr/bin/env python3
"""Walk the full SYNTHESIS intelligence loop from code (vision §47)."""
import sys

from synthesis_sdk import SynthesisClient

c = SynthesisClient(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")

s = c.state()
print(f"GLOBAL STATE  obs={s['active_observations']}  calibration={s['model_calibration_pct']}%  "
      f"chain=#{s['chain_length']} {s['chain_head'][:12]}…\n")

ev = c.events()[0]
print(f"EVENT  {ev['title']}")

cone = c.impact_cone(ev["id"])
print(f"IMPACT CONE  {len(cone['nodes'])} nodes / {len(cone['edges'])} edges")
for e in cone["edges"][:3]:
    print(f"  [{e['status']}] {e['source']} → {e['target']}  ({e['mechanism'][:60]}…)")

hyp = c.hypotheses(ev["id"])[0]
print(f"\nHYPOTHESIS {hyp['label']}  ({int(hyp['confidence']*100)}%)  {hyp['claim'][:80]}…")
print("  falsifiers:", "; ".join(hyp["falsifiers"])[:100], "…")

adv = c.challenge(hyp["id"])
print(f"\nADVERSARIAL  {len(adv['findings'])} findings → adjusted "
      f"{int(adv['adversarial_adjusted_confidence']*100)}%  — {adv['verdict'][:60]}")

cf = c.counterfactual(ev["id"], duration_hours=24, recovery="immediate")
worst = max((n for n in cf["nodes"] if n["layer"] > 0), key=lambda n: n["impact_score"])
print(f"\nCOUNTERFACTUAL 24h/immediate → worst node: {worst['label'].replace(chr(10), ' ')} "
      f"({worst['projected_impact']}, {worst['impact_score']})")

ok, n, head = c.verify_chain()
print(f"\nCHAIN VERIFY (client-side, independent): {'VALID' if ok else 'INVALID'} — "
      f"{n} records, head {head[:16]}…")
