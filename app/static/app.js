const state = { demo: { index: 0, running: false, progress: {}, result: null, error: "", timer: null, runId: 0, stopped: false }, scoreScope: "all", benchmark: null, apiKey: "", keyMessage: "", meta: null, result: null, running: false, error: "", progress: {}, runs: new Map(),
  evaluation: { running: false, active: null, stage: null, results: new Map(), summary: null, error: "", category: "all", repeats: 1, filter: "all", plan: [], stopRequested: false, manifest: null } };
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const md = (value) => esc(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
const number = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const seconds = value => value == null ? "—" : `${Number(value).toFixed(2)} s`;
const modelReady = () => Boolean(state.apiKey || (state.meta?.model_ready && !state.meta?.requires_api_key));
const requestHeaders = () => ({ "Content-Type": "application/json", "Accept": "application/x-ndjson",
  ...(state.apiKey ? { "Authorization": `Bearer ${state.apiKey}` } : {}) });
const preset = () => state.meta.presets.find(p => p.question === $("#question").value.trim());
const presetButtons = (items, offset = 0) => items.map((p, i) => `<button type="button" data-preset="${i + offset}" title="${esc(p.question)}" aria-label="${esc(p.label)}: ${esc(p.question)}"><b>${esc(p.label)}</b><span>${esc(p.concept)}</span></button>`).join("");

function runWorkspace(prefix = "") {
  return `    <div class="workspace">
      <section class="panel flow-panel">
        <div class="panel-head"><div><span class="eyebrow">QUESTION → EVIDENCE</span><h2>The path to an answer</h2></div><div class="run-status"><span class="live" id="${prefix}live-status" role="status"></span>${prefix === "demo-" ? '<button id="demo-stop" class="text-button" type="button" hidden>Stop replay</button>' : ""}</div></div>
        <div id="${prefix}flow" class="flow"></div>
      </section>
      <section class="panel answer-panel" aria-labelledby="${prefix}answer-heading">
        <div class="panel-head"><div><span class="eyebrow">RESULT</span><h2 id="${prefix}answer-heading" tabindex="-1">Answer</h2></div><span id="${prefix}answer-state"></span></div>
        <div id="${prefix}answer" class="answer" aria-live="polite"></div>
      </section>
    </div>
    <section class="panel details-panel" id="${prefix}details-panel" hidden>
      <div class="panel-head"><div><span class="eyebrow">EVIDENCE</span><h2>Inspect the SQL</h2></div></div>
      <div id="${prefix}details"></div>
    </section>
`;
}

function render() {
  $("#main").innerHTML = `
    <div id="demo-view"></div>
    <div id="ask-view">
    <section class="hero panel">
      <div class="page-intro"><span class="eyebrow">THE PLAYGROUND</span><h1>Your question. Real SQL.</h1><p>Ask about energy data in plain language. Follow the answer back to its source.</p></div>
      <section id="key-settings" class="api-access" aria-labelledby="api-key-heading">
        <div class="api-access-body">
          <div class="api-access-intro"><div class="api-access-heading"><h2 id="api-key-heading">Connect your OpenAI key</h2><span class="key-connection"><span class="connection-dot" aria-hidden="true"></span><span id="key-summary">Not connected</span></span></div><p>Use your own key to ask live questions. Your key stays in this tab’s memory and passes through the app’s backend to OpenAI. It is never saved by the app. Reload or remove it to clear it. Usage is billed to your OpenAI account.</p><small id="model-access-note">Requires access to the configured Decisions and Responses models.</small></div>
          <form id="api-key-form" class="api-key-form" autocomplete="off">
            <label for="api-key">OpenAI API key</label><div class="api-key-controls"><input id="api-key" type="password" name="visitor-api-key" maxlength="503" placeholder="sk-…" autocomplete="off" spellcheck="false" autocapitalize="none" aria-describedby="api-key-status"><button id="save-key" type="submit">Use key</button><button id="clear-key" type="button" hidden>Remove</button></div>
            <span id="api-key-status" role="status"></span><a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">Get an API key ↗</a>
          </form>
        </div>
      </section>
      <div class="market-strip" aria-label="Available energy markets">${state.meta.isos.map(iso => `<span>${esc(iso)}</span>`).join("")}<small>${state.meta.catalog_tables} tables · ${state.meta.isos.length} markets</small></div>
      <aside class="data-window" id="data-window"><span class="connection-dot" aria-hidden="true"></span><span>Synthetic dataset · Through <strong>Oct 21, 2026</strong> · Use a specific region and date.</span></aside>
      <form id="ask-form" class="ask-form">
        <label for="question">What would you like to know?</label>
        <div class="question-composer"><textarea id="question" aria-describedby="data-window question-hint" rows="3" maxlength="${state.meta.max_question_chars}" required placeholder="What was ERCOT’s peak demand on October 19, 2026?"></textarea><div class="composer-bottom"><span id="question-hint">⌘ / Ctrl + Enter to ask</span><button id="ask-button" type="submit">Ask the grid →</button></div></div>
        <span id="ask-access-note" class="footnote">Add your key above to run a live question.</span>
      </form>
      <p class="preset-hint">Or start with an example</p>
      <div class="examples" aria-label="Preset questions">${presetButtons(state.meta.presets.slice(0, 3))}</div>
      <details class="more-examples"><summary>More examples: prices, forecasts, and storage</summary><div class="examples">${presetButtons(state.meta.presets.slice(3), 3)}</div></details>
      <details class="question-guide">
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


    </section>
    ${runWorkspace()}
    <section class="panel metrics-panel" id="metrics-panel" hidden>
      <div class="panel-head"><div><span class="eyebrow">MEASURED RUN</span><h2>Time and model use</h2></div></div>
      <div id="metrics"></div>
    </section></div>
    <section id="evaluation-view" hidden>
      <div class="page-intro evaluation-intro"><span class="eyebrow">THE EVALUATION</span><h1>Measure the tradeoffs.</h1><p>Routed schema versus embedded retrieval. Same questions, same SQL model, same database.</p></div>
      <div id="benchmark-results" class="panel benchmark-panel"></div>
      <details class="panel methodology"><summary>How the comparison works</summary><div class="guide-grid">
        <div><strong>Routed schema</strong><p>A decision model scores tables, expands their references, then scores columns. The SQL model receives the resulting compact schema.</p></div>
        <div><strong>Embedded schema</strong><p>BGE-small embeds each documented table. Qdrant retrieves the top 4 or 6 tables, adds their references, and supplies every column to the same SQL model.</p></div>
        <div><strong>Accuracy</strong><p>Numeric questions must produce the correct final scalar SQL result. Behavior cases must decline or request clarification without executing SQL. Independent reference queries never reach the model.</p></div>
        <div><strong>Fairness and limits</strong><p>Fixed settings, shuffled method order, repeated trials, and failures included. This small synthetic benchmark does not establish production accuracy. Token costs exclude embedding compute and hosting.</p></div>
      </div></details>
      <section class="panel live-checks" aria-labelledby="evaluation-heading">
        <div class="panel-head"><div><span class="eyebrow">LIVE REGRESSION SUITE</span><h2 id="evaluation-heading">Test the whole pipeline.</h2></div><span id="evaluation-version" class="badge"></span></div>
        <p id="evaluation-suite-info" class="footnote"></p>
        <p class="footnote">These checks exercise the routed playground. The recorded comparison above is a separate, fixed benchmark. Numeric questions request one row and one numeric answer column. Reference answers and SQL are never sent to the live model.</p>
        <div class="evaluation-controls"><label for="evaluation-category">Coverage<select id="evaluation-category"></select></label><label for="evaluation-repeats">Trials per question<select id="evaluation-repeats"><option value="1">1 trial</option><option value="3">3 trials</option></select></label></div>
        <div class="evaluation-action"><button id="evaluation-run" type="button">Run checks →</button><button id="evaluation-stop" class="text-button" type="button" hidden>Stop after this case</button><button id="evaluation-download" class="text-button" type="button" disabled>Download report ↓</button></div>
        <p id="evaluation-access" class="footnote"></p>
        <div id="evaluation-summary" class="evaluation-summary" role="status"></div><div id="evaluation-metrics"></div>
        <div class="evaluation-results-toolbar"><label for="evaluation-filter">Show results<select id="evaluation-filter"><option value="all">All cases</option><option value="failed">Needs review</option><option value="passed">All checks passed</option></select></label><span class="footnote">Filtering does not change scores.</span></div>
        <div id="evaluation-cases" class="evaluation-cases"></div>
      </section>
    </section>`;
  $(".skip-link").onclick = event => { event.preventDefault(); $("#main").focus(); $("#main").scrollIntoView({block: "start"}); };
  $("#api-key-form").onsubmit = event => {
    event.preventDefault();
    if (state.running || state.evaluation.running) return;
    const key = $("#api-key").value.trim();
    if (!/^sk-[A-Za-z0-9_-]{10,500}$/.test(key)) {
      $("#api-key").setAttribute("aria-invalid", "true");
      state.keyMessage = "Enter a valid OpenAI API key beginning with sk-.";
      paintKey(); return;
    }
    state.apiKey = key; state.keyMessage = ""; $("#api-key").value = "";
    $("#api-key").removeAttribute("aria-invalid");
    paint(); paintEvaluation();
    $("#question").focus();
  };
  $("#clear-key").onclick = () => {
    if (state.running || state.evaluation.running) return;
    state.apiKey = ""; state.keyMessage = ""; $("#api-key").value = "";
    $("#api-key").removeAttribute("aria-invalid");
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
  $("#question").onkeydown = event => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault(); $("#ask-form").requestSubmit();
    }
  };
  const initialQuestion = new URLSearchParams(location.search).get("q");
  $("#question").value = (initialQuestion || "").slice(0, state.meta.max_question_chars);
  if (initialQuestion && !location.hash) history.replaceState(null, "", `${location.search}#playground`);
  $("#evaluation-run").onclick = () => runEvaluation();
  $("#evaluation-category").onchange = event => { state.evaluation.category = event.target.value; paintEvaluation(); };
  $("#evaluation-repeats").onchange = event => { state.evaluation.repeats = Number(event.target.value); paintEvaluation(); };
  $("#evaluation-filter").onchange = event => { state.evaluation.filter = event.target.value; paintEvaluation(); };
  $("#evaluation-stop").onclick = () => { state.evaluation.stopRequested = true; paintEvaluation(); };
  $("#evaluation-download").onclick = downloadEvaluation;
  window.onhashchange = showView;
  paintDemo(); paintBenchmark(); paintCatalog();
  $("#catalog-search").oninput = paintCatalog;
  showView();
  paintPresets(); paint();
  paintEvaluation();
}

