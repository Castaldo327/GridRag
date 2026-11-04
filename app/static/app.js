const state = { apiKey: "", keyMessage: "", meta: null, result: null, running: false, error: "", progress: {}, runs: new Map(),
  evaluation: { running: false, active: null, stage: null, results: new Map(), summary: null, error: "" } };
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const md = (value) => esc(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
const number = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const seconds = value => value == null ? "—" : `${Number(value).toFixed(2)} s`;
const modelReady = () => Boolean(state.apiKey || state.meta?.model_ready);
const requestHeaders = () => ({ "Content-Type": "application/json", "Accept": "application/x-ndjson",
  ...(state.apiKey ? { "Authorization": `Bearer ${state.apiKey}` } : {}) });
const preset = () => state.meta.presets.find(p => p.question === $("#question").value.trim());

function render() {
  $("#main").innerHTML = `
    <section class="api-access panel" aria-labelledby="api-key-heading">
      <div class="api-access-intro"><span class="eyebrow">TRY IT YOURSELF</span><h2 id="api-key-heading">Bring your own OpenAI key.</h2>
        <p>Your key stays in this tab’s memory and is sent securely to this app’s server to call OpenAI. It is never saved. API usage is billed to your OpenAI account.</p>
        <small>Models: ${esc(state.meta.models?.decisions || "configured decision model")} · ${esc(state.meta.models?.answer || "configured answer model")} · Requires Decisions and Responses API access.</small></div>
      <form id="api-key-form" class="api-key-form" autocomplete="off">
        <label for="api-key">OpenAI API key</label><div class="api-key-controls"><input id="api-key" type="password" name="visitor-api-key" maxlength="503" placeholder="sk-…" autocomplete="off" spellcheck="false" autocapitalize="none" aria-describedby="api-key-status"><button id="save-key" type="submit">Use key</button><button id="clear-key" type="button" hidden>Remove</button></div>
        <span id="api-key-status" role="status"></span>
        <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">Get an API key ↗</a>
      </form>
    </section>
    <div id="ask-view">
    <section class="hero panel">
      <span class="eyebrow">ENERGY INTELLIGENCE · SYNTHETIC DATA</span>
      <h1>A clearer view of the grid.</h1>
      <p>Explore demand, generation, prices, and projects. Ask in plain language and get an answer you can trace back to the data.</p>
      <div class="market-strip" aria-label="Available energy markets">${state.meta.isos.map(iso => `<span>${esc(iso)}</span>`).join("")}<small>${state.meta.catalog_tables} tables · ${state.meta.isos.length} markets</small></div>
      <aside class="data-window" id="data-window" aria-label="Synthetic data coverage">
        <strong>Data ends October 21, 2026 · This is a fixed snapshot, not live data.</strong>
        <span>Start with a region, a measure, and a date in the ranges below. Use specific dates rather than “today.”</span>
      </aside>
      <form id="ask-form" class="ask-form">
        <label class="sr-only" for="question">Your question</label>
        <textarea id="question" aria-describedby="data-window" rows="3" maxlength="${state.meta.max_question_chars}" required placeholder="Try: What was ERCOT’s peak demand on October 19, 2026?"></textarea>
        <button id="ask-button" type="submit">Ask the grid →</button>
      </form>
      <p class="preset-hint">A place to start. Choose a question, then make it yours.</p>
      <div class="examples" aria-label="Preset questions">${state.meta.presets.map((p, i) => `
        <button type="button" data-preset="${i}" title="${esc(p.question)}" aria-label="${esc(p.label)}: ${esc(p.question)}"><b>${esc(p.label)}</b><span>${esc(p.concept)}</span></button>`).join("")}</div>
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
      <p class="coverage">${state.meta.catalog_tables} catalog tables · ${state.meta.isos.length} ISOs · Synthetic demonstration data · Questions use the configured model API.</p>

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
    </section></div>
    <section id="evaluation-view" class="panel evaluation-page" hidden>
      <div class="evaluation-intro"><div><span class="eyebrow">FULL SUITE</span><h1>Evaluation</h1>
        <p>Run all ${state.meta.evaluation_cases?.length || 0} shared questions, including answer, clarification, and decline cases. Each case checks its state, routing, SQL, numeric evidence, and final answer where applicable.</p></div>
        <div class="evaluation-action"><button id="evaluation-run" type="button">Run all evaluations →</button>
          <small>Runs each case with your active API key. API usage may incur charges.</small></div></div>
      <div id="evaluation-summary" class="evaluation-summary" role="status"></div>
      <div id="evaluation-cases" class="evaluation-cases"></div>
      <p class="footnote">A pass confirms these checks. Inspect the SQL and answer before treating a response as correct.</p>
    </section>`;
  $("#api-key-form").onsubmit = event => {
    event.preventDefault();
    if (state.running || state.evaluation.running) return;
    const key = $("#api-key").value.trim();
    if (!/^sk-[A-Za-z0-9_-]{10,500}$/.test(key)) {
      state.keyMessage = "Enter a valid OpenAI API key beginning with sk-.";
      paintKey(); return;
    }
    state.apiKey = key; state.keyMessage = ""; $("#api-key").value = "";
    paint(); paintEvaluation();
  };
  $("#clear-key").onclick = () => {
    if (state.running || state.evaluation.running) return;
    state.apiKey = ""; state.keyMessage = ""; $("#api-key").value = "";
    paint(); paintEvaluation();
  };
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
  $("#evaluation-run").onclick = runEvaluation;
  window.onhashchange = showView;
  showView();
  paintPresets(); paint();
  paintEvaluation();
}

function showView() {
  const view = location.hash === "#evaluation" ? "evaluation" : "ask";
  $("#ask-view").hidden = view !== "ask";
  $("#evaluation-view").hidden = view !== "evaluation";
  $("#view-title").textContent = view === "ask" ? "Ask the grid" : "Evaluation";
  document.title = `${view === "ask" ? "Ask the grid" : "Evaluation"} · Energy workspace`;
  document.querySelectorAll("[data-view-link]").forEach(link => {
    const selected = link.dataset.viewLink === view;
    link.classList.toggle("selected", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
}

function paintPresets() {
  const p = preset();
  document.querySelectorAll("[data-preset]").forEach(button => {
    button.setAttribute("aria-pressed", String(state.meta.presets[Number(button.dataset.preset)] === p));
  });
}

function paintKey() {
  const busy = state.running || state.evaluation.running;
  $("#api-key").disabled = busy;
  $("#save-key").disabled = busy;
  $("#save-key").textContent = state.apiKey ? "Replace key" : "Use key";
  $("#clear-key").hidden = !state.apiKey;
  $("#clear-key").disabled = busy;
  $("#api-key").placeholder = state.apiKey ? "Key added for this tab" : "sk-…";
  $("#api-key-status").textContent = state.keyMessage || (state.apiKey ? "Key added for this tab. Reloading or closing this tab removes it." : state.meta.model_ready ? "Using the local server’s configured key. You can use your own instead." : "Add your key above to ask a question or run evaluations.");
  $("#api-key-status").classList.toggle("error", Boolean(state.keyMessage));
}

function paint() {
  paintKey();
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
    '<div class="empty"><span class="empty-symbol" aria-hidden="true">✧</span><strong>Your next insight starts here.</strong><span>Choose a question or write your own. Your answer and supporting evidence will appear here.</span></div>';
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
  $("#ask-button").disabled = state.running || state.evaluation.running || !modelReady();
  $("#ask-button").textContent = state.running ? "Running…" : "Ask the grid →";
  $("#question").disabled = state.running || state.evaluation.running;
  document.querySelectorAll("[data-preset], [data-question]").forEach(b => { b.disabled = state.running || state.evaluation.running; });
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question || state.running || state.evaluation.running || !modelReady()) return;
  const p = preset();
  state.running = true; state.result = null; state.error = ""; state.progress = {}; paint(); paintEvaluation();
  try {
    const response = await fetch("/api/ask", {
      method: "POST", headers: requestHeaders(), body: JSON.stringify({ question }),
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
  } finally { state.running = false; paint(); paintEvaluation(); }
}

function paintEvaluation() {
  const e = state.evaluation, cases = state.meta.evaluation_cases || [];
  const completed = e.results.size;
  const passed = [...e.results.values()].filter(item => item.assessment?.passed).length;
  const stageNames = { gate: "Checking request", route: "Selecting schema", sql: "Running SQL", answer: "Answering" };
  $("#evaluation-run").disabled = e.running || state.running || !modelReady() || !cases.length;
  $("#evaluation-run").textContent = e.running ? "Evaluation running…" : `Run all ${cases.length} evaluations →`;
  $("#evaluation-summary").innerHTML = e.error ? `<span class="error">${esc(e.error)}</span>` :
    e.summary ? `<strong>${e.summary.passed} of ${e.summary.total} passed</strong><span>${seconds(e.summary.seconds)} total · Estimated $${Number(e.summary.cost_usd).toFixed(5)} model cost</span>` :
    e.running ? `<strong>${completed} of ${cases.length} complete</strong><span>${passed} passed · ${e.active ? `Running ${esc(e.active)}${e.stage ? ` · ${esc(stageNames[e.stage] || e.stage)}` : ""}` : "Starting…"}</span>` :
    `<strong>${cases.length} cases ready</strong><span>Press Run all evaluations to start the live suite.</span>`;
  if (!cases.length) {
    $("#evaluation-cases").innerHTML = '<p class="error">Evaluation cases are unavailable. Restart the local app and reload this page.</p>';
    return;
  }
  const expanded = new Set([...document.querySelectorAll(".evaluation-result[open]")].map(node => node.dataset.caseId));
  $("#evaluation-cases").innerHTML = cases.map((c, i) => {
    const entry = e.results.get(c.id), assessment = entry?.assessment, result = assessment?.result;
    const status = assessment ? assessment.passed ? "Passed" : "Needs review" : entry?.error ? "Error" :
      e.active === c.id ? "Running" : "Ready";
    const statusClass = assessment ? assessment.passed ? "good" : "warn" : entry?.error ? "warn" :
      e.active === c.id ? "active" : "";
    const expected = c.expected == null ? esc(c.expected_state) : `${esc(c.expected_state)} · ${number(c.expected)} ${esc(c.unit)}`;
    const checks = assessment?.checks.map(check => `<li class="${check.passed ? "good" : "warn"}">
      <b>${check.passed ? "✓" : "!"} ${esc(check.name)}</b><span>${esc(check.detail)}</span></li>`).join("") || "";
    const calls = result?.tool_calls || [];
    return `<article class="evaluation-case ${statusClass}">
      <div class="evaluation-case-head"><span class="case-index">${String(i + 1).padStart(2, "0")}</span>
        <div><strong>${esc(c.label)}</strong><p>${esc(c.question)}</p><small>Expected: ${expected}</small>
          ${c.verification ? `<p class="evaluation-verification"><b>Warehouse verification:</b> ${esc(c.verification)}</p>` : ""}</div>
        <span class="badge ${statusClass}">${status}</span></div>
      ${entry?.error ? `<p class="error">${esc(entry.error)}</p>` : ""}
      ${assessment ? `<details class="evaluation-result" data-case-id="${esc(c.id)}" ${expanded.has(c.id) ? "open" : ""}>
        <summary>Inspect checks, answer, and SQL · ${seconds(result.timings?.total)} · $${Number(result.usage?.cost_usd || 0).toFixed(5)}</summary>
        <ul class="evaluation-checks">${checks}</ul><div class="evaluation-answer"><b>Answer</b><p>${md(result.answer || "")}</p></div>
        ${calls.map((call, j) => `<details class="evidence-item"><summary>Query ${j + 1} · ${call.error ? "error" : `${call.rows} rows`}</summary>
          <pre>${esc(call.query)}</pre>${call.csv ? `<pre>${esc(call.csv)}</pre>` : ""}${call.error ? `<p class="error">${esc(call.error)}</p>` : ""}</details>`).join("")}</details>` : ""}
    </article>`;
  }).join("");
}

async function runEvaluation() {
  const e = state.evaluation, cases = state.meta.evaluation_cases || [];
  if (e.running || state.running || !modelReady() || !cases.length) return;
  e.running = true; e.active = null; e.stage = null; e.results.clear(); e.summary = null; e.error = "";
  paintEvaluation(); paint();
  const started = performance.now();
  let passed = 0, cost = 0;
  try {
    // One bounded request per case keeps the full suite within hosting time limits.
    for (const c of cases) {
      const response = await fetch("/api/evaluate-case", {
        method: "POST", headers: requestHeaders(), body: JSON.stringify({ id: c.id }),
      });
      if (!response.ok) throw new Error((await response.json()).error || `HTTP ${response.status}`);
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "", summary = null;
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
            if (event.type === "case_start") { e.active = event.id; e.stage = null; }
            if (event.type === "case_progress") e.stage = event.stage;
            if (event.type === "case_done") { e.results.set(event.assessment.id, event); e.active = null; e.stage = null; }
            if (event.type === "case_error") { e.results.set(event.id, event); e.active = null; e.stage = null; }
            if (event.type === "done") summary = event.summary;
            paintEvaluation();
          }
          if (done || summary) break;
        }
        if (!summary) throw new Error("The evaluation connection ended early. Completed cases remain below; retry to run the full suite.");
        passed += summary.passed; cost += summary.cost_usd;
      } finally { await reader.cancel(); }
    }
    e.summary = { passed, total: cases.length, cost_usd: cost, seconds: (performance.now() - started) / 1000 };
  } catch (error) {
    e.error = error.message || "Could not run the evaluation. Please retry.";
  } finally {
    e.running = false; e.active = null; e.stage = null; paintEvaluation(); paint();
  }
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
