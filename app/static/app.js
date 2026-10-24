const state = { meta: null, result: null, running: false, error: "", progress: {}, runs: new Map() };
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const md = (value) => esc(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
const number = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const seconds = value => value == null ? "—" : `${Number(value).toFixed(2)} s`;
const preset = () => state.meta.presets.find(p => p.question === $("#question").value.trim());

function render() {
  $("#main").innerHTML = `
    <section class="hero panel">
      <span class="eyebrow">SYNTHETIC DATA</span>
      <h1>Ask the grid.</h1>
      <p>Explore demand, generation, prices, and projects. Follow a question from schema selection to SQL and an answer backed by data.</p>
      <aside class="data-window" id="data-window" aria-label="Synthetic data coverage">
        <strong>Data ends October 21, 2026 · This is a fixed snapshot, not live data.</strong>
        <span>Start with a region, a measure, and a date in the ranges below. Use specific dates rather than “today.”</span>
      </aside>
      <details class="question-guide">
        <summary>What can I ask?</summary>
        <div class="guide-grid">
          <div><strong>Demand &amp; generation by fuel</strong><p>Hourly peaks, averages, totals and fuel shares, including solar and wind.</p><small>All 7 regions · Jan 1, 2025–Oct 21, 2026</small></div>
          <div><strong>Five-minute demand &amp; generation</strong><p>Look at a specific time or compare changes within a day.</p><small>CAISO and ERCOT only · Oct 15–21, 2026</small></div>
          <div><strong>Prices, forecasts &amp; operations</strong><p>Bus/hub prices, load forecasts, battery dispatch, outages, curtailment and ancillary prices. Forecasts are for demand, not solar generation.</p><small>All 7 regions · Oct 15–21, 2026</small></div>
          <div><strong>Proposed projects</strong><p>Count queued projects or compare proposed capacity by region, fuel and project status.</p><small>All 7 regions · Snapshot as of Oct 21, 2026</small></div>
        </div>
        <p class="guide-regions"><strong>Region names:</strong> ${state.meta.isos.map(esc).join(" · ")}. CAISO is California; ERCOT is Texas. Dates use each region’s local time unless you ask for UTC.</p>
        <button class="guide-example" type="button" data-question="What was CAISO's highest hourly solar generation in MW on October 19, 2026?">Try: CAISO’s highest hourly solar generation on October 19, 2026 →</button>
      </details>
      <p class="preset-hint">Choose a question to edit, then select <strong>Ask the grid</strong>.</p>
      <div class="examples" aria-label="Preset questions">${state.meta.presets.map((p, i) => `
        <button type="button" data-preset="${i}"><b>${esc(p.label)}</b><span>${esc(p.question)}</span></button>`).join("")}</div>
      <form id="ask-form" class="ask-form">
        <label class="sr-only" for="question">Your question</label>
        <textarea id="question" aria-describedby="data-window" rows="3" maxlength="${state.meta.max_question_chars}" required placeholder="Try: What was ERCOT’s peak demand on October 19, 2026?"></textarea>
        <button id="ask-button" type="submit">Ask the grid →</button>
      </form>
      <p class="coverage">${state.meta.catalog_tables} catalog tables · ${state.meta.isos.length} ISOs · Synthetic demonstration data · Questions use the configured model API.</p>
      ${state.meta.model_ready ? "" : '<p class="error">Model not configured. Add OPENAI_API_KEY to .env to ask questions. Reference values are available below.</p>'}
    </section>
    <div class="workspace">
      <section class="panel flow-panel">
        <div class="panel-head"><div><span class="eyebrow">QUESTION → EVIDENCE</span><h2>The path to an answer</h2></div><span class="live" id="live-status" role="status"></span></div>
        <div id="flow" class="flow"></div>
      </section>
      <section class="panel answer-panel">
        <div class="panel-head"><div><span class="eyebrow">RESULT</span><h2>Answer</h2></div><span id="answer-state"></span></div>
        <div id="answer" class="answer" aria-live="polite"></div>
      </section>
    </div>
    <section class="panel details-panel" id="details-panel" hidden>
      <div class="panel-head"><div><span class="eyebrow">EVIDENCE</span><h2>Inspect the SQL</h2></div></div>
      <div id="details"></div>
    </section>
    <section class="panel metrics-panel" id="metrics-panel" hidden>
      <div class="panel-head"><div><span class="eyebrow">MEASURED RUN</span><h2>Time and model use</h2></div></div>
      <div id="metrics"></div>
    </section>`;
  $("#ask-form").onsubmit = e => { e.preventDefault(); ask(); };
  $("#question").oninput = () => { state.result = null; state.error = ""; state.progress = {}; paintPresets(); paint(); };
  document.querySelectorAll("[data-preset]").forEach(button => {
    button.onclick = () => {
      const p = state.meta.presets[Number(button.dataset.preset)];
      $("#question").value = p.question;
      state.result = state.runs.get(p.id) || null;
      state.error = ""; state.progress = {};
      paintPresets(); paint();
    };
  });
  document.querySelectorAll("[data-question]").forEach(button => {
    button.onclick = () => {
      $("#question").value = button.dataset.question;
      $("#question").dispatchEvent(new Event("input"));
      $("#question").focus();
    };
  });
  $("#question").value = new URLSearchParams(location.search).get("q") || state.meta.presets[0].question;
  paintPresets(); paint();
}

function paintPresets() {
  const p = preset();
  document.querySelectorAll("[data-preset]").forEach(button => {
    button.setAttribute("aria-pressed", String(state.meta.presets[Number(button.dataset.preset)] === p));
  });
}

function paint() {
  const r = state.result, route = r?.route || state.progress.route, gate = r?.gate || state.progress.gate;
  const calls = r?.tool_calls || state.progress.tool_calls || [];
  const active = state.running ? state.progress.stage : null;
  const stageNames = {gate: "Checking request", route: "Selecting schema", sql: "Working with SQL", answer: "Interpreting results"};
  const total = state.meta.catalog_tables, selected = route?.tables || [];
  $("#live-status").textContent = state.running ? stageNames[active] || "Starting…" : r ? "Finished" : "Ready";
  $("#live-status").className = `live ${state.running ? "running" : ""}`;
  const steps = [
    ["Request gate", gate ? gate.reason : "Check relevance and instruction safety.", Boolean(gate)],
    ["Select schema", route ? `${selected.length} of ${total} tables selected. Full columns and referenced tables retained.` :
      "Select relevant tables from the documented catalog.", Boolean(route)],
    ["Query the warehouse", calls.length ? `${calls.length} queries · ${calls.filter(c => !c.error).length} successful` :
      r ? "No queries executed." : "Generate read-only SQL; repair errors if needed.", calls.length > 0],
    ["Answer from results", r ? r.state.replaceAll("_", " ") : "Use query evidence to answer the question.", r?.state === "answered"],
  ];
  $("#flow").innerHTML = steps.map(([title, description, done], i) => {
    const isActive = active === ["gate", "route", "sql", "answer"][i];
    return `
    <div class="flow-step ${isActive ? "active" : done ? "complete" : ""}" ${isActive ? 'aria-current="step"' : ""}><span class="step-number">${isActive ? '<span class="stage-spinner" aria-hidden="true"></span>' : done ? "✓" : `0${i + 1}`}</span>
      <div><strong>${title}</strong>${isActive ? '<span class="active-label">Active</span>' : ""}<p>${esc(description)}</p>
      ${i === 1 && route ? `<div class="schema-meter" role="img" aria-label="${selected.length} of ${total} catalog tables selected">
        <span style="width:${100 * selected.length / total}%"></span></div>
        <details class="schema-list"><summary>Selected tables${route.fallback ? " · includes uncertain matches" : ""}</summary>
          ${selected.map(t => `<code>${esc(t)}${route.columns?.[t] ? ` · ${esc(route.columns[t].join(", "))}` : ""}</code>`).join("") || "None"}</details>` : ""}</div></div>`;
  }).join("");
  $("#answer-state").innerHTML = r ? `<span class="badge ${r.state === "answered" ? "good" : "warn"}">${esc(r.state.replaceAll("_", " "))}</span>` : "";
  $("#answer").innerHTML = state.error ? `<p class="error">${esc(state.error)}</p>` : r ?
    `<div class="answer-text">${md(r.answer)}</div>` : state.running && state.progress.answer_text ?
    `<div class="answer-text">${md(state.progress.answer_text)}</div>` : state.running ?
    `<div class="loading"><i></i>${esc(stageNames[active] || "Starting the pipeline")}…</div><p class="footnote">The highlighted stage follows backend progress. SQL and evidence appear as they return.</p>` :
    '<p class="empty">Choose a preset or write a question, then ask the grid.</p>';
  $("#details-panel").hidden = !calls.length;
  $("#details").innerHTML = calls.map((call, i) => `<details class="evidence-item" ${i === calls.length - 1 ? "open" : ""}>
    <summary>Query ${i + 1} · ${call.error ? "error" : `${call.rows} result rows`}</summary>
    <pre>${esc(call.query)}</pre>${call.csv ? `<div class="evidence-output"><b>Returned data</b><pre>${esc(call.csv)}</pre></div>` : ""}
    ${call.truncated ? `<p>${esc(call.truncated)}</p>` : ""}
    ${call.error ? `<p class="error">${esc(call.error)}</p>` : ""}</details>`).join("");
  $("#metrics-panel").hidden = !r;
  if (r) $("#metrics").innerHTML = `<div class="metric-grid">
    <div title="From request processing start to the first streamed answer text"><small>First answer token</small><strong>${seconds(r.timings.first_token)}</strong></div>
    <div><small>Model calls</small><strong>${r.usage.calls}</strong></div>
    <div><small>Estimated token cost</small><strong>$${r.usage.cost_usd.toFixed(5)}</strong></div>
    <div><small>SQL queries</small><strong>${calls.length}</strong></div></div>
    <div class="stage-metrics"><span>Total completion <b>${seconds(r.timings.total)}</b></span>${["gate", "route", "sql"].map(s => `<span>${{gate:"Gate", route:"Routing", sql:"SQL + answer"}[s]} <b>${seconds(r.timings[s])}</b></span>`).join("")}
    <span>Tokens <b>${number(r.usage.input_tokens)} in / ${number(r.usage.output_tokens)} out</b></span></div>
    <details class="evidence-item"><summary>Latency breakdown</summary>
      <div class="stage-metrics">${(r.usage.per_call || []).map((call, i) => `<span>Call ${i + 1} · ${esc({gate: "Gate", route: "Routing", sql: "SQL / answer model"}[call.stage] || call.stage)} <b>${seconds(call.seconds)}</b></span>`).join("")}
      ${calls.map((call, i) => call.execution_seconds == null ? "" : `<span>Database query ${i + 1} <b>${seconds(call.execution_seconds)}</b></span>`).join("")}</div>
      <p class="footnote">Model times include network waits and SDK retries. Database times include SQL checks and result formatting.</p>
    </details>`;
  $("#ask-button").disabled = state.running || !state.meta.model_ready;
  $("#ask-button").textContent = state.running ? "Running…" : "Ask the grid →";
  $("#question").disabled = state.running;
  document.querySelectorAll("[data-preset], [data-question]").forEach(b => { b.disabled = state.running; });
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question || state.running) return;
  const p = preset();
  state.running = true; state.result = null; state.error = ""; state.progress = {}; paint();
  try {
    const response = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/x-ndjson" }, body: JSON.stringify({ question }),
    });
    if (!response.ok) throw new Error((await response.json()).error || `HTTP ${response.status}`);
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "error") throw new Error(event.error);
          if (event.type === "progress") {
            if (event.answer_delta !== undefined) {
              state.progress.answer_text = (state.progress.answer_text || "") + event.answer_delta;
              $("#answer").innerHTML = `<div class="answer-text">${md(state.progress.answer_text)}</div>`;
            } else {
              Object.assign(state.progress, event);
              paint();
            }
          }
          if (event.type === "done") {
            state.result = event.result;
            if (p) state.runs.set(p.id, event.result);
          }
        }
        if (done || state.result) break;
      }
      if (!state.result) throw new Error("The connection ended before the answer arrived. Please retry.");
    } finally { await reader.cancel(); }

  } catch (error) {
    state.error = error.message || "Could not reach the server. Please retry.";
  } finally { state.running = false; paint(); }
}

async function boot() {
  try {
    const response = await fetch("/api/meta");
    const meta = await response.json();
    if (!response.ok) throw new Error(meta.error || `HTTP ${response.status}`);
    state.meta = meta; render();
  } catch (error) {
    $("#main").innerHTML = `<section class="panel boot-error"><h1>Could not load the warehouse</h1>
      <p>${esc(error.message)}</p><button id="retry" type="button">Retry</button></section>`;
    $("#retry").onclick = boot;
  }
}
boot();