function showView(event) {
  const requested = location.hash.slice(1);
  const view = ["playground", "evaluation"].includes(requested) ? requested : requested === "ask" ? "playground" : "demo";
  if (view !== "demo" && state.demo.running) stopDemo();
  $("#demo-view").hidden = view !== "demo";
  $("#ask-view").hidden = view !== "playground";
  $("#evaluation-view").hidden = view !== "evaluation";
  const title = {demo: "Demo", playground: "Playground", evaluation: "Evaluation"}[view];
  document.title = `${title} · GridRag`;
  document.querySelectorAll("[data-view-link]").forEach(link => {
    const selected = link.dataset.viewLink === view;
    link.classList.toggle("selected", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
  if (event) $("#main").focus({preventScroll: true});
}

function paintCatalog() {
  const query = ($("#catalog-search").value || "").toLowerCase();
  const tables = (state.meta.catalog || []).filter(t => t.ddl.toLowerCase().includes(query));
  $("#catalog-list").innerHTML = `<p class="footnote">${tables.length} table definitions · Read-only synthetic warehouse hosted by the app</p>` + tables.map(t => `<details class="evidence-item"><summary>${esc(t.name)}</summary><pre>${esc(t.ddl)}</pre></details>`).join("");
}

function paintDemo() {
  const demos = state.meta.demos || [], demo = state.demo, d = demos[demo.index];
  if (!d) return;
  const options = (items, offset = 0) => items.map((item, i) => `<button type="button" data-demo="${i + offset}" aria-pressed="${i + offset === demo.index}" aria-label="${esc(item.label)}: ${esc(item.question)}"><b>${esc(item.label)}</b><span>${esc(item.concept)}</span></button>`).join("");
  $("#demo-view").innerHTML = `
    <section class="hero panel">
      <div class="page-intro"><span class="eyebrow">THE DEMO · NO KEY NEEDED</span><h1>Your question. Real SQL.</h1><p>Try the playground experience. Choose a question and follow it from the first check to the answer.</p></div>
      <div class="market-strip" aria-label="Available energy markets">${state.meta.isos.map(iso => `<span>${esc(iso)}</span>`).join("")}<small>${state.meta.catalog_tables} tables · ${state.meta.isos.length} markets</small></div>
      <form id="demo-form" class="ask-form">
        <label for="demo-question">What would you like to know?</label>
        <div class="question-composer"><textarea id="demo-question" rows="3" readonly aria-describedby="demo-question-hint demo-note">${esc(d.question)}</textarea><div class="composer-bottom"><span id="demo-question-hint">Choose an example below · ⌘ / Ctrl + Enter to ask</span><button id="demo-ask-button" type="submit">Ask the grid →</button></div></div>
      </form>
      <div class="demo-replay-note" id="demo-note"><span class="badge">Prepared replay</span><p>Verified SQL and prepared answers on fictional data. The stages and text playback are illustrative; no OpenAI calls or charges.</p></div>
      <p class="preset-hint">Choose a question to try</p><div class="examples" role="group" aria-label="Demo questions">${options(demos.slice(0, 3))}</div>
      <details class="more-examples"><summary>More examples: prices, forecasts, and storage</summary><div class="examples">${options(demos.slice(3), 3)}</div></details>
      <div class="demo-toolbar"><a class="artifact-link" href="#playground">Ask a custom question in the playground ↗</a></div>
    </section>
    ${runWorkspace("demo-")}
    <section class="panel metrics-panel" id="demo-summary" hidden><div class="panel-head"><div><span class="eyebrow">REFERENCE RESULT</span><h2>What this example used</h2></div><span class="badge">Prepared replay</span></div><div id="demo-summary-content"></div><div class="demo-toolbar"><button id="demo-replay" class="text-button" type="button">Replay this answer ↺</button><button id="demo-choose" class="text-button" type="button">Try another question ↑</button></div></section>`;
  $("#demo-form").onsubmit = event => { event.preventDefault(); runDemo(); };
  $("#demo-question").onkeydown = event => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); $("#demo-form").requestSubmit(); }
  };
  document.querySelectorAll("[data-demo]").forEach(button => button.onclick = () => {
    const expanded = $("#demo-view .more-examples").open;
    stopDemo(); demo.index = Number(button.dataset.demo); demo.progress = {}; demo.result = null; demo.stopped = false;
    paintDemo();
    $("#demo-view .more-examples").open = expanded;
    document.querySelector(`[data-demo="${demo.index}"]`).focus({preventScroll: true});
  });
  $("#demo-stop").onclick = () => { stopDemo(); $("#demo-ask-button").focus({preventScroll: true}); };
  $("#demo-replay").onclick = runDemo;
  $("#demo-choose").onclick = () => { $("#demo-ask-button").focus(); };
  paintDemoRun();
}

