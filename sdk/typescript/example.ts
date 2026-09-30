/** Walk the SYNTHESIS intelligence loop from TypeScript (Node 18+).
 *  Run:  npx tsx example.ts [base-url]      (or compile with tsc) */
import { SynthesisClient } from "./synthesis-sdk";

declare const process: { argv: string[] } | undefined;

async function main(): Promise<void> {
  const base = (typeof process !== "undefined" && process?.argv[2]) || "http://localhost:8000";
  const c = new SynthesisClient(base);

  const s = await c.state();
  console.log(`GLOBAL STATE  obs=${s.active_observations}  calibration=${s.model_calibration_pct}%  chain=#${s.chain_length}`);

  const [ev] = await c.events();
  console.log(`EVENT  ${ev.title}`);

  const cone = await c.impactCone(ev.id);
  console.log(`IMPACT CONE  ${cone.nodes.length} nodes / ${cone.edges.length} edges`);

  const [hyp] = await c.hypotheses(ev.id);
  const adv = await c.challenge(hyp.id);
  console.log(`ADVERSARIAL  ${adv.findings.length} findings → ${Math.round(adv.adversarial_adjusted_confidence * 100)}%`);

  const cf = await c.counterfactual(ev.id, 24, "immediate");
  console.log(`COUNTERFACTUAL  ${cf.narrative[0]}`);

  const chain = await c.verifyChain();
  console.log(`CHAIN VERIFY (client-side): ${chain.valid ? "VALID" : "INVALID"} — ${chain.records} records`);
}

main().catch((e) => { console.error(e); });
