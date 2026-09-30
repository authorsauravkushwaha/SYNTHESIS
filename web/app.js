/* SYNTHESIS — Evidence-Carrying Causal World Model — web client */
"use strict";

const $ = (s) => document.querySelector(s);
const api = (p, opt) => fetch(p, opt).then((r) => { if (!r.ok) throw new Error(p); return r.json(); });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const DOMCOLORS = { weather:"#7dd3fc", maritime:"#39d0d8", energy:"#eab308", infrastructure:"#f97316", trade:"#a78bfa", economy:"#f472b6" };
const EDGE_STYLE = {
  observed:            { color:"#22d3a5", dash:"",     w:2.5, label:"observed" },
  strongly_supported:  { color:"#7dd3fc", dash:"",     w:2,   label:"strongly supported" },
  plausible:           { color:"#eab308", dash:"7,4",  w:2,   label:"plausible" },
  uncertain:           { color:"#f97316", dash:"3,4",  w:1.8, label:"uncertain" },
  contradicted:        { color:"#ef4444", dash:"2,3",  w:1.8, label:"contradicted" },
  unknown:             { color:"#64748b", dash:"1,4",  w:1.5, label:"unknown" },
};
const IMPACT_COLOR = { source:"#ef4444", severe:"#ef4444", high:"#f97316", moderate:"#eab308", low:"#38bdf8", minimal:"#334155" };

let EVENTS = [], selectedEvent = null, selectedHyp = null, coneCache = null, worldGeo = null, feedSeen = new Set();

/* ---------------- tabs ---------------- */
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "ledger") refreshLedger();
  if (name === "contra") refreshContradictions();
  if (name === "agents") refreshAgents();
}

/* ---------------- global state ---------------- */
async function refreshState() {
  try {
    const s = await api("/api/state");
    $("#topstats").innerHTML = [
      ["active observations", s.active_observations.toLocaleString()],
      ["cross-domain events", s.cross_domain_events],
      ["active hypotheses", s.active_hypotheses],
      ["forecasts open", s.forecasts_open],
      ["unresolved contradictions", s.unresolved_contradictions],
      ["model calibration", s.model_calibration_pct + "%"],
    ].map(([k, v]) => `<div class="topstat"><b>${v}</b><span>${k}</span></div>`).join("");
    $("#chainpill").textContent = "chain #" + s.chain_length + " · " + s.chain_head.slice(0, 12) + "…";
    $("#stateTiles").innerHTML =
      `<div class="panel-title">GLOBAL STATE</div>` + [
        ["Active observations", s.active_observations.toLocaleString(), 1],
        ["Cross-domain events", s.cross_domain_events, 0],
        ["Active hypotheses", s.active_hypotheses, 0],
        ["Forecasts under observation", s.forecasts_open, 0],
        ["Unresolved contradictions", s.unresolved_contradictions, 0],
        ["Forecasts awaiting outcomes", s.forecasts_awaiting_outcomes, 0],
        ["Model calibration", s.model_calibration_pct + "%", 1],
        ["Mean Brier score", s.mean_brier, 0],
      ].map(([k, v, a]) => `<div class="tile${a ? " accent" : ""}"><b>${v}</b><span>${k}</span></div>`).join("");
  } catch (e) { /* server restarting */ }
}

async function refreshFeed() {
  try {
    const feed = await api("/api/feed?limit=14");
    $("#feed").innerHTML = feed.map((r) => {
      const fresh = !feedSeen.has(r.id);
      feedSeen.add(r.id);
      return `<div class="feeditem${fresh ? " fresh" : ""}" style="border-left-color:${DOMCOLORS[r.domain] || "#1c2a47"}">
        <span class="src">${esc(r.source)}</span> <span class="meta">rel ${r.reliability} · ${esc(r.observed_at)}</span>
        <div>${esc(r.statement)}</div>
        <span class="meta">${r.id} · ${esc(r.classification)} · hash ${r.content_hash.slice(0, 10)}…</span>
      </div>`;
    }).join("");
  } catch (e) {}
}