function paintDemoRun() {
  const demo = state.demo, d = state.meta.demos[demo.index];
  paintRun(demo, "demo-", true);
  $("#demo-ask-button").disabled = demo.running;
  $("#demo-ask-button").textContent = demo.running ? "Replaying…" : demo.result || demo.stopped ? "Replay answer ↺" : "Ask the grid →";
  $("#demo-stop").hidden = !demo.running;
  document.querySelectorAll("[data-demo]").forEach(button => { button.disabled = demo.running; });
  $("#demo-summary").hidden = !demo.result;
  if (demo.stopped) {
    $("#demo-live-status").textContent = "Replay stopped";
    $("#demo-answer").innerHTML = '<p class="footnote">Replay stopped. Select Replay answer to start again.</p>';
  }
  if (demo.result) $("#demo-summary-content").innerHTML = `<div class="metric-grid"><div><small>Tables in reference SQL</small><strong>${d.tables.length} / ${state.meta.catalog_tables}</strong></div><div><small>Reference queries</small><strong>1</strong></div><div><small>Result rows</small><strong>1</strong></div><div><small>OpenAI calls in replay</small><strong>0</strong></div></div><p class="footnote">This reference query was executed against the fictional warehouse when the demo was built. Add your key in the playground to generate new SQL and see measured model use.</p>`;
}

