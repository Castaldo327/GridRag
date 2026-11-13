const state = { demo: { index: 0, running: false, progress: {}, result: null, error: "", timer: null, runId: 0, stopped: false }, scoreScope: "all", recordedTrials: new Map(), benchmark: null, apiKey: "", keyMessage: "", meta: null, result: null, running: false, error: "", progress: {}, runs: new Map() };
let modelMetaRequest = null;
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
function normalizeMarkdown(value) {
  let fenced = false;
  return String(value ?? "").replace(/\r\n/g, "\n").split("\n").map(line => {
    if (/^\s*(```|~~~)/.test(line)) { fenced = !fenced; return line; }
    if (fenced || !/\|\s*:?-{3,}:?\s*\|/.test(line)) return line;
    const rows = line.trim().replace(/^\\\|/, "|").split(/\|\s+\|/).map(row => row.replace(/^\|/, "").replace(/\|$/, "").trim());
    if (rows.length < 3) return line;
    const cells = rows.map(row => row.split("|").map(cell => cell.trim()));
    if (!cells[1].every(cell => /^:?-{3,}:?$/.test(cell)) || !cells.every(row => row.length === cells[0].length)) return line;
    return rows.map(row => `| ${row} |`).join("\n");
  }).join("\n");
}

function md(value) {
  const html = marked.parse(normalizeMarkdown(value), {gfm: true, breaks: true});
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "strong", "em", "del", "a", "blockquote", "pre", "code", "ul", "ol", "li", "hr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th", "td"],
    ALLOWED_ATTR: ["href", "title", "align", "start"], ALLOW_DATA_ATTR: false,
  });
}
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

function architectureView() {
  const stages = [
    ["Check the request", "Check domain relevance and misuse before retrieving schema. Decline requests that fail the gate."],
    ["Score the tables", "Evaluate every documented table independently against the question. Keep relevant candidates instead of filling a fixed top-k."],
    ["Preserve the context", "Expand foreign-key references. Score columns in parallel while retaining the structural fields needed for joins and time filters."],
    ["Compute with SQL", "Give the SQL model the selected schema, including its documented definitions and constraints. Validate each query independently, execute read-only, and allow bounded repairs."],
    ["Show the evidence", "Answer from returned rows. Expose the selected schema, executed SQL, results, timings, and model use for inspection."],
  ];
  return `<section id="architecture-view" hidden>
    <div class="page-intro architecture-intro"><span class="eyebrow">THE ARCHITECTURE</span><h1>Retrieve the schema.<br>Compute the answer.</h1><p>Energy questions depend on the right region, units, time interval, and joins. GridRag selects the database context for a question, then lets SQL perform the calculation.</p></div>
    <section class="panel architecture-pipeline" aria-labelledby="architecture-flow-heading">
      <div class="panel-head"><div><span class="eyebrow">QUESTION → SCHEMA → SQL → EVIDENCE</span><h2 id="architecture-flow-heading">A path you can inspect.</h2></div><span class="badge">65 tables · 7 regions</span></div>
      <figure class="architecture-diagram">
        <div class="architecture-diagram-scroll" role="region" aria-label="GridRag system diagram, scroll horizontally on small screens" tabindex="0"><img src="/static/architecture.svg?v=3" width="1440" height="1060" alt="A question passes the request gate and schema selection to the SQL model. The model sends read-only SQL to guarded DuckDB, receives rows or a repairable error, and returns an answer with its SQL and data evidence." aria-describedby="architecture-diagram-caption"></div>
        <figcaption id="architecture-diagram-caption"><p><strong>Follow the arrows.</strong> Gray arrows show the request and answer path. Teal arrows show selected schema and database feedback: returned rows or a repairable error. The loop between the SQL model and DuckDB lets a failed query be revised within a fixed budget.</p><a class="artifact-link" href="/static/architecture.svg?v=3" target="_blank" rel="noopener noreferrer">Open the full-size diagram ↗</a><span class="diagram-mobile-hint">Scroll the diagram horizontally to read every label.</span></figcaption>
      </figure>
      <details class="architecture-walkthrough"><summary>Walk through each stage</summary><ol class="architecture-flow">${stages.map(([title,description],i) => `<li><span class="architecture-step" aria-hidden="true">0${i+1}</span><h3>${title}</h3><p>${description}</p></li>`).join("")}</ol></details>
      <p class="architecture-boundary"><strong>The execution boundary is code.</strong> The SQL guard restricts statements, table access, functions, and resources. Questions that exceed the table budget ask for clarification. The model’s instructions and relevance scores are not access controls.</p>
    </section>
    <section class="architecture-section" aria-labelledby="architecture-design-heading"><span class="eyebrow">THE DESIGN CHOICE</span><h2 id="architecture-design-heading">Preserve the context a calculation needs.</h2>
      <div class="architecture-principles">
        <article><h3>Relevance without a fixed quota</h3><p>A comparison can need several products and a denominator. Independent table scores can keep several useful candidates without forcing every question into the same retrieval count.</p><small>Scores are model judgments, not calibrated guarantees. Too much uncertainty fails explicitly.</small></article>
        <article><h3>Keep the relationships intact</h3><p>Relevant columns alone are not enough. Referenced tables and structural fields remain available so the model can join regions, align timestamps, and preserve the documented grain.</p><small>Column selection reduces the schema sent to the SQL model. Scoring that schema adds work and cost.</small></article>
        <article><h3>Calculate from rows</h3><p>A five-minute solar reading and an hourly average can sound similar. Their table definitions distinguish them; SQL selects the interval and calculates the result. The answer stays connected to its query.</p><small>Visible evidence supports review. It does not prove that every generated query is correct.</small></article>
      </div>
    </section>
    <section class="panel architecture-comparison" aria-labelledby="architecture-comparison-heading"><span class="eyebrow">ONE CONTROLLED DIFFERENCE</span><h2 id="architecture-comparison-heading">Change the retrieval. Keep the SQL pipeline.</h2><p>The recorded experiment uses the same request gate, SQL model, repair budget, and query guard for all three approaches, using documented schema definitions without curated entity aliases.</p>
      <div class="architecture-paths"><div><span class="badge good">GridRag</span><h3>Score → expand → select</h3><p>Independent table relevance → referenced tables → relevant columns plus structural fields → SQL model.</p></div><div><span class="badge">Qdrant · top 21</span><h3>Embed → rank → expand</h3><p>Embed the question and documented tables → retrieve top-k → referenced tables with every column → the same SQL model.</p></div><div><span class="badge">Qdrant → Decisions</span><h3>Expand candidates → fuse → rerank</h3><p>48 semantic candidates + keyword matches → generic score fusion → rerank the complete candidate union → referenced tables with every column → SQL within the 25-table budget.</p></div></div>
      <p class="architecture-tradeoff"><strong>Inspect the tradeoff:</strong> compare answer accuracy, required-table recall, latency, and estimated model cost in the latest rerun. Hybrid retrieval uses the OpenAI Decisions API to rerank the Qdrant candidate pool; all three approaches use schema documentation without curated entity aliases.</p>
      <a class="artifact-link" href="#evaluation">Compare every recorded answer, timing, and cost →</a>
      <p class="footnote">30 answerable questions from easy to very hard, three trials per approach and 270 attempts in total. This small synthetic experiment compares these retrieval implementations; broader testing is needed to establish production accuracy.</p>
    </section>
    <section class="architecture-section architecture-deployment" aria-labelledby="architecture-hosting-heading"><div><span class="eyebrow">WHAT RUNS WHERE</span><h2 id="architecture-hosting-heading">A public demo with a clear boundary.</h2></div><dl><div><dt>In your browser</dt><dd>The key-free demo replays prepared answers. Evaluation displays recorded runs. Neither makes model calls.</dd></div><div><dt>On Vercel</dt><dd>The live playground sends your question through a Python API to the model and a read-only, fictional DuckDB warehouse. Your API key is held in tab memory and used by a separate backend client for your request.</dd></div><div><dt>In the local experiment</dt><dd>Qdrant and BGE-small embeddings generated the recorded comparison. Qdrant is not a live service in this deployment.</dd></div></dl><p class="footnote">An independent demonstration using fictional data. Real organizational data needs authentication, tenant authorization, stronger execution isolation, and operational monitoring.</p></section>
    <div class="demo-toolbar"><a class="primary-link" href="#demo">Try the key-free demo →</a><a class="artifact-link" href="https://github.com/Castaldo327/GridRag" target="_blank" rel="noopener noreferrer">Inspect the implementation ↗</a></div>
  </section>`;
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
      <div class="page-intro evaluation-intro"><span class="eyebrow">THE EVALUATION</span><h1>Compare the answers.</h1><p>See what GridRag and Qdrant actually returned for the same questions. Thirty answerable questions from easy to very hard. Three retrieval approaches use schema documentation and the same SQL model, with three recorded trials each and cumulative scores across all attempts. No key needed.</p></div>
      <section class="panel retrieval-update" aria-labelledby="retrieval-update-heading"><span class="eyebrow">THE NEW EXPERIMENT</span><h2 id="retrieval-update-heading">Schema-driven retrieval under test.</h2><div class="guide-grid">
        <div><h3>Use the supplied schema</h3><p>Every approach interprets the same documented tables and columns. There are no curated entity aliases, table-specific relevance rules, or special region, measure, cadence, and coverage scorers. Keys and time fields come from declared constraints and types.</p><p class="footnote">This POC measures generic query logic on a small synthetic dataset. It does not establish accuracy across production domains or performance at catalog scale.</p></div>
        <div><h3>Strengthen vector retrieval</h3><p>Increase dense retrieval to top 21. For the reranked variant, retrieve 48 semantic candidates, combine semantic similarity with BM25 keyword scores over the supplied schema documents, then rerank against the full question. Retrieval uses no table-specific rules or domain alias expansion. Expand references before passing the final schema to SQL.</p><p><strong>48 semantic candidates + keywords → rerank the full pool → up to 25 tables including references.</strong></p><p class="footnote">Hybrid adds a paid OpenAI Decisions API reranker. The current comparison uses top-21 dense retrieval and a reranked variant with a 25-table cap. Both use schema documentation without curated aliases.</p></div>
      </div></section>
      <div id="benchmark-results" class="panel benchmark-panel"></div>
      <div id="recorded-answers"></div>
      <details class="panel methodology"><summary>How the comparison works</summary><div class="guide-grid">
        <div><strong>Routed schema</strong><p>A decision model scores tables, expands their references, then scores columns. The SQL model receives the resulting compact schema.</p></div>
        <div><strong>Embedded schema</strong><p>BGE-small embeds each documented table. Qdrant retrieves the top 21 tables, adds their references, and supplies every column to the same SQL model.</p></div>
        <div><strong>Hybrid retrieval</strong><p>Retrieve 48 semantic candidates and add up to 12 BM25 keyword matches. Fuse semantic and keyword scores without table-specific rules or domain alias expansion, then rerank the full union (up to 60 tables) against the complete question and supplied schema documentation. Expand references and select within the 25-table budget. One batched call to the OpenAI Decisions API (gpt-6-luna) assigns a relevance probability to each candidate. Those probabilities determine the second-pass ranking; its latency and cost are included.</p></div>
        <div><strong>Shared schema context</strong><p>Every approach uses the supplied schema documentation without a hand-maintained entity dictionary. The request gate and SQL instructions are domain-neutral. Reference tables come from foreign keys; retained structural columns come from declared keys and date/time types. Finding the right table and interpreting its fields are measured together.</p></div>
        <div><strong>Accuracy</strong><p>Every question requires a verified answer. Scalar results must match the independent reference value; table results must match every required row and column. A clarification is not a correct answer for this capability suite. Reference queries never reach the model.</p></div>
        <div><strong>Fairness and limits</strong><p>Three trials per question and approach, shuffled method order, and all failures included. Cumulative accuracy counts every attempt; each approach has 90 attempts across the 30 questions. All three approaches share a 25-table evaluation budget including references and a 4,096-token SQL output limit; the playground retains its 10-table limit. These synthetic development questions are not an unseen test set. Three trials show some run-to-run variability; this dataset does not establish production-scale or cross-domain generalization. Token costs exclude embedding compute and hosting.</p></div>
      </div></details>

    </section>
    ${architectureView()}`;
  $(".skip-link").onclick = event => { event.preventDefault(); $("#main").focus(); $("#main").scrollIntoView({block: "start"}); };
  $("#api-key-form").onsubmit = event => {
    event.preventDefault();
    if (state.running) return;
    const key = $("#api-key").value.trim();
    if (!/^sk-[A-Za-z0-9_-]{10,500}$/.test(key)) {
      $("#api-key").setAttribute("aria-invalid", "true");
      state.keyMessage = "Enter a valid OpenAI API key beginning with sk-.";
      paintKey(); return;
    }
    state.apiKey = key; state.keyMessage = ""; $("#api-key").value = "";
    $("#api-key").removeAttribute("aria-invalid");
    paint();
    $("#question").focus();
  };
  $("#clear-key").onclick = () => {
    if (state.running) return;
    state.apiKey = ""; state.keyMessage = ""; $("#api-key").value = "";
    $("#api-key").removeAttribute("aria-invalid");
    paint();
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
  window.onhashchange = showView;
  paintDemo(); paintBenchmark(); paintCatalog();
  $("#catalog-search").oninput = paintCatalog;
  showView();
  paintPresets(); paint();
}

function showView(event) {
  const requested = location.hash.slice(1);
  const view = ["playground", "evaluation", "architecture"].includes(requested) ? requested : requested === "ask" ? "playground" : "demo";
  if (view !== "demo" && state.demo.running) stopDemo();
  $("#demo-view").hidden = view !== "demo";
  $("#ask-view").hidden = view !== "playground";
  $("#evaluation-view").hidden = view !== "evaluation";
  $("#architecture-view").hidden = view !== "architecture";
  if (view === "playground") loadModelMeta();
  const title = {demo: "Demo", playground: "Playground", evaluation: "Evaluation", architecture: "Architecture"}[view];
  document.title = `${title} · Grid Status Demo · GridRag`;
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
      <div class="demo-toolbar"><a class="artifact-link" href="#playground">Ask a custom question in the playground ↗</a><a class="artifact-link" href="#architecture">How GridRag works →</a></div>
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

const retrievalMethods = [["routed", "GridRag", "Routed schema"], ["vector-k21", "Qdrant", "Top 21 tables"], ["vector-hybrid-k25", "Qdrant → Decisions", "48 candidates → up to 25 tables"]];

function recordedMethods() {
  return retrievalMethods.filter(([method]) => state.benchmark?.runs?.some(row => row.method === method));
}

function recordedCases() {
  return (state.benchmark?.cases || []).filter(c => state.scoreScope === "all" || c.difficulty === state.scoreScope);
}

function paintBenchmark() {
  const b = state.benchmark;
  if (!b?.runs?.length) {
    $("#benchmark-results").innerHTML = '<h2>Recorded answers are unavailable.</h2><p class="footnote">Please reload to try again.</p>';
    $("#recorded-answers").innerHTML = "";
    return;
  }
  if (b.manifest.experiment !== "capability-30-v1") {
    $("#benchmark-results").innerHTML = '<h2>The 30-question results are being prepared.</h2><p>The new comparison uses three trials per question and approach, top-21 vector retrieval, and 48-candidate reranking with a 25-table budget. Complete recorded results will appear after the evaluation finishes.</p>';
    $("#recorded-answers").innerHTML = "";
    return;
  }
  const cases = recordedCases(), ids = new Set(cases.map(c => c.id)), rows = b.runs.filter(r => ids.has(r.case));
  const trials = [...new Set(rows.map(r => r.repeat))].sort((a,b) => a-b);
  const summaries = recordedMethods().map(([method, name, description]) => {
    const attempts = rows.filter(r => r.method === method), times = attempts.map(r => r.seconds).sort((a,b) => a-b);
    const n = times.length, priced = attempts.filter(r => Number.isFinite(r.cost_usd));
    return {name, description, count:n, correct:attempts.filter(r => r.correct).length, accuracy:n ? attempts.filter(r => r.correct).length/n : 0,
      trials:trials.map(repeat => {
        const group = attempts.filter(r => r.repeat === repeat);
        return {correct:group.filter(r => r.correct).length, count:group.length};
      }),
      median:n ? (times[Math.floor((n-1)/2)] + times[Math.ceil((n-1)/2)])/2 : null,
      recall: attempts.some(r => Number.isFinite(r.required_table_recall)) ? attempts.filter(r => Number.isFinite(r.required_table_recall)).reduce((sum,r) => sum+r.required_table_recall,0)/attempts.filter(r => Number.isFinite(r.required_table_recall)).length : null,
      cost:priced.length ? priced.reduce((sum,r) => sum + r.cost_usd,0)/priced.length : null};
  });
  const trialComparison = trials.length > 1 ? `<div class="comparison-scroll"><table class="comparison-table"><caption>Accuracy by trial · Every displayed question included</caption><thead><tr><th scope="col">Retrieval approach</th>${trials.map(repeat => `<th scope="col">Trial ${repeat+1}</th>`).join("")}</tr></thead><tbody>${summaries.map(r => `<tr><th scope="row">${r.name}</th>${r.trials.map(t => `<td>${t.correct}/${t.count} · ${t.count ? (100*t.correct/t.count).toFixed(1)+"%" : "—"}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
  $("#benchmark-results").innerHTML = `<div class="panel-head"><div><span class="eyebrow">RECORDED COMPARISON · ${esc(new Date(b.manifest.created_utc).toLocaleDateString("en-US", {timeZone:"America/New_York", year:"numeric", month:"short", day:"numeric"}))} ET</span><h2>The same questions. Different context.</h2></div><span class="badge">No API key needed</span></div><p class="footnote">${cases.length} ${cases.length === 1 ? "question" : "questions"} shown · ${b.manifest.repeats} recorded ${b.manifest.repeats === 1 ? "trial" : "trials"} per question and approach · ${rows.length} total attempts shown · SQL model: ${esc(b.manifest.models.sql)}. Qdrant uses ${esc(b.manifest.embedding_model)} embeddings. Entity context: ${b.manifest.grounding?.version === "schema-only-v1" ? "schema documentation only; no curated aliases" : esc(b.manifest.grounding?.version ?? "unreported")}. Vector k = ${esc(b.manifest.vector_top_k ?? 21)}; reranking starts from ${esc(b.manifest.hybrid?.dense_pool ?? 48)} semantic candidates plus keywords and retains up to ${esc(b.manifest.hybrid?.final_k ?? 25)} tables. Shared evaluation budget: ${esc(b.manifest.max_routed_tables ?? 25)} tables including references and 4,096 SQL output tokens. Second pass: OpenAI Decisions API (${esc(b.manifest.hybrid?.reranker ?? "unreported model")}). These are recorded runs, not fresh API calls.</p>${b.manifest.hybrid?.metadata?.length ? '<p class="footnote"><strong>Historical retrieval:</strong> This recorded run used demo-specific metadata rules and keyword region aliases that have since been removed. These scores do not evaluate the current generic retriever; a fresh benchmark is required.</p>' : ""}<div class="demo-options" role="group" aria-label="Question difficulty">${[["all","All difficulties"],["easy","Easy"],["medium","Medium"],["hard","Hard"],["very_hard","Very hard"]].map(([key,label]) => `<button type="button" data-score-scope="${key}" aria-pressed="${state.scoreScope === key}">${label}</button>`).join("")}</div><div class="comparison-scroll"><table class="comparison-table"><caption>Summary of the questions shown below · Every recorded attempt included</caption><thead><tr><th scope="col">Retrieval approach</th><th scope="col">Cumulative correct answers</th><th scope="col">Required-table recall</th><th scope="col">Median time</th><th scope="col">Est. cost / attempt</th></tr></thead><tbody>${summaries.map(r => `<tr><th scope="row">${r.name} · ${r.description}</th><td>${r.correct}/${r.count} · ${(r.accuracy*100).toFixed(1)}%</td><td>${r.recall == null ? "—" : `${(r.recall*100).toFixed(1)}%`}</td><td>${seconds(r.median)}</td><td>${r.cost == null ? "—" : `$${r.cost.toFixed(5)}`}</td></tr>`).join("")}</tbody></table></div>${trialComparison}<p class="footnote">Cumulative scores include every trial for the displayed questions, including failed attempts. Selecting a trial below changes the displayed evidence, not the cumulative score. Required-table recall includes reference tables. This suite changes the questions and context budget, so its scores are not directly comparable with earlier runs. ${esc(b.manifest.cost_basis)}. Costs are configured estimates, not billing records.</p><a class="artifact-link" href="/static/benchmark.json" download>Download answers, references, and evidence (JSON) ↓</a>`;
  $("#recorded-answers").innerHTML = `<div class="recorded-section-heading"><span class="eyebrow">THE ACTUAL ANSWERS</span><h2>Read each approach’s response.</h2><p>Each question shows the recorded answers from every approach, including failures. ${b.manifest.repeats > 1 ? "Use Trial 1, Trial 2, and Trial 3 to inspect individual attempts. Cumulative scores include all trials." : "One trial is available."} Inspect the answer, selected tables, SQL, and returned data beside the independent reference.</p></div>` + cases.map(c => `<article class="panel recorded-question" id="recorded-${esc(c.id)}"></article>`).join("");
  cases.forEach(paintRecordedQuestion);
  document.querySelectorAll("[data-score-scope]").forEach(button => button.onclick = () => {
    state.scoreScope = button.dataset.scoreScope; paintBenchmark();
    document.querySelector(`[data-score-scope="${state.scoreScope}"]`).focus({preventScroll:true});
  });
}

function paintRecordedQuestion(c) {
  const b = state.benchmark;
  const trials = [...new Set(b.runs.filter(r => r.case === c.id).map(r => r.repeat))].sort((a,b) => a-b);
  const preferredTrial = state.recordedTrials.get(c.id);
  const selected = trials.includes(preferredTrial) ? preferredTrial : trials[0];
  const difficulty = {easy: "Easy", medium: "Medium", hard: "Hard", very_hard: "Very hard"}[c.difficulty] || "Unrated";
  const target = document.getElementById(`recorded-${c.id}`);
  target.innerHTML = `<div class="recorded-question-head"><div><span class="eyebrow">${esc(difficulty.toUpperCase())} · ${c.type === "table" ? "TABLE RESULT" : "SCALAR RESULT"}</span><h3>${esc(c.question)}</h3>${c.expected != null ? `<p class="footnote">Warehouse reference: <strong>${number(c.expected)} ${esc(c.unit)}</strong></p>` : ""}${c.reference_csv ? `<details class="evidence-item"><summary>Expected result · independent reference</summary><pre>${esc(c.reference_csv)}</pre></details>` : ""}</div>${trials.length > 1 ? `<div class="demo-options recorded-trials" role="group" aria-label="Recorded trials for ${esc(c.question)}">${trials.map(repeat => `<button type="button" data-recorded-case="${esc(c.id)}" data-recorded-trial="${repeat}" aria-pressed="${repeat === selected}">Trial ${repeat+1}</button>`).join("")}</div>` : ""}</div><div class="recorded-answer-grid">${recordedMethods().map(([method,name,description]) => {
    const row = b.runs.find(r => r.case === c.id && r.method === method && r.repeat === selected);
    if (!row) return `<section class="recorded-method"><h4>${name} · ${description}</h4><p>No recorded answer for this trial.</p></section>`;
    const attempts = b.runs.filter(r => r.case === c.id && r.method === method);
    const cumulative = attempts.length > 1 ? `<p class="footnote">Cumulative: ${attempts.filter(r => r.correct).length}/${attempts.length} correct across all trials.</p>` : "";
    const verdict = row.state === "failed" ? "Execution failed" : row.correct ? "Matches reference" : "Needs review";
    return `<section class="recorded-method" aria-label="${esc(name)} ${esc(description)} answer"><div class="recorded-method-head"><div><h4>${name}</h4><span>${description}</span></div><span class="badge ${row.correct ? "good" : "warn"}">${verdict}</span></div>${cumulative}<div class="answer-text recorded-answer">${md(row.answer || "No answer was returned in this recorded attempt.")}</div><div class="recorded-run-metrics"><span>${seconds(row.seconds)}</span><span>${row.cost_usd == null ? "Cost unreported" : `$${row.cost_usd.toFixed(5)}`}</span><span>${row.input_tokens == null ? "" : `${number(row.input_tokens)} input tokens`}</span></div><details class="evidence-item"><summary>Selected tables (${row.tables?.length || 0})</summary><div class="recorded-tables">${(row.tables || []).map(table => `<code>${esc(table)}</code>`).join("") || '<p class="footnote">No schema was delivered for this response.</p>'}</div></details>${row.retrieval ? `<details class="evidence-item"><summary>Hybrid retrieval evidence</summary><p class="footnote">${row.retrieval.dense_candidates?.length || 0} semantic candidates · ${row.retrieval.shortlist?.length || 0} shortlisted tables · second pass: ${esc(row.retrieval.reranker_endpoint ?? row.retrieval.reranker)}${row.retrieval.reranker_model ? ` · ${esc(row.retrieval.reranker_model)}` : ""}. Scores are model relevance judgments.</p><div class="recorded-tables">${(row.retrieval.shortlist || []).map(table => `<code>${esc(table)} · ${row.retrieval.rerank_scores?.[table] == null ? "unscored" : (row.retrieval.rerank_scores[table]*100).toFixed(1)+"%"}</code>`).join("")}</div></details>` : ""}<details class="evidence-item"><summary>SQL &amp; evidence (${row.queries?.length || 0} ${row.queries?.length === 1 ? "query" : "queries"})</summary>${(row.queries || []).map((query,i) => `<div class="recorded-query"><strong>Query ${i+1}</strong><pre>${esc(query.query)}</pre>${query.csv ? `<b>Returned data</b><pre>${esc(query.csv)}</pre>` : ""}${query.error ? `<p class="error">${esc(query.error)}</p>` : ""}${query.truncated ? `<p class="error">${esc(query.truncated)}</p>` : ""}</div>`).join("") || '<p class="footnote">No SQL was executed.</p>'}</details></section>`;
  }).join("")}</div>`;
  target.querySelectorAll("[data-recorded-trial]").forEach(button => button.onclick = () => {
    state.recordedTrials.set(c.id, Number(button.dataset.recordedTrial));
    paintRecordedQuestion(c);
    target.querySelector(`[data-recorded-trial="${state.recordedTrials.get(c.id)}"]`).focus({preventScroll:true});
  });
}

function paintPresets() {
  const p = preset();
  document.querySelectorAll("[data-preset]").forEach(button => {
    button.setAttribute("aria-pressed", String(state.meta.presets[Number(button.dataset.preset)] === p));
  });
}

function paintKey() {
  const busy = state.running;
  $("#api-key").disabled = busy;
  $("#save-key").disabled = busy;
  $("#save-key").textContent = state.apiKey ? "Replace key" : "Use key";
  $("#clear-key").hidden = !state.apiKey;
  $("#clear-key").disabled = busy;
  $("#api-key").placeholder = state.apiKey ? "Key added for this tab" : "sk-…";
  $("#api-key-status").textContent = state.keyMessage || (state.apiKey ? "Key added for this tab. Reloading or closing this tab removes it." : (state.meta.model_ready && !state.meta.requires_api_key) ? "Using the local server’s configured key. You can use your own instead." : "Add your key above to ask a live question.");
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
    ["Select schema", route ? `${selected.length} of ${total} tables selected. ${isDemo ? "Tables used by the verified reference query." : "Relevant columns, structural fields, and referenced tables retained."}` :
      "Select relevant tables and columns from the documented catalog.", Boolean(route)],
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
      ${i === 1 && route ? `<meter class="schema-meter" min="0" max="${total}" value="${selected.length}" aria-label="${selected.length} of ${total} catalog tables selected">${selected.length} of ${total}</meter>
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
  $("#ask-button").disabled = state.running || !$("#question").value.trim();
  $("#ask-button").textContent = state.running ? "Running…" : modelReady() ? "Ask the grid →" : "Connect key to ask →";
  $("#answer").setAttribute("aria-busy", String(state.running));
  $("#question").disabled = state.running;
  document.querySelectorAll("[data-preset], [data-question]").forEach(b => { b.disabled = state.running; });
}

async function ask() {
  const question = $("#question").value.trim();
  if (!question || state.running) return;
  if (!modelReady()) {
    $("#api-key").focus();
    return;
  }
  const selectedPreset = preset();
  state.running = true; state.result = null; state.error = ""; state.progress = {}; paint();
  $("#answer-heading").focus({preventScroll: true});
  $("#ask-view .workspace").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
  try {
    const response = await fetch("/api/ask", {
      method: "POST", headers: requestHeaders(), body: JSON.stringify({ question }),
    });
    if (!response.ok) {
      const fallback = response.status === 429 ? "Too many requests. Please wait a minute and try again." : `Request failed (HTTP ${response.status}). Please try again.`;
      const error = await response.json().catch(() => null);
      throw new Error(error?.error || fallback);
    }
    for await (const event of readJsonEvents(response.body)) {
      applyAnswerEvent(event, selectedPreset);
      if (state.result) break;
    }
    if (!state.result) throw new Error("The connection ended before the answer arrived. Please retry.");

  } catch (error) {
    state.error = error.message || "Could not reach the server. Please retry.";
  } finally { state.running = false; paint(); }
}

function applyAnswerEvent(event, selectedPreset) {
  if (event.type === "error") throw new Error(event.error);
  if (event.type === "done") {
    state.result = event.result;
    if (selectedPreset) state.runs.set(selectedPreset.id, event.result);
    return;
  }
  if (event.type !== "progress") return;
  if (event.answer_delta !== undefined) {
    state.progress.answer_text = (state.progress.answer_text || "") + event.answer_delta;
    $("#answer").innerHTML = `<div class="answer-text">${md(state.progress.answer_text)}</div>`;
    return;
  }
  Object.assign(state.progress, event);
  paint();
}

function loadModelMeta() {
  if (modelMetaRequest) return;
  modelMetaRequest = fetch("/api/meta").then(response => {
    if (!response.ok) throw new Error("Live settings unavailable");
    return response.json();
  }).then(meta => {
    state.meta = {...state.meta, ...meta};
    $("#model-access-note").textContent = `Models: ${meta.models.decisions} · ${meta.models.answer}. Requires Decisions and Responses API access.`;
    paintKey(); paint();
  }).catch(() => {
    modelMetaRequest = null;
    $("#model-access-note").textContent = "Live model settings could not be checked. Reload to retry.";
  });
}

async function boot() {
  try {
    // The default demo and recorded comparison are static and require no provider key.
    const response = await fetch("/static/demo.json");
    if (!response.ok) throw new Error("The demo assets are unavailable. Please reload in a moment.");
    state.meta = await response.json();
    render();
    fetch("/static/benchmark.json").then(r => r.ok ? r.json() : null).then(data => { state.benchmark = data; paintBenchmark(); }).catch(() => {});
  } catch (error) {
    $("#main").innerHTML = `<section class="panel boot-error"><h1>Could not load the demo</h1><p>${esc(error.message)}</p><button id="retry" type="button">Retry</button></section>`;
    $("#retry").onclick = boot;
  }
}
boot();