async function refreshEvents() {
  EVENTS = await api("/api/events");
  $("#eventList").innerHTML = EVENTS.map((ev) => `
    <div class="evrow" data-ev="${ev.id}">
      <span class="sev ${ev.severity}"></span>
      <div><b>${esc(ev.title)}</b>${ev.severity === "high" ? '<span class="newbadge">EVENT DETECTED</span>' : ""}
        <div class="meta">${esc(ev.domain.toUpperCase())} · ${esc(ev.location)} · detected ${esc(ev.detected_at)}</div>
      </div>
    </div>`).join("");
  document.querySelectorAll(".evrow").forEach((r) => r.addEventListener("click", () => openEvent(r.dataset.ev)));
  const sel = $("#eventSelect");
  sel.innerHTML = EVENTS.map((ev) => `<option value="${ev.id}">${esc(ev.title)}</option>`).join("");
  sel.onchange = () => openEvent(sel.value, false);
  if (!selectedEvent && EVENTS.length) loadEvent(EVENTS[0].id);
  drawMap();
}

/* ---------------- world map ---------------- */
async function loadGeo() { try { worldGeo = await api("/world.geo.json"); drawMap(); } catch (e) {} }
function proj(lon, lat, w, h) { return [(lon + 180) / 360 * w, (90 - lat) / 180 * h * (180 / 150)]; } // crop poles slightly
function drawMap() {
  const cv = $("#worldmap"); if (!cv) return;
  const ctx = cv.getContext("2d"), w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#060a14"; ctx.fillRect(0, 0, w, h);
  // graticule
  ctx.strokeStyle = "#0e1830"; ctx.lineWidth = 1;
  for (let lon = -180; lon <= 180; lon += 30) { const [x] = proj(lon, 0, w, h); ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let lat = -60; lat <= 90; lat += 30) { const [, y] = proj(0, lat, w, h); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  if (worldGeo) {
    ctx.fillStyle = "#101d38"; ctx.strokeStyle = "#1e2f52"; ctx.lineWidth = 0.6;
    for (const f of worldGeo.features) {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      for (const poly of polys) {
        ctx.beginPath();
        for (const ring of poly) {
          ring.forEach(([lon, lat], i) => { const [x, y] = proj(lon, lat, w, h); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
          ctx.closePath();
        }
        ctx.fill(); ctx.stroke();
      }
    }
  }
  // event dots
  const t = Date.now() / 600;
  for (const ev of EVENTS) {
    const [x, y] = proj(ev.lon, ev.lat, w, h);
    const base = ev.severity === "high" ? "#ef4444" : ev.severity === "medium" ? "#eab308" : "#22d3a5";
    const pulse = 6 + 4 * Math.abs(Math.sin(t + x));
    ctx.beginPath(); ctx.arc(x, y, pulse + 6, 0, 7); ctx.fillStyle = base + "22"; ctx.fill();
    ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.fillStyle = base; ctx.fill();
    ctx.strokeStyle = "#fff8"; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = "#d7e2f4"; ctx.font = "11px monospace";
    ctx.fillText(ev.title.slice(0, 34) + (ev.title.length > 34 ? "…" : ""), x + 12, y - 6);
  }
  $("#maplegend").innerHTML = `
    <span class="lgd"><i style="background:#ef4444"></i>high severity</span>
    <span class="lgd"><i style="background:#eab308"></i>medium</span>
    <span class="lgd"><i style="background:#22d3a5"></i>low</span>
    <span class="lgd" style="margin-left:auto">${EVENTS.length} active events · equirectangular</span>`;
}
$("#worldmap").addEventListener("click", (e) => {
  const cv = $("#worldmap"), rect = cv.getBoundingClientRect();
  const mx = (e.clientX - rect.left) * cv.width / rect.width, my = (e.clientY - rect.top) * cv.height / rect.height;
  let best = null, bd = 1e9;
  for (const ev of EVENTS) {
    const [x, y] = proj(ev.lon, ev.lat, cv.width, cv.height);
    const d = (x - mx) ** 2 + (y - my) ** 2;
    if (d < bd) { bd = d; best = ev; }
  }
  if (best && bd < 900) openEvent(best.id);
});
setInterval(drawMap, 700);

/* ---------------- event analysis ---------------- */
function openEvent(id, switchTab = true) { if (switchTab) showTab("event"); loadEvent(id); }

async function loadEvent(id) {
  selectedEvent = id; selectedHyp = null; coneCache = null;
  $("#eventSelect").value = id;
  const ev = EVENTS.find((e) => e.id === id) || await api("/api/events/" + id);
  $("#eventSummary").innerHTML = `
    <span class="domain">${esc(ev.domain)} · severity ${esc(ev.severity)} · ${esc(ev.status)}</span>
    <h2>${esc(ev.title)}</h2>
    <div class="evloc">📍 ${esc(ev.location)} · detected ${esc(ev.detected_at)}</div>
    <div>${esc(ev.summary)}</div>
    <div style="margin-top:8px">${ev.evidence_ids.map((e) => `<span class="evchip" data-ev="${e}">${e}</span>`).join("")}</div>`;
  bindEvidenceChips($("#eventSummary"));
  $("#advOut").innerHTML = `<span class="muted">Press “⚔ Challenge this” to attack the selected hypothesis.</span>`;
  $("#hypDetail").innerHTML = `<span class="muted">Select a hypothesis, then use “Why?”, “Challenge this”, or the Falsification Engine.</span>`;
  await Promise.all([renderCone(id), renderHypotheses(id)]);
}

async function renderCone(id, branch = null) {
  const cone = branch || coneCache || await api(`/api/events/${id}/cone`);
  if (!branch) coneCache = cone;
  const svg = $("#coneSvg");
  const layers = {};
  cone.nodes.forEach((n) => (layers[n.layer] = layers[n.layer] || []).push(n));
  const L = Object.keys(layers).map(Number).sort((a, b) => a - b);
  const colW = 205, nodeW = 158, nodeH = 48, W = 60 + L.length * colW, H = 430;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const pos = {};
  L.forEach((l, li) => {
    const col = layers[l], gap = H / (col.length + 1);
    col.forEach((n, i) => (pos[n.id] = { x: 30 + li * colW, y: gap * (i + 1) - nodeH / 2 }));
  });
  let out = "";
  for (const e of cone.edges) {
    const s = pos[e.source], t = pos[e.target]; if (!s || !t) continue;
    const st = EDGE_STYLE[e.status] || EDGE_STYLE.unknown;
    const x1 = s.x + nodeW, y1 = s.y + nodeH / 2, x2 = t.x, y2 = t.y + nodeH / 2, mx = (x1 + x2) / 2;
    out += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none"
      stroke="${st.color}" stroke-width="${st.w}" ${st.dash ? `stroke-dasharray="${st.dash}"` : ""} opacity="0.85">
      <title>${esc(st.label.toUpperCase())} (conf ${e.confidence}) — ${esc(e.mechanism)}${e.lag ? " · lag " + esc(e.lag) : ""}</title></path>`;
  }
  for (const n of cone.nodes) {
    const p = pos[n.id], lines = n.label.split("\n");
    const impact = n.projected_impact;
    const fill = impact ? (IMPACT_COLOR[impact] || "#334155") + (impact === "source" ? "44" : "33") : null;
    const stroke = impact ? (IMPACT_COLOR[impact] || "#334155") : null;
    out += `<g class="conenode${n.kind === "event" ? " event" : ""}">
      <rect x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="8"
        ${fill ? `style="fill:${fill};stroke:${stroke}"` : ""}></rect>
      ${lines.map((ln, i) => `<text x="${p.x + 10}" y="${p.y + 19 + i * 14}">${esc(ln)}</text>`).join("")}
      <text class="dom" x="${p.x + 10}" y="${p.y + nodeH - 5}">${esc((n.domain || "").toUpperCase())}${impact && impact !== "source" ? ` · ${impact.toUpperCase()} (${n.impact_score})` : ""}</text>
      <title>${esc(n.label.replace("\n", " "))}${impact ? ` — projected impact: ${impact} (${n.impact_score})` : ""}</title></g>`;
  }
  svg.innerHTML = out;
  $("#coneLegend").innerHTML = Object.values(EDGE_STYLE).map((s) =>
    `<span><span class="lgline" style="border-color:${s.color};border-top-style:${s.dash ? "dashed" : "solid"}"></span>${s.label}</span>`).join("");
  $("#coneMode").textContent = branch
    ? `COUNTERFACTUAL BRANCH — ${branch.scenario.duration_hours} h disruption, ${branch.scenario.recovery} recovery`
    : "baseline causal model";
  $("#cfNarrative").innerHTML = branch
    ? branch.narrative.map((n) => `<p>⑂ ${esc(n)}</p>`).join("") + `<p class="caveat">${esc(branch.caveat)}</p>`
    : "";
}

async function renderHypotheses(id) {
  const hs = await api(`/api/events/${id}/hypotheses`);
  $("#hypList").innerHTML = hs.map((h) => `
    <div class="hyp" data-h="${h.id}">
      <div class="hyphead"><span class="hlabel">HYPOTHESIS ${h.label}</span><span class="confnum">${Math.round(h.confidence * 100)}%</span></div>
      <div class="claim">${esc(h.claim)}</div>
      <div class="confbar"><i style="width:${h.confidence * 100}%"></i></div>
    </div>`).join("");
  document.querySelectorAll(".hyp").forEach((el) => el.addEventListener("click", () => selectHyp(el.dataset.h)));
  if (hs.length) selectHyp(hs[0].id, false);
}

async function selectHyp(hid, scroll = true) {
  selectedHyp = hid;
  document.querySelectorAll(".hyp").forEach((el) => el.classList.toggle("sel", el.dataset.h === hid));
  const h = await api("/api/hypotheses/" + hid);
  $("#detailTitle").textContent = `HYPOTHESIS ${h.label} — WHY? (EVIDENCE TRAIL)`;
  $("#hypDetail").innerHTML = `
    <div class="claim" style="font-size:13px"><b>${esc(h.claim)}</b></div>
    <div class="kv"><h4>Supporting evidence (${h.evidence.length})</h4>
      ${h.evidence.map((e) => `<span class="evchip" data-ev="${e.id}" title="${esc(e.statement)}">${e.id} · ${esc(e.source)} · rel ${e.reliability}</span>`).join("") || '<span class="muted">none attached</span>'}</div>
    <div class="kv"><h4>Contradicting evidence (${h.counter_evidence.length})</h4>
      ${h.counter_evidence.map((e) => `<span class="evchip counter" data-ev="${e.id}" title="${esc(e.statement)}">${e.id}</span>`).join("") || '<span class="muted">none attached — absence of counter-evidence ≠ absence of search</span>'}</div>
    <div class="kv"><h4>Mechanism</h4><ul>${h.mechanism.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>
    <div class="kv"><h4>Assumptions</h4><ul>${h.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>
    <div class="kv"><h4>Falsifiers — what would prove this wrong</h4><ul>${h.falsifiers.map((f) => `<li>✕ ${esc(f)}</li>`).join("")}</ul></div>
    <div class="kv"><h4>Watchpoints</h4><ul>${h.watchpoints.map((w) => `<li><b>${esc(w.label)}</b> · ${esc(w.signal)} · ${esc(w.direction)}</li>`).join("")}</ul></div>`;
  bindEvidenceChips($("#hypDetail"));
  if (scroll) $("#hypDetail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function bindEvidenceChips(root) {
  root.querySelectorAll(".evchip[data-ev]").forEach((c) => c.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    const e = await api("/api/evidence/" + c.dataset.ev);
    openModal(`<h3>${e.id} — EVIDENCE RECORD</h3>` + [
      ["Statement", e.statement], ["Source", `${e.source} (${e.source_type})`],
      ["Classification", e.classification], ["Reliability", e.reliability],
      ["Independence", e.independence], ["Domain", e.domain],
      ["Observed at", e.observed_at], ["Ingested at", e.ingested_at],
      ["Content hash (chained)", e.content_hash], ["Chain sequence", "#" + e.chain_seq],
    ].map(([k, v]) => `<div class="evfield"><b>${k}</b>${esc(v)}</div>`).join("") +
    `<div class="evfield"><b>Note</b>“Source says X” ≠ “SYNTHESIS infers Y from X”. This record stores what the source said; inferences live in hypotheses.</div>`);
  }));
}

/* ---- action buttons ---- */
$("#btnAnalyze").addEventListener("click", () => { if (selectedEvent) { coneCache = null; renderCone(selectedEvent); } });
$("#btnChallenge").addEventListener("click", async () => {
  if (!selectedHyp) return;
  $("#advOut").innerHTML = `<span class="muted">Adversarial Agent attacking hypothesis…</span>`;
  const r = await api(`/api/hypotheses/${selectedHyp}/challenge`, { method: "POST" });
  $("#advOut").innerHTML =
    r.findings.map((f) => `<div class="finding ${f.severity}"><span class="ftype">${esc(f.type)} · ${esc(f.severity)}</span><div>${esc(f.note)}</div></div>`).join("") +
    `<div class="verdict ${r.adversarial_adjusted_confidence <= 0.45 ? "weak" : ""}">
      <b>${esc(r.verdict)}</b><br>stated confidence ${Math.round(r.stated_confidence * 100)}% →
      adversarial-adjusted <b>${Math.round(r.adversarial_adjusted_confidence * 100)}%</b></div>`;
});
$("#btnFalsify").addEventListener("click", async () => {
  if (!selectedHyp) return;
  const h = await api("/api/hypotheses/" + selectedHyp);
  openModal(`<h3>FALSIFICATION ENGINE — HYPOTHESIS ${h.label}</h3>
    <div class="evfield"><b>Hypothesis</b>${esc(h.claim)}</div>
    <div class="kv"><h4>Falsification conditions</h4><ul>${h.falsifiers.map((f) => `<li>✕ ${esc(f)}</li>`).join("")}</ul></div>
    <div class="kv"><h4>Watchpoints generated</h4><ul>${h.watchpoints.map((w, i) => `<li><b>WATCHPOINT ${i + 1}</b> — ${esc(w.label)} (${esc(w.signal)}, ${esc(w.direction)})</li>`).join("")}</ul></div>
    <div class="evfield"><b>Principle</b>If falsifying evidence arrives, confidence decreases automatically. Prediction is a testable process, not a narrative.</div>`);
});
$("#cfDuration").addEventListener("input", () => {
  const v = +$("#cfDuration").value;
  $("#cfDurationLabel").textContent = `${v} h (${(v / 24).toFixed(1)} d)`;
});
$("#btnBranch").addEventListener("click", async () => {
  if (!selectedEvent) return;
  const branch = await api("/api/counterfactual", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: selectedEvent, duration_hours: +$("#cfDuration").value, recovery: $("#cfRecovery").value }),
  });
  renderCone(selectedEvent, branch);
});
$("#btnBaseline").addEventListener("click", () => selectedEvent && renderCone(selectedEvent));

/* ---------------- contradictions ---------------- */
async function refreshContradictions() {
  const cs = await api("/api/contradictions");
  $("#contraList").innerHTML = cs.map((c) => `
    <div class="contra">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap">
        <span class="topic">${esc(c.id.toUpperCase().replace("CONFLICT_", "CONFLICT #"))} — ${esc(c.topic)}</span>
        <span class="status ${c.status}">${c.status.replace("_", " ")}</span>
      </div>
      <div class="claims">
        ${[["CLAIM A", c.claim_a], ["CLAIM B", c.claim_b]].map(([t, cl]) => `
          <div class="claimbox"><span class="ctag">${t}</span>
            <div><b>${esc(cl.claim)}</b></div>
            <div>source: ${esc(cl.source)} · reliability <span class="rel">${cl.reliability}</span></div>
            <div>ts: ${esc(cl.timestamp)}</div>
            <div>corroboration: ${esc(cl.corroboration)}</div>
          </div>`).join("")}
      </div>
      ${c.observation ? `<div class="obsnote">🛰 independent observation: ${esc(c.observation)}</div>` : ""}
      ${c.resolution_note ? `<div class="resnote">✓ ${esc(c.resolution_note)}</div>` : `<div class="resnote muted" style="color:var(--mut)">Awaiting evidence — original claims preserved either way.</div>`}
    </div>`).join("");
}

/* ---------------- outcome ledger ---------------- */
async function refreshLedger() {
  const [led, cal] = await Promise.all([api("/api/ledger"), api("/api/calibration")]);
  $("#openForecasts").innerHTML = led.open_forecasts.map((f) => {
    const ms = new Date(f.expires_at) - Date.now();
    const cd = ms > 0 ? (ms > 864e5 ? Math.round(ms / 864e5) + " d" : ms > 36e5 ? Math.round(ms / 36e5) + " h" : Math.max(0, Math.round(ms / 1e3)) + " s") : "closing…";
    return `<div class="fcast">
      <span class="fid">${f.id}</span> <span class="prob">p=${f.probability}</span> <span class="window">window ${f.forecast_window} · ${f.model_version}</span>
      <div>${esc(f.prediction)}</div>
      <div class="window">expected: ${f.expected_indicators.map(esc).join(" · ")}</div>
      <div class="countdown">⏱ resolves in ${cd}</div></div>`;
  }).join("") || '<span class="muted">none open</span>';
  const res = led.resolved_forecasts;
  if (res.length) {
    $("#resolvedForecasts").innerHTML = res.map((f) => `
      <div class="fcast ${f.status}">
        <span class="fid">${f.id}</span> <span class="vtag ${f.status}">${esc(f.outcome.verdict)}</span> <span class="prob">p was ${f.probability}</span>
        <div>${esc(f.prediction)}</div>
        <div class="window">observed: ${esc(f.outcome.observed)}</div>
        <div class="window">${esc(f.outcome.calibration_note)} · ${esc(f.outcome.observed_at)}</div>
      </div>`).join("");
  }
  $("#calSummary").textContent = `${cal.total_resolved} resolved · hit rate ${(cal.overall_hit_rate * 100).toFixed(1)}% · mean Brier ${cal.mean_brier}`;
  drawCalibration(cal);
  $("#sectorStats").innerHTML =
    cal.sector_stats.map((s) => `<span class="sector">${esc(s.sector)} <b>${(s.hit_rate * 100).toFixed(0)}%</b>/${s.n} · B ${s.mean_brier}</span>`).join("") +
    `<div class="muted" style="margin-top:6px;font-size:11.5px">${esc(cal.note)}</div>`;
}

function drawCalibration(cal) {
  const cv = $("#calChart"), ctx = cv.getContext("2d"), w = cv.width, h = cv.height, pad = 34;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#1c2a47"; ctx.strokeRect(pad, 10, w - pad - 10, h - pad - 10);
  // perfect-calibration diagonal
  ctx.strokeStyle = "#334155"; ctx.setLineDash([4, 4]); ctx.beginPath();
  ctx.moveTo(pad, h - pad); ctx.lineTo(w - 10, 10); ctx.stroke(); ctx.setLineDash([]);
  const X = (p) => pad + p * (w - pad - 10), Y = (p) => h - pad - p * (h - pad - 20);
  ctx.fillStyle = "#7d8db0"; ctx.font = "10px monospace";
  ctx.fillText("predicted →", w / 2 - 20, h - 8); ctx.save(); ctx.translate(10, h / 2 + 24); ctx.rotate(-Math.PI / 2); ctx.fillText("observed →", 0, 0); ctx.restore();
  for (const b of cal.reliability_buckets) {
    ctx.beginPath(); ctx.arc(X(b.predicted), Y(b.observed), 4 + Math.sqrt(b.n), 0, 7);
    ctx.fillStyle = "#39d0d866"; ctx.fill(); ctx.strokeStyle = "#39d0d8"; ctx.stroke();
    ctx.fillStyle = "#d7e2f4"; ctx.fillText(b.range + " (n=" + b.n + ")", X(b.predicted) + 10, Y(b.observed) - 6);
  }
}

/* ---------------- agents ---------------- */
async function refreshAgents() {
  const ags = await api("/api/agents");
  $("#agentList").innerHTML = ags.map((a) => `
    <div class="agent"><span class="sandbadge">SANDBOXED</span>
      <h3>${esc(a.name)}</h3><div class="scope">${esc(a.scope)}</div>
      <div class="task">▸ ${esc(a.current_task)}</div>
      <div class="perm">read: ${esc(a.permissions.read)} · write: ${esc(a.permissions.write)}<br>cannot: ${a.permissions.cannot.map(esc).join(", ")}</div>
    </div>`).join("");
}

/* ---------------- modal ---------------- */
function openModal(html) { $("#modalBody").innerHTML = html; $("#modal").classList.remove("hidden"); }
$("#modalClose").addEventListener("click", () => $("#modal").classList.add("hidden"));
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });

/* ---------------- PWA install ---------------- */
let deferredPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; $("#installBtn").classList.remove("hidden"); });
$("#installBtn").addEventListener("click", async () => { if (deferredPrompt) { deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt = null; $("#installBtn").classList.add("hidden"); } });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

/* ---------------- boot ---------------- */
async function boot() {
  await refreshState();
  await refreshEvents();
  await refreshFeed();
  loadGeo();
  setInterval(refreshState, 5000);
  setInterval(refreshFeed, 5000);
  setInterval(() => { if ($("#tab-ledger").classList.contains("active")) refreshLedger(); }, 5000);
  setInterval(() => { if ($("#tab-contra").classList.contains("active")) refreshContradictions(); }, 8000);
}
boot();