function stopDemo() {
  const demo = state.demo;
  clearTimeout(demo.timer); demo.timer = null; demo.runId += 1;
  if (!demo.running) return;
  demo.running = false; demo.stopped = true; demo.progress = {}; demo.result = null;
  paintDemoRun();
}

function runDemo() {
  const demo = state.demo, d = state.meta.demos[demo.index];
  if (demo.running || !d) return;
  clearTimeout(demo.timer);
  const runId = ++demo.runId;
  demo.running = true; demo.stopped = false; demo.result = null; demo.progress = {stage: "gate"};
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gate = {reason: "This prepared question asks for a read-only calculation on the grid dataset."};
  const route = {tables: d.tables};
  const calls = [{query: d.sql, rows: 1, csv: d.evidence, error: null}];
  const schedule = (callback, delay) => {
    demo.timer = setTimeout(() => { if (demo.running && demo.runId === runId) callback(); }, delay);
  };
  const finish = () => {
    demo.running = false; demo.timer = null;
    demo.result = {state: "answered", answer: d.answer, gate, route, tool_calls: calls};
    paintDemoRun();
  };
  const reveal = () => {
    if (reducedMotion) { finish(); return; }
    const words = d.answer.match(/\S+\s*/g) || [];
    let shown = 0;
    const chunk = () => {
      shown = Math.min(words.length, shown + 3);
      demo.progress.answer_text = words.slice(0, shown).join("");
      // Keep expanded evidence and keyboard focus stable while text is revealed.
      $("#demo-answer").innerHTML = `<div class="answer-text">${md(demo.progress.answer_text)}</div>`;
      if (shown === words.length) finish(); else schedule(chunk, 55);
    };
    chunk();
  };
  paintDemoRun();
  $("#demo-answer-heading").focus({preventScroll: true});
  $("#demo-view .workspace").scrollIntoView({behavior: reducedMotion ? "instant" : "smooth", block: "start"});
  schedule(() => {
    demo.progress = {stage: "route", gate}; paintDemoRun();
    schedule(() => {
      demo.progress = {stage: "sql", gate, route}; paintDemoRun();
      schedule(() => {
        demo.progress = {stage: "answer", gate, route, tool_calls: calls}; paintDemoRun();
        schedule(reveal, reducedMotion ? 0 : 300);
      }, reducedMotion ? 0 : 850);
    }, reducedMotion ? 0 : 700);
  }, reducedMotion ? 0 : 550);
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
  $("#api-key-status").textContent = state.keyMessage || (state.apiKey ? "Key added for this tab. Reloading or closing this tab removes it." : (state.meta.model_ready && !state.meta.requires_api_key) ? "Using the local server’s configured key. You can use your own instead." : "Add your key above to ask a question or run evaluations.");
  $("#api-key-status").classList.toggle("error", Boolean(state.keyMessage));
  $("#key-summary").textContent = state.apiKey ? "Connected for this tab" : modelReady() ? "Local server key connected" : "Not connected";
  $("#key-settings").classList.toggle("connected", modelReady());
  $("#ask-access-note").textContent = modelReady() ? "Live model requests use your key and may incur API charges." : "Add your key above to run a live question.";
}

