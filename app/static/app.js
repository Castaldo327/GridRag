const state = { demoIndex: 0, demoStep: 0, scoreScope: "all", benchmark: null, apiKey: "", keyMessage: "", meta: null, result: null, running: false, error: "", progress: {}, runs: new Map(),
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
    <div id="demo-view"></div>
    <section class="api-access panel" aria-labelledby="api-key-heading">
      <div class="api-access-intro"><span class="eyebrow">TRY IT YOURSELF</span><h2 id="api-key-heading">Bring your own OpenAI key.</h2>
        <p>Your key is held in this tab’s memory and sent to the app’s backend to call OpenAI. The app does not save it. Reload or remove it to clear it. API usage is billed to your OpenAI account.</p>
        <small id="model-access-note">Models: ${esc(state.meta.models?.decisions || "configured decision model")} · ${esc(state.meta.models?.answer || "configured answer model")} · Requires Decisions and Responses API access.</small></div>
      <form id="api-key-form" class="api-key-form" autocomplete="off">
        <label for="api-key">OpenAI API key</label><div class="api-key-controls"><input id="api-key" type="password" name="visitor-api-key" maxlength="503" placeholder="sk-…" autocomplete="off" spellcheck="false" autocapitalize="none" aria-describedby="api-key-status"><button id="save-key" type="submit">Use key</button><button id="clear-key" type="button" hidden>Remove</button></div>
        <span id="api-key-status" role="status"></span>
        <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">Get an API key ↗</a>
      </form>
    </section>
    <div id="ask-view">
    <section class="hero panel">
      <span class="eyebrow">ENERGY INTELLIGENCE · SYNTHETIC DATA</span>
      <h1>Your question. Real SQL.</h1>
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
      <details class="question-guide" open>
        <summary>What’s in the warehouse?</summary>
        <div class="guide-grid">
          <div><strong>Demand &amp; generation by fuel</strong><p>Hourly peaks, averages, totals and fuel shares, including solar and wind.</p><small>All 7 regions · Jan 1, 2025–Oct 21, 2026</small></div>
          <div><strong>Five-minute demand &amp; generation</strong><p>Look at a specific time or compare changes within a day.</p><small>CAISO and ERCOT only · Oct 15–21, 2026</small></div>
          <div><strong>Prices, forecasts &amp; operations</strong><p>Bus/hub prices, load forecasts, battery dispatch, outages, curtailment and ancillary prices. Forecasts are for demand, not solar generation.</p><small>All 7 regions · Oct 15–21, 2026</small></div>
          <div><strong>Proposed projects</strong><p>Count queued projects or compare proposed capacity by region, fuel and project status.</p><small>All 7 regions · Snapshot as of Oct 21, 2026</small></div>
        </div>
        <p class="guide-regions"><strong>Region names:</strong> ${state.meta.isos.map(esc).join(" · ")}. CAISO is California; ERCOT is Texas. Dates use each region’s local time unless you ask for UTC.</p>
        <button class="guide-example" type="button" data-question="What was CAISO's highest hourly solar generation in MW on October 19, 2026?">Try: CAISO’s highest hourly solar generation on October 19, 2026 →</button>
      </details>
      <details class="question-guide"><summary>Browse the table definitions</summary><label class="catalog-search-label" for="catalog-search">Find a table, region, or measure</label><input id="catalog-search" type="search" placeholder="Try: ERCOT, storage, forecast"><div id="catalog-list"></div></details>
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
    <section id="evaluation-view" hidden>
      <div class="hero panel"><span class="eyebrow">MEASURE THE TRADEOFFS</span><h1>Does better context<br>make a better answer?</h1><p>The routed schema approach versus embedded schema retrieval in Qdrant. Same questions, same SQL model, same database. Compare accuracy, response time, and estimated model cost.</p></div>
      <div id="benchmark-results" class="panel benchmark-panel"></div>
      <details class="panel methodology"><summary>How the comparison works</summary><div class="guide-grid">
        <div><strong>Routed schema</strong><p>A decision model scores tables, expands their references, then scores columns. The SQL model receives the resulting compact schema.</p></div>
        <div><strong>Embedded schema</strong><p>BGE-small embeds each documented table. Qdrant retrieves the top 4 or 6 tables, adds their references, and supplies every column to the same SQL model.</p></div>
        <div><strong>Accuracy</strong><p>Numeric questions must produce the correct final scalar SQL result. Behavior cases must decline or request clarification without executing SQL. Independent reference queries never reach the model.</p></div>
        <div><strong>Fairness and limits</strong><p>Fixed settings, shuffled method order, repeated trials, and failures included. This small synthetic benchmark does not establish production accuracy. Token costs exclude embedding compute and hosting.</p></div>
      </div></details>
      <details class="panel live-checks"><summary>Run the routed pipeline checks with your own key</summary>
        <p class="footnote">These checks exercise the live playground. The comparison above is a separately recorded benchmark; rerunning these checks does not rerun Qdrant.</p>
        <div class="evaluation-action"><button id="evaluation-run" type="button">Run checks →</button><small><a href="#playground">Add your key in the playground</a> first. This makes paid API calls.</small></div>
        <div id="evaluation-summary" class="evaluation-summary" role="status"></div><div id="evaluation-cases" class="evaluation-cases"></div>
      </details>
    </section>`;
  $(".skip-link").onclick = event => { event.preventDefault(); $("#main").focus(); $("#main").scrollIntoView({block: "start"}); };
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
  paintDemo(); paintBenchmark(); paintCatalog();
  $("#catalog-search").oninput = paintCatalog;
  showView();
  paintPresets(); paint();
  paintEvaluation();
}

function showView() {
  const requested = location.hash.slice(1);
  const view = ["playground", "evaluation"].includes(requested) ? requested : requested === "ask" ? "playground" : "demo";
  $("#demo-view").hidden = view !== "demo";
  $("#ask-view").hidden = view !== "playground";
  $(".api-access").hidden = view !== "playground";
  $("#evaluation-view").hidden = view !== "evaluation";
  const title = {demo: "Demo", playground: "Playground", evaluation: "Evaluation"}[view];
  $("#view-title").textContent = title;
  document.title = `${title} · GridRag`;
  document.querySelectorAll("[data-view-link]").forEach(link => {
    const selected = link.dataset.viewLink === view;
    link.classList.toggle("selected", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
}

function paintCatalog() {
  const query = ($("#catalog-search").value || "").toLowerCase();
  const tables = (state.meta.catalog || []).filter(t => t.ddl.toLowerCase().includes(query));
  $("#catalog-list").innerHTML = `<p class="footnote">${tables.length} table definitions · Read-only synthetic warehouse hosted by the app</p>` + tables.map(t => `<details class="evidence-item"><summary>${esc(t.name)}</summary><pre>${esc(t.ddl)}</pre></details>`).join("");
}

function paintDemo() {
  const demos = state.meta.demos || [], d = demos[state.demoIndex];
  if (!d) return;
  const explanations = {
    peak: ["Start with a region, a measure, and a date.", "Hourly demand lives in the balance table. The ISO dimension identifies ERCOT.", "Filter the region and local date, then take the highest hourly demand.", "The result is a measurement from this fictional dataset, with its SQL available for inspection."],
    storage: ["Ask for energy, not just a power reading.", "Five-minute battery dispatch records charge and discharge separately.", "Sum gross discharge power and divide by 12 to convert five-minute MW readings into MWh.", "Keeping units and interval duration in the query makes the answer auditable."],
    forecast: ["Specify both delivery time and what was known at the time.", "The forecast table includes publication time, unlike a simple demand estimate.", "Keep eligible publication times, then choose the latest forecast vintage.", "This avoids using a forecast that was published after the requested cutoff."]
  };
  const titles = ["Ask a precise question", "Find the relevant schema", "Calculate with SQL", "Inspect the evidence"];
  const detail = [
    `<blockquote>${esc(d.question)}</blockquote>`,
    `<div class="demo-tables">${d.tables.map(t => `<code>${esc(t)}</code>`).join("")}</div><p class="footnote">Join dimensions are included where needed. Explore all 65 tables in the playground.</p>`,
    `<pre>${esc(d.sql)}</pre>`,
    `<div class="demo-answer"><strong>${number(d.value)}</strong><span>${esc(d.unit)}</span></div><pre>${esc(d.evidence)}</pre>`
  ];
  $("#demo-view").innerHTML = `<section class="hero panel demo-hero"><span class="eyebrow">AN INDEPENDENT ENERGY + AI PROJECT</span><h1>Ask the grid.<br>Follow the evidence.</h1><p>Electricity data is full of subtle questions: which market, which interval, which forecast vintage? GridRag explores how AI can find the right schema, write SQL, and answer from the data.</p><div class="demo-actions"><a class="primary-link" href="#playground">Open the playground ↗</a><a href="#evaluation">See the comparison →</a></div><div class="demo-stats"><span><strong>65</strong> documented tables</span><span><strong>7</strong> US grid regions</span><span><strong>100%</strong> synthetic data</span></div></section>
    <section class="panel walkthrough"><div class="panel-head"><div><span class="eyebrow">NO KEY NEEDED</span><h2>One question, explained.</h2></div><span class="badge">Guided walkthrough</span></div><p class="walkthrough-note">These examples use verified reference queries on the fictional warehouse. They are prepared examples, not live model responses.</p><div class="demo-options" role="group" aria-label="Walkthrough examples">${demos.map((item,i) => `<button data-demo="${i}" aria-pressed="${i === state.demoIndex}">${esc(item.label)}</button>`).join("")}</div><div class="walkthrough-grid"><div class="demo-steps">${titles.map((title,i) => `<button data-step="${i}" aria-pressed="${i === state.demoStep}"><span>0${i+1}</span>${title}<b aria-hidden="true">→</b></button>`).join("")}</div><div class="demo-detail" aria-live="polite"><span class="eyebrow">STEP ${state.demoStep + 1} OF 4</span><h2>${titles[state.demoStep]}</h2><p>${explanations[d.id][state.demoStep]}</p>${detail[state.demoStep]}<button id="demo-next" class="primary-link">${state.demoStep < 3 ? "Next step →" : "Start again ↺"}</button></div></div></section>
    <div class="demo-bottom"><div><span class="eyebrow">WHY THIS EXISTS</span><h2>Good answers start with the right context.</h2><p>A personal exploration of schema retrieval for energy analytics. Built to make the path from natural-language question to database evidence visible, measurable, and reproducible.</p></div><a href="#evaluation">Explore the evaluation ↗</a></div>`;
  document.querySelectorAll("[data-demo]").forEach(b => b.onclick = () => { state.demoIndex = Number(b.dataset.demo); state.demoStep = 0; paintDemo(); document.querySelector(`[data-demo="${state.demoIndex}"]`).focus(); });
  document.querySelectorAll("[data-step]").forEach(b => b.onclick = () => { state.demoStep = Number(b.dataset.step); paintDemo(); document.querySelector(`[data-step="${state.demoStep}"]`).focus(); });
  $("#demo-next").onclick = () => { state.demoStep = (state.demoStep + 1) % 4; paintDemo(); $("#demo-next").focus(); };
}

function paintBenchmark() {
  const b = state.benchmark;
  if (!b?.summary?.length) {
    $("#benchmark-results").innerHTML = `<h2>Comparison results are not published yet.</h2><p class="footnote">The reproducible benchmark runs locally against Qdrant. Measured results will appear here after the run is verified.</p>`;
    return;
  }
  const summary = state.scoreScope === "numeric" ? b.numeric_summary : state.scoreScope === "behavior" ? b.behavior_summary : b.summary;
  const names = {routed: "GridRag · routed schema", "vector-k4": "Qdrant · top 4 tables", "vector-k6": "Qdrant · top 6 tables"};
  $("#benchmark-results").innerHTML = `<div class="panel-head"><div><span class="eyebrow">RECORDED BENCHMARK</span><h2>Accuracy, latency, and cost</h2></div><span class="badge">${b.manifest.cases} questions × ${b.manifest.repeats} repeats</span></div><div class="demo-options" role="group" aria-label="Benchmark question types">${[["all","All questions"],["numeric","Numeric questions"],["behavior","Safety & scope"]].map(([key,label]) => `<button data-score-scope="${key}" aria-pressed="${state.scoreScope === key}">${label}</button>`).join("")}</div><div class="comparison-scroll"><table class="comparison-table"><caption>End-to-end results, including failed attempts · ${summary[0].attempts} attempts per method</caption><thead><tr><th scope="col">Schema retrieval</th><th scope="col">Accuracy</th><th scope="col">Median latency</th><th scope="col">p95 latency</th><th scope="col">Est. cost / question</th></tr></thead><tbody>${summary.map(r => `<tr><th scope="row">${esc(names[r.method] || r.method)}</th><td><strong>${(r.accuracy*100).toFixed(1)}%</strong></td><td>${seconds(r.median_seconds)}</td><td>${seconds(r.p95_seconds)}</td><td>$${r.mean_cost_usd.toFixed(5)}</td></tr>`).join("")}</tbody></table></div><p class="footnote">Measured ${esc(b.manifest.created_utc.slice(0,10))} · SQL model: ${esc(b.manifest.models.sql)} · Embeddings: ${esc(b.manifest.embedding_model)}. Latency includes the gate, retrieval, SQL generation, execution, and answer. Index build: ${seconds(b.manifest.index_seconds)} (excluded from per-question latency).</p><p class="footnote">${esc(b.manifest.cost_basis)}. These are configured rate estimates, not billing records.</p><div class="interval-notes">${(b.paired_intervals || []).map(i => `<p>Routed vs ${i.comparison.endsWith("k4") ? "top 4" : "top 6"}: <strong>${(i.accuracy_delta*100).toFixed(1)} percentage points</strong> accuracy difference; 95% case-bootstrap interval ${(i.ci95[0]*100).toFixed(1)} to ${(i.ci95[1]*100).toFixed(1)}.</p>`).join("")}</div><a class="artifact-link" href="/static/benchmark.json" download>Download measured results, SQL, and evidence (JSON) ↓</a><details class="case-breakdown"><summary>Inspect results by question</summary>${b.cases.map(c => {
    const rows = b.runs.filter(r => r.case === c.id);
    return `<article><strong>${esc(c.question)}</strong><div>${Object.entries(names).map(([key,label]) => {
      const trials = rows.filter(r => r.method === key), correct = trials.filter(r => r.correct).length;
      return `<span>${label}: <b>${correct}/${trials.length}</b></span>`;
    }).join("")}</div></article>`;
  }).join("")}</details>`;
  document.querySelectorAll("[data-score-scope]").forEach(button => button.onclick = () => {
    state.scoreScope = button.dataset.scoreScope; paintBenchmark();
    document.querySelector(`[data-score-scope="${state.scoreScope}"]`).focus();
  });
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
    // The default demo and recorded comparison are static and require no provider key.
    const response = await fetch("/static/demo.json");
    if (!response.ok) throw new Error("The demo assets are unavailable. Please reload in a moment.");
    state.meta = await response.json();
    render();
    fetch("/static/benchmark.json").then(r => r.ok ? r.json() : null).then(data => { state.benchmark = data; paintBenchmark(); }).catch(() => {});
    fetch("/api/meta").then(r => r.ok ? r.json() : null).then(meta => {
      if (!meta) return;
      state.meta = {...state.meta, ...meta};
      $("#model-access-note").textContent = `Models: ${meta.models.decisions} · ${meta.models.answer} · Requires Decisions and Responses API access.`;
      paintKey(); paint(); paintEvaluation();
    }).catch(() => {});
  } catch (error) {
    $("#main").innerHTML = `<section class="panel boot-error"><h1>Could not load the demo</h1><p>${esc(error.message)}</p><button id="retry" type="button">Retry</button></section>`;
    $("#retry").onclick = boot;
  }
}
boot();
