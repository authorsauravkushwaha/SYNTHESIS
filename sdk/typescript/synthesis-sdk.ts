/**
 * synthesis-sdk (TypeScript) — zero-dependency client for the SYNTHESIS
 * Evidence-Carrying Causal World Model. Works in Node 18+, browsers and Deno
 * (global fetch + WebCrypto).
 *
 *   import { SynthesisClient } from "./synthesis-sdk";
 *   const c = new SynthesisClient("http://localhost:8000");
 *   const events = await c.events();
 *   const { valid, records } = await c.verifyChain();   // independent check
 *
 * Like the platform itself, the SDK never hides uncertainty: every hypothesis
 * arrives with its evidence ids, assumptions, falsifiers and confidence.
 */

export type EdgeStatus =
  | "observed" | "strongly_supported" | "plausible"
  | "uncertain" | "contradicted" | "unknown";

export interface Evidence {
  id: string; source: string; source_type: string; reliability: number;
  independence: string; classification: string; statement: string;
  domain: string; observed_at: string; ingested_at: string;
  content_hash: string; chain_seq: number;
}

export interface WorldEvent {
  id: string; title: string; domain: string;
  severity: "low" | "medium" | "high"; status: string;
  detected_at: string; location: string; lat: number; lon: number;
  summary: string; entity_ids: string[]; evidence_ids: string[];
}

export interface ConeNode {
  id: string; label: string; layer: number; domain: string; kind?: string;
  projected_impact?: string; impact_score?: number;
}

export interface ConeEdge {
  source: string; target: string; status: EdgeStatus;
  mechanism: string; lag: string; confidence: number;
}

export interface ImpactCone { event_id: string; nodes: ConeNode[]; edges: ConeEdge[]; }

export interface Watchpoint { id: string; label: string; signal: string; direction: string; }

export interface Hypothesis {
  id: string; event_id: string; label: string; claim: string;
  mechanism: string[]; assumptions: string[]; falsifiers: string[];
  evidence_ids: string[]; counter_evidence_ids: string[];
  watchpoints: Watchpoint[]; confidence: number; status: string;
  evidence?: Evidence[]; counter_evidence?: Evidence[];
}

export interface AdversarialFinding { type: string; severity: string; note: string; }

export interface ChallengeResult {
  hypothesis_id: string; agent: string; generated_at: string;
  findings: AdversarialFinding[]; stated_confidence: number;
  adversarial_adjusted_confidence: number; verdict: string;
}

export interface Forecast {
  id: string; hypothesis_id: string; event_id: string; prediction: string;
  probability: number; forecast_window: string; created_at: string;
  expires_at: string; expected_indicators: string[]; model_version: string;
  status: "open" | "correct" | "partially_correct" | "failed";
  outcome: { observed: string; verdict: string; observed_at: string;
             calibration_note: string } | null;
}

export interface GlobalState {
  generated_at: string; active_observations: number; cross_domain_events: number;
  active_events: number; active_hypotheses: number; forecasts_open: number;
  forecasts_awaiting_outcomes: number; unresolved_contradictions: number;
  model_calibration_pct: number; mean_brier: number; model_version: string;
  chain_head: string; chain_length: number;
}

export interface CounterfactualBranch {
  event_id: string; scenario: { duration_hours: number; recovery: string };
  generated_at: string; model_version: string; caveat: string;
  nodes: ConeNode[]; edges: ConeEdge[]; narrative: string[]; event_title: string;
}

export interface ChainVerification { valid: boolean; records: number; head: string; failedAt?: number; }

const GENESIS = "0".repeat(64);

async function sha256hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

export class SynthesisClient {
  constructor(private base: string = "http://localhost:8000") {
    this.base = base.replace(/\/+$/, "");
  }

  private async get<T>(path: string): Promise<T> {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
    return r.json() as Promise<T>;
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    const r = await fetch(this.base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) throw new Error(`POST ${path} -> ${r.status}`);
    return r.json() as Promise<T>;
  }

  /* ---- world state ---- */
  state()                      { return this.get<GlobalState>("/api/state"); }
  feed(limit = 12)             { return this.get<Evidence[]>(`/api/feed?limit=${limit}`); }
  events()                     { return this.get<WorldEvent[]>("/api/events"); }
  event(id: string)            { return this.get<WorldEvent>(`/api/events/${id}`); }
  impactCone(eventId: string)  { return this.get<ImpactCone>(`/api/events/${eventId}/cone`); }
  hypotheses(eventId: string)  { return this.get<Hypothesis[]>(`/api/events/${eventId}/hypotheses`); }
  hypothesis(id: string)       { return this.get<Hypothesis>(`/api/hypotheses/${id}`); }
  evidence(id: string)         { return this.get<Evidence>(`/api/evidence/${id}`); }
  contradictions()             { return this.get<unknown[]>("/api/contradictions"); }
  forecasts()                  { return this.get<Forecast[]>("/api/forecasts"); }
  ledger()                     { return this.get<{ resolved_forecasts: Forecast[]; open_forecasts: Forecast[] }>("/api/ledger"); }
  calibration()                { return this.get<unknown>("/api/calibration"); }
  agents()                     { return this.get<unknown[]>("/api/agents"); }
  ingestStatus()               { return this.get<unknown>("/api/ingest/status"); }

  /* ---- analysis actions ---- */
  challenge(hypId: string) {
    return this.post<ChallengeResult>(`/api/hypotheses/${hypId}/challenge`);
  }

  counterfactual(eventId: string, durationHours = 168,
                 recovery: "immediate" | "normal" | "slow" = "normal") {
    return this.post<CounterfactualBranch>("/api/counterfactual", {
      event_id: eventId, duration_hours: durationHours, recovery,
    });
  }

  /* ---- realtime ---- */
  /** Read-only world updates. Returns the WebSocket; caller owns its lifecycle. */
  live(onUpdate: (msg: { state: GlobalState; feed: Evidence[] }) => void): WebSocket {
    const url = this.base.replace(/^http/, "ws") + "/ws";
    const ws = new WebSocket(url);
    ws.onmessage = (ev: MessageEvent) => {
      const d = JSON.parse(String(ev.data));
      if (d.type === "world_update") onUpdate(d);
    };
    return ws;
  }

  /* ---- validation API: trust nothing, verify locally ---- */
  async exportChain(): Promise<string> {
    const r = await fetch(this.base + "/api/ledger/export");
    if (!r.ok) throw new Error(`export -> ${r.status}`);
    return r.text();
  }

  /** Re-verify the tamper-evident evidence chain in the client,
   *  independent of the server's own arithmetic. */
  async verifyChain(): Promise<ChainVerification> {
    const lines = (await this.exportChain()).trim().split("\n").slice(1);
    let prev = GENESIS, n = 0;
    for (const line of lines) {
      const idx1 = line.indexOf("\t"), idx2 = line.indexOf("\t", idx1 + 1),
            idx3 = line.indexOf("\t", idx2 + 1);
      const prevHash = line.slice(idx1 + 1, idx2);
      const stored = line.slice(idx2 + 1, idx3);
      const payload = line.slice(idx3 + 1);
      if (prevHash !== prev) return { valid: false, records: n, head: prev, failedAt: n };
      const computed = await sha256hex(`${prevHash}|${payload}`);
      if (computed !== stored) return { valid: false, records: n, head: prev, failedAt: n };
      prev = stored; n++;
    }
    return { valid: true, records: n, head: prev };
  }
}