function paintRun(session, prefix = "", isDemo = false) {
  const q = name => document.getElementById(prefix + name);
  const r = session.result, route = r?.route || session.progress.route, gate = r?.gate || session.progress.gate;
  const calls = r?.tool_calls || session.progress.tool_calls || [];
  const active = session.running ? session.progress.stage : null;
  const stageNames = {gate: "Checking request", route: "Selecting schema", sql: "Working with SQL", answer: "Interpreting results"};
  const total = state.meta.catalog_tables, selected = route?.tables || [];
  q("live-status").textContent = session.running ? stageNames[active] || "Starting…" : r ? "Finished" : "Ready";
  q("live-status").className = `live ${session.running ? "running" : ""}`;
  const steps = [
    ["Request gate", gate ? gate.reason : "Check relevance and instruction safety.", Boolean(gate)],
    ["Select schema", route ? `${selected.length} of ${total} tables selected. ${isDemo ? "Tables used by the verified reference query." : "Full columns and referenced tables retained."}` :
      "Select relevant tables from the documented catalog.", Boolean(route)],
    ["Query the warehouse", calls.length ? `${calls.length} ${calls.length === 1 ? "query" : "queries"} · ${calls.filter(c => !c.error).length} successful` :
      r ? "No queries executed." : "Generate read-only SQL; repair errors if needed.", calls.length > 0],
    ["Answer from results", r ? r.state.replaceAll("_", " ") : "Use query evidence to answer the question.", r?.state === "answered"],
  ];
  const openSchema = q("flow").querySelector(".schema-list")?.open;
  q("flow").innerHTML = steps.map(([title, description, done], i) => {
    const isActive = active === ["gate", "route", "sql", "answer"][i];
    return `
    <div class="flow-step ${isActive ? "active" : done ? "complete" : ""}" ${isActive ? 'aria-current="step"' : ""}><span class="step-number">${isActive ? '<span class="stage-spinner" aria-hidden="true"></span>' : done ? "✓" : `0${i + 1}`}</span>
      <div><strong>${title}</strong>${isActive ? '<span class="active-label">Active</span>' : ""}<p>${esc(description)}</p>
      ${i === 1 && route ? `<div class="schema-meter" role="img" aria-label="${selected.length} of ${total} catalog tables selected">
        <span style="width:${100 * selected.length / total}%"></span></div>
        <details class="schema-list" ${openSchema ? "open" : ""}><summary>Selected tables${route.fallback ? " · includes uncertain matches" : ""}</summary>
          ${selected.map(t => `<code>${esc(t)}${route.columns?.[t] ? ` · ${esc(route.columns[t].join(", "))}` : ""}</code>`).join("") || "None"}</details>` : ""}</div></div>`;
  }).join("");
  q("answer-state").innerHTML = r ? `<span class="badge ${r.state === "answered" ? "good" : "warn"}">${esc(r.state.replaceAll("_", " "))}</span>` : "";
  q("answer").innerHTML = session.error ? `<p class="error">${esc(session.error)}</p>` : r ?
    `<div class="answer-text">${md(r.answer)}</div>` : session.running && session.progress.answer_text ?
    `<div class="answer-text">${md(session.progress.answer_text)}</div>` : session.running ?
    `<div class="loading"><i></i>${esc(stageNames[active] || "Starting the pipeline")}…</div><p class="footnote">${isDemo ? "Replaying prepared stages. SQL and evidence appear next." : "The highlighted stage follows backend progress. SQL and evidence appear as they return."}</p>` :
    '<div class="empty"><span class="empty-symbol" aria-hidden="true">↳</span><strong>An answer you can inspect.</strong><span>Ask a question above. Your answer, SQL, and supporting data will appear here.</span></div>';
  q("details-panel").hidden = !calls.length;
  if (q("details").dataset.calls !== JSON.stringify(calls)) {
    q("details").dataset.calls = JSON.stringify(calls);
    q("details").innerHTML = calls.map((call, i) => `<details class="evidence-item" ${i === calls.length - 1 ? "open" : ""}>
    <summary>Query ${i + 1} · ${call.error ? "error" : `${call.rows} result ${call.rows === 1 ? "row" : "rows"}`}</summary>
    <pre>${esc(call.query)}</pre>${call.csv ? `<div class="evidence-output"><b>Returned data</b><pre>${esc(call.csv)}</pre></div>` : ""}
    ${call.truncated ? `<p>${esc(call.truncated)}</p>` : ""}
    ${call.error ? `<p class="error">${esc(call.error)}</p>` : ""}</details>`).join("");
  }
  q("answer").setAttribute("aria-busy", String(session.running));
}

function paint() {
  paintKey();
  paintRun(state);
  const r = state.result, calls = r?.tool_calls || state.progress.tool_calls || [];
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
  $("#ask-button").disabled = state.running || state.evaluation.running || !$("#question").value.trim();
  $("#ask-button").textContent = state.running ? "Running…" : modelReady() ? "Ask the grid →" : "Connect key to ask →";
  $("#answer").setAttribute("aria-busy", String(state.running));
  $("#question").disabled = state.running || state.evaluation.running;
  document.querySelectorAll("[data-preset], [data-question]").forEach(b => { b.disabled = state.running || state.evaluation.running; });
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question || state.running || state.evaluation.running) return;
  if (!modelReady()) {
    $("#api-key").focus();
    return;
  }
  const p = preset();
  state.running = true; state.result = null; state.error = ""; state.progress = {}; paint(); paintEvaluation();
  $("#answer-heading").focus({preventScroll: true});
  $("#ask-view .workspace").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
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

function evaluationStats() {
  const entries = [...state.evaluation.results.values()];
  const costs = entries.map(entry => entry.assessment?.result?.usage?.cost_usd).filter(value => Number.isFinite(value));
  const latencies = entries.map(entry => entry.assessment?.result?.timings?.total).filter(value => Number.isFinite(value)).sort((a,b) => a-b);
  const median = latencies.length ? (latencies[Math.floor((latencies.length-1)/2)] + latencies[Math.ceil((latencies.length-1)/2)]) / 2 : null;
  return {completed: entries.length, passed: entries.filter(entry => entry.assessment?.passed).length,
    correct: entries.filter(entry => entry.assessment?.correct).length,
    errors: entries.filter(entry => entry.error || entry.assessment?.result?.state === "failed").length,
    cost_usd: costs.reduce((sum, cost) => sum + cost, 0), costed_attempts: costs.length,
    median_seconds: median, p95_seconds: latencies.length ? latencies[Math.ceil(.95*latencies.length)-1] : null};
}

function paintEvaluation() {
  const e = state.evaluation, all = state.meta.evaluation_cases || [], suite = state.meta.evaluation_suite;
  const groups = suite?.groups || [...new Set(all.map(c => c.category || "analytics"))].map(id => ({id, label:id}));
  const cases = all.filter(c => e.category === "all" || c.category === e.category);
  $("#evaluation-category").innerHTML = '<option value="all">All categories</option>' + groups.map(g => `<option value="${esc(g.id)}">${esc(g.label)}${g.cases ? ` (${g.cases})` : ""}</option>`).join("");
  $("#evaluation-category").value = e.category;
  $("#evaluation-repeats").value = String(e.repeats);
  $("#evaluation-category").disabled = e.running;
  $("#evaluation-repeats").disabled = e.running;
  $("#evaluation-version").textContent = suite ? `Suite v${suite.version}` : "Live checks";
  $("#evaluation-suite-info").textContent = suite ? `${suite.cases} questions · ${suite.numeric} numeric · ${suite.behavior} scope and safety · ${suite.groups.length} coverage categories` : `${all.length} questions available`;
  $("#evaluation-run").disabled = e.running || state.running || !modelReady() || !cases.length;
  $("#evaluation-run").textContent = e.running ? "Evaluation running…" : `Run ${cases.length * e.repeats} ${cases.length * e.repeats === 1 ? "trial" : "trials"} →`;
  $("#evaluation-stop").hidden = !e.running;
  $("#evaluation-stop").disabled = e.stopRequested;
  $("#evaluation-stop").textContent = e.stopRequested ? "Stopping after this case…" : "Stop after this case";
  $("#evaluation-download").disabled = e.running || !e.results.size;
  $("#evaluation-access").innerHTML = modelReady() ? `Starting a run makes up to <strong>${cases.length * e.repeats} paid question runs</strong> using your connected key. Each question may require several model calls. Each new run replaces the displayed report; download it first to keep it.` : '<a href="#playground">Connect your OpenAI key in the playground</a> to run checks. You can inspect every case and its expected result without a key.';
  const stats = evaluationStats(), total = e.plan.length;
  const stageNames = {gate:"Checking request",route:"Selecting schema",sql:"Running SQL",answer:"Answering"};
  $("#evaluation-summary").innerHTML = `<strong>${e.running ? `${stats.completed} / ${total} trials complete` : total ? `${stats.completed} / ${total} trials completed${stats.completed < total ? " · Partial run" : ""}` : "Ready to evaluate"}</strong><span>${e.active ? `${esc(e.active.id)} · Trial ${e.active.repeat + 1} · ${esc(stageNames[e.stage] || "Starting")}` : "Task correctness and all-check pass rate are reported separately."}</span>${e.error ? `<span class="error">${esc(e.error)}</span>` : ""}`;
  $("#evaluation-metrics").innerHTML = stats.completed ? `<div class="metric-grid"><div><small>Task correct / completed</small><strong>${stats.correct} / ${stats.completed}</strong></div><div><small>All checks passed / completed</small><strong>${stats.passed} / ${stats.completed}</strong></div><div><small>Execution / provider errors</small><strong>${stats.errors}</strong></div><div><small>Reported model cost</small><strong>$${stats.cost_usd.toFixed(5)}</strong></div></div><p class="footnote">Median ${seconds(stats.median_seconds)} · p95 ${seconds(stats.p95_seconds)} · Cost reported for ${stats.costed_attempts}/${stats.completed} attempts; failed-call billing and hosting are excluded. Task correctness requires the expected end state and complete scalar evidence (or no SQL for behavior cases). All checks additionally cover routing, forbidden SQL, answer value, and unit labels. Retries after repaired SQL remain visible. This suite does not estimate production accuracy.</p>` : "";
  const expanded = new Set([...document.querySelectorAll("#evaluation-cases details[open]")].map(node => node.dataset.detailKey));
  const displayed = cases.filter(c => {
    const attempts = [...e.results.values()].filter(entry => entry.id === c.id);
    return e.filter === "all" || e.filter === "failed" && attempts.some(entry => !entry.assessment?.passed) || e.filter === "passed" && attempts.length > 0 && attempts.every(entry => entry.assessment?.passed);
  });
  $("#evaluation-cases").innerHTML = displayed.map((c, i) => {
    const attempts = [...e.results.values()].filter(entry => entry.id === c.id);
    const passed = attempts.filter(entry => entry.assessment?.passed).length;
    const active = e.active?.id === c.id;
    const status = active ? "Running" : attempts.length ? `${passed}/${attempts.length} passed` : "Not run";
    const statusClass = active ? "active" : attempts.length ? passed === attempts.length ? "good" : "warn" : "";
    const expected = c.expected == null ? esc(c.expected_state) : `${number(c.expected)} ${esc(c.unit)} · tolerance ±${c.tolerance ?? .01}`;
    return `<article class="evaluation-case ${statusClass}"><div class="evaluation-case-head"><span class="case-index">${String(i+1).padStart(2,"0")}</span><div><strong>${esc(c.label)}</strong><p>${esc(c.question)}</p><small>${esc(groups.find(g => g.id === c.category)?.label || c.category || "Analytics")} · ${esc(c.difficulty || "standard")} · Expected: ${expected}</small></div><span class="badge ${statusClass}">${status}</span></div>
      <details class="evaluation-result" data-detail-key="contract-${esc(c.id)}" ${expanded.has(`contract-${c.id}`) ? "open" : ""}><summary>Expected behavior and evidence contract</summary><p class="footnote">End state: ${esc(c.expected_state)} · ${esc(c.result_contract || "One numeric scalar")}.</p>${c.required_tables?.length ? `<p class="footnote">Required tables: ${c.required_tables.map(esc).join(", ")}</p>` : ""}${c.excluded_tables?.length ? `<p class="footnote">Excluded tables: ${c.excluded_tables.map(esc).join(", ")}</p>` : ""}${c.forbidden_sql?.length ? `<p class="footnote">Forbidden SQL text: ${c.forbidden_sql.map(esc).join(", ")}</p>` : ""}${c.verification ? `<p class="footnote">${esc(c.verification)}</p>` : ""}</details>
      ${attempts.map(entry => {
        const a = entry.assessment, r = a?.result, key = `${entry.id}:${entry.repeat}`;
        return `<details class="evaluation-result" data-detail-key="${esc(key)}" ${expanded.has(key) ? "open" : ""}><summary>Trial ${entry.repeat+1} · ${a?.passed ? "All checks passed" : "Needs review"} · ${seconds(r?.timings?.total)}</summary>${entry.error ? `<p class="error">${esc(entry.error)}</p>` : ""}${a ? `<p class="footnote">Task ${a.correct ? "correct" : "incorrect"} · Expected ${a.expected == null ? esc(c.expected_state) : number(a.expected)} · Observed ${a.observed == null ? "no valid scalar" : number(a.observed)} · ${a.diagnostics?.sql_calls ?? 0} SQL calls, ${a.diagnostics?.sql_errors ?? 0} query errors</p><ul class="evaluation-checks">${a.checks.map(check => `<li class="${check.passed ? "good" : "warn"}"><b>${check.passed ? "✓" : "!"} ${esc(check.name)}</b><span>${esc(check.category || "check")} · ${esc(check.detail)}</span></li>`).join("")}</ul><div class="evaluation-answer"><b>Answer</b><p>${md(r.answer || "")}</p></div><div class="stage-metrics"><span>Tokens <b>${number(r.usage?.input_tokens || 0)} in / ${number(r.usage?.output_tokens || 0)} out</b></span><span>Model calls <b>${r.usage?.calls ?? "—"}</b></span><span>Failed model calls <b>${r.usage?.failed_calls ?? "—"}</b></span><span>Reported cost <b>${r.usage?.cost_usd == null ? "—" : `$${r.usage.cost_usd.toFixed(5)}`}</b></span></div>${(r.tool_calls || []).map((call,j) => `<details class="evidence-item"><summary>Query ${j+1} · ${call.error ? "error" : `${call.rows} rows`}${call.truncated ? " · truncated" : ""}</summary><pre>${esc(call.query)}</pre>${call.csv ? `<pre>${esc(call.csv)}</pre>` : ""}${call.error ? `<p class="error">${esc(call.error)}</p>` : ""}</details>`).join("")}` : ""}</details>`;
      }).join("")}</article>`;
  }).join("") || '<p class="footnote">No cases match this filter.</p>';
}

function downloadEvaluation() {
  const e = state.evaluation;
  if (e.running || !e.results.size) return;
  // Explicit projection: tab credentials and other application state never enter reports.
  const report = {format_version: 2, manifest: e.manifest, planned_trials: e.plan,
    completed_trials: e.results.size, partial: e.results.size < e.plan.length,
    summary: {...evaluationStats(), seconds: e.summary?.seconds}, error: e.error || null,
    attempts: [...e.results.values()]};
  const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)], {type:"application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = `gridrag-evaluation-${e.manifest.started_utc.slice(0,19).replaceAll(":","-")}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function runEvaluation() {
  const e = state.evaluation, cases = (state.meta.evaluation_cases || []).filter(c => e.category === "all" || c.category === e.category);
  if (e.running || state.running || !modelReady() || !cases.length) return;
  e.running = true; e.active = null; e.stage = null; e.results.clear(); e.summary = null; e.error = ""; e.stopRequested = false;
  e.plan = Array.from({length:e.repeats}, (_,repeat) => cases.map(c => ({id:c.id, repeat}))).flat();
  e.manifest = {started_utc: new Date().toISOString(), suite: state.meta.evaluation_suite,
    models: state.meta.models || null, category: e.category, repeats:e.repeats,
    cases: cases.map(c => ({...c})), scoring: "Strict final scalar evidence; routing and prose checks reported separately", cost_basis:"Reported configured token-cost estimates; excludes hosting and unreported failed-call billing"};
  paintEvaluation(); paint();
  const started = performance.now();
  try {
    for (const trial of e.plan) {
      if (e.stopRequested) break;
      e.active = trial; e.stage = null; paintEvaluation();
      const key = `${trial.id}:${trial.repeat}`;
      let completed = false;
      try {
        const response = await fetch("/api/evaluate-case", {method:"POST", headers:requestHeaders(), body:JSON.stringify({id:trial.id})});
        if (!response.ok) {
          e.stopRequested = true;
          throw new Error((await response.json()).error || `HTTP ${response.status}`);
        }
        const reader = response.body.getReader(), decoder = new TextDecoder();
        let buffer = "", summary = null;
        try {
          const consume = line => {
            if (!line.trim()) return;
            const event = JSON.parse(line);
            if (event.type === "error") throw new Error(event.error);
            if (event.type === "case_progress") { e.stage = event.stage; paintEvaluation(); }
            if (event.type === "case_done" || event.type === "case_error") {
              const id = event.assessment?.id || event.id;
              if (id !== trial.id) throw new Error("The server returned a different evaluation case.");
              e.results.set(key, {...event, id:trial.id, repeat:trial.repeat}); completed = true; paintEvaluation();
            }
            if (event.type === "done") summary = event.summary;
          };
          while (true) {
            const {done,value} = await reader.read();
            buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
            const lines = buffer.split("\n"); buffer = lines.pop(); lines.forEach(consume);
            if (done) { if (buffer.trim()) consume(buffer); break; }
            if (summary) break;
          }
          if (!summary || !completed) throw new Error("The evaluation stream ended early. Completed trials are retained.");
        } finally { await reader.cancel(); }
        // Stop after provider failures instead of spending on the remaining suite.
        if (e.results.get(key)?.error || e.results.get(key)?.assessment?.result?.state === "failed") {
          e.error = "Stopped after a provider or execution failure. Completed trials are retained; inspect the failing case before starting a new run.";
          e.stopRequested = true;
        }
      } catch (error) {
        if (!completed) e.results.set(key, {id:trial.id,repeat:trial.repeat,error:error.message || "Evaluation request failed"});
        e.error = error.message || "Evaluation request failed"; e.stopRequested = true;
      }
      e.active = null; e.stage = null; paintEvaluation();
    }
  } finally {
    e.summary = {...evaluationStats(), seconds:(performance.now()-started)/1000};
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
      $("#model-access-note").textContent = `Models: ${meta.models.decisions} · ${meta.models.answer}. Requires Decisions and Responses API access.`;
      paintKey(); paint(); paintEvaluation();
    }).catch(() => {});
  } catch (error) {
    $("#main").innerHTML = `<section class="panel boot-error"><h1>Could not load the demo</h1><p>${esc(error.message)}</p><button id="retry" type="button">Retry</button></section>`;
    $("#retry").onclick = boot;
  }
}
boot();
