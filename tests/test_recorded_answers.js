const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function page() {
  const elements = new Map();
  const scopes = ["all", "easy", "medium", "hard", "very_hard"].map(scope => ({dataset: {scoreScope: scope}}));
  const categories = ["all", "scope", "joins"].map(category => ({dataset: {scoreCategory: category}}));
  const element = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML: "", focus() {},
      querySelectorAll(selector) {
        if (selector !== "[data-recorded-trial]") return [];
        this.trialButtons ??= new Map();
        return [...this.innerHTML.matchAll(/data-recorded-trial="(\d+)"/g)].map(([, trial]) => {
          if (!this.trialButtons.has(trial)) this.trialButtons.set(trial, {dataset: {recordedTrial:trial}});
          return this.trialButtons.get(trial);
        });
      }, querySelector() { return {focus() {}}; }});
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {querySelector: element, getElementById: element,
      querySelectorAll: selector => selector === "[data-score-scope]" ? scopes : selector === "[data-score-category]" ? categories : []},
    marked: {parse: value => value}, DOMPurify: {sanitize: value => value},
    fetch() { throw new Error("Recorded answers must not request a model"); },
  });
  const script = fs.readFileSync("app/static/app.js", "utf8").replace(/boot\(\);\s*$/, "");
  vm.runInContext(script + "\nglobalThis.page = {state, paintBenchmark, paintRecordedQuestion};", context);
  const methods = ["routed", "vector-hybrid-p20"];
  const cases = [
    {id: "easy", type: "scalar", difficulty: "easy", category: "scope", question: "Easy question", concept: "Scope <script>unsafe</script>", expected: 12.5, unit: "MW"},
    {id: "medium", type: "scalar", difficulty: "medium", category: "joins", question: "Medium question"},
    {id: "hard", type: "scalar", difficulty: "hard", question: "Hard question"},
    {id: "all_iso_prices", type: "table", difficulty: "very_hard", question: "Compare all regions",
      reference_csv: "iso_code,product,average_energy_price\n" + Array.from({length: 21}, (_, i) =>
        `${i === 0 ? "<script>unsafe</script>" : "ISO"},product_${i},12.5\n`).join("")},
  ];
  context.page.state.benchmark = {
    manifest: {experiment: "decisions-vs-reranker-30-v3", created_utc: "2026-11-13T02:58:02Z", repeats: 1,
      models: {sql: "test"}, embedding_model: "test", cost_basis: "test",
      hybrid: {catalog_tables: 65, candidate_percent: 20, candidate_top_k: 13, dense_pool: 13, keyword_pool: 13, final_k: 13, reranker: "test-reranker", reranker_endpoint: "/v1/decisions"}, max_routed_tables: 25},
    cases,
    runs: cases.flatMap(c => methods.map(method => ({
      case: c.id, method, repeat: 0, correct: c.id !== "medium",
      state: c.id === "medium" ? "failed" : "answered", seconds: 2,
      cost_usd: .001, required_table_recall: 1,
      answer: `${method} single answer`, tables: [],
      queries: [{query: "SELECT '<script>unsafe</script>'", csv: "answer\n1\n"}],
    }))),
  };
  return {api: context.page, element, scopes, categories};
}

test("difficulty filters recompute all methods' scores and retain failures", () => {
  const {api, element, scopes} = page();
  api.paintBenchmark();
  const summary = () => element("#benchmark-results").innerHTML;
  assert.match(summary(), /4 questions shown · 1 recorded trial per question and approach · 8 total attempts shown/);
  assert.equal((summary().match(/<td>3\/4 · 75\.0%<\/td>/g) || []).length, 2);
  assert.doesNotMatch(summary(), /Top 21 tables|Vector k =/);
  assert.match(summary(), /Qdrant → Decisions/);
  assert.match(summary(), /OpenAI Decisions API \(test-reranker\)/);
  assert.match(summary(), /20% catalog cap → 13 candidates/);
  assert.match(summary(), /25 tables including references and 4,096 SQL output tokens/);
  assert.match(summary(), /Nov 12, 2026/);
  for (const [index, difficulty] of ["easy", "medium", "hard", "very_hard"].entries()) {
    scopes[index+1].onclick();
    assert.match(summary(), /1 question shown/);
    const expected = difficulty === "medium" ? "0.0" : "100.0";
    assert.match(summary(), new RegExp(`<td>${difficulty === "medium" ? 0 : 1}/1 · ${expected.replace(".", "\\.")}%<\\/td>`));
    const id = difficulty === "very_hard" ? "all_iso_prices" : difficulty;
    assert.match(element("#recorded-answers").innerHTML, new RegExp(`id="recorded-${id}"`));
    assert.doesNotMatch(summary(), /NaN/);
  }
  scopes[0].onclick();
  assert.match(summary(), /4 questions shown/);
});

test("refreshed GridRag evidence uses the original comparison layout and controls", () => {
  const {api, element} = page();
  api.state.benchmark = JSON.parse(fs.readFileSync("app/static/benchmark.json", "utf8"));
  api.paintBenchmark();
  const html = element("#benchmark-results").innerHTML;
  assert.match(html, /86\/90 · 95\.6%/);
  assert.match(html, /59\/90 · 65\.6%/);
  assert.match(html, /\$0\.00247/);
  assert.match(html, /Metadata filter → selected columns/);
  assert.match(html, /Qdrant was not rerun/);
  assert.match(html, /data-score-scope/);
  assert.match(html, /data-score-category/);
  assert.match(element("recorded-annual_system_peak").innerHTML, /data-recorded-trial/);
  const source = fs.readFileSync("app/static/app.js", "utf8");
  assert.doesNotMatch(source, /metadata-results|data-metadata-suite|paintMetadataBenchmark|Earlier vector comparison/);
});

test("one attempt shows both answers without trial controls and escapes evidence", () => {
  const {api, element} = page();
  api.paintBenchmark();
  const scalar = element("recorded-easy").innerHTML;
  for (const method of ["routed", "vector-hybrid-p20"])
    assert.match(scalar, new RegExp(`${method} single answer`));
  assert.match(scalar, /EASY · SCALAR RESULT/);
  assert.match(scalar, /Warehouse reference:/);
  assert.match(scalar, /Tests:<\/strong> Scope &lt;script&gt;unsafe/);
  assert.match(scalar, /12\.5 MW/);
  assert.doesNotMatch(scalar, /data-recorded-trial|Trial 1/);
  assert.match(scalar, /&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.doesNotMatch(scalar, /<script>/);
  const table = element("recorded-all_iso_prices").innerHTML;
  assert.match(table, /VERY HARD · TABLE RESULT/);
  assert.match(table, /<details class="evidence-item"><summary>Expected result · independent reference/);
  assert.match(table, /product_20,12\.5/);
  assert.match(table, /&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.doesNotMatch(table, /Expected behavior|data-recorded-trial|<script>/);
  assert.equal((table.match(/Matches reference/g) || []).length, 2);
});

test("three trials contribute to cumulative scores while selectors change only the evidence", () => {
  const {api, element, scopes} = page();
  const b = api.state.benchmark, original = b.runs;
  b.manifest.repeats = 3;
  b.runs = [0,1,2].flatMap(repeat => original.map(row => ({...row, repeat,
    correct: row.case === "easy" ? repeat !== 1 : row.case === "medium" ? false : repeat === 0,
    answer: `${row.method} trial ${repeat+1} answer`,
  })));
  api.paintBenchmark();
  const summary = element("#benchmark-results").innerHTML;
  assert.match(summary, /3 recorded trials per question and approach · 24 total attempts shown/);
  assert.equal((summary.match(/<td>4\/12 · 33\.3%<\/td>/g) || []).length, 2);
  assert.match(summary, /Accuracy by trial/);
  for (const score of ["3/4 · 75.0%", "0/4 · 0.0%", "1/4 · 25.0%"])
    assert.equal(summary.split(`<td>${score}</td>`).length - 1, 2);
  const question = element("recorded-easy");
  assert.equal((question.innerHTML.match(/Cumulative: 2\/3 correct across all trials/g) || []).length, 2);
  for (const trial of [0,1,2]) {
    const buttons = question.querySelectorAll("[data-recorded-trial]");
    assert.equal(buttons.length, 3);
    buttons[trial].onclick();
    assert.equal(api.state.recordedTrials.get("easy"), trial);
    assert.match(question.innerHTML, new RegExp(`routed trial ${trial+1} answer`));
    assert.equal((question.innerHTML.match(/Cumulative: 2\/3 correct across all trials/g) || []).length, 2);
    assert.equal(element("#benchmark-results").innerHTML, summary);
  }
  scopes[1].onclick();
  const filtered = element("#benchmark-results").innerHTML;
  assert.match(filtered, /1 question shown · 3 recorded trials per question and approach · 6 total attempts shown/);
  assert.equal((filtered.match(/<td>2\/3 · 66\.7%<\/td>/g) || []).length, 2);
  assert.match(element("recorded-easy").innerHTML, /routed trial 3 answer/);
});

test("earlier data cannot appear as results of the new capability suite", () => {
  const {api, element} = page();
  delete api.state.benchmark.manifest.experiment;
  api.paintBenchmark();
  assert.match(element("#benchmark-results").innerHTML, /30-question results are being prepared/);
  assert.doesNotMatch(element("#benchmark-results").innerHTML, /75\.0%|before-grounding/);
  assert.equal(element("#recorded-answers").innerHTML, "");
});

test("demo-specific recorded retrieval is labeled historical without changing its results", () => {
  const {api, element} = page();
  api.state.benchmark.manifest.hybrid.metadata = ["region", "measure", "cadence", "coverage"];
  api.paintBenchmark();
  const summary = element("#benchmark-results").innerHTML;
  assert.match(summary, /Historical retrieval:/);
  assert.match(summary, /These scores do not evaluate the current generic retriever/);
  assert.equal((summary.match(/<td>3\/4 · 75\.0%<\/td>/g) || []).length, 2);
  delete api.state.benchmark.manifest.hybrid.metadata;
  api.state.benchmark.manifest.hybrid.fusion_version = "semantic-bm25-v1";
  api.paintBenchmark();
  assert.doesNotMatch(element("#benchmark-results").innerHTML, /Historical retrieval:/);
});

test("recorded ISO vocabulary is identified as shared SQL context", () => {
  const {api, element} = page();
  api.state.benchmark.manifest.grounding = {version:"iso-entities-v1", entries:7, shared_by_all_methods:true};
  api.paintBenchmark();
  assert.match(element("#benchmark-results").innerHTML,
    /seven ISO entity mappings shared by all approaches; SQL generation only/);
  assert.doesNotMatch(element("#benchmark-results").innerHTML, /no curated aliases/);
});


test("candidate omissions and selected columns stay inspectable and escaped", () => {
  const {api, element} = page();
  const row = api.state.benchmark.runs.find(r => r.case === "easy" && r.method === "vector-hybrid-p20");
  row.candidate_table_recall = .5;
  row.candidate_missing_tables = ["core.<script>missing</script>"];
  row.columns = {"core.sample": ["iso_id", "<script>value</script>"]};
  row.selected_columns = 2;
  row.retrieval = {shortlist: ["core.sample"], rerank_scores: {"core.sample": .9}};
  api.paintBenchmark();
  const html = element("recorded-easy").innerHTML;
  assert.match(html, /Selected columns \(2\)/);
  assert.match(html, /iso_id, &lt;script&gt;value/);
  assert.match(html, /Required tables missing from the candidate pool: core.&lt;script&gt;missing/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(element("#benchmark-results").innerHTML, /Candidate-table recall/);
});


test("capability and difficulty filters compose and can recover an empty selection", () => {
  const {api, element, scopes, categories} = page();
  api.paintBenchmark();
  categories[1].onclick();
  assert.match(element("#benchmark-results").innerHTML, /1 question shown/);
  assert.match(element("#recorded-answers").innerHTML, /recorded-easy/);
  scopes[2].onclick();
  assert.match(element("#benchmark-results").innerHTML, /0 questions shown/);
  assert.doesNotMatch(element("#benchmark-results").innerHTML, /NaN/);
  categories[0].onclick();
  assert.match(element("#benchmark-results").innerHTML, /1 question shown/);
  assert.match(element("#recorded-answers").innerHTML, /recorded-medium/);
});

test("fixed combined cap and broad-task limitation remain visible with failed attempts counted", () => {
  const {api, element} = page();
  const row = api.state.benchmark.runs.find(r => r.case === "all_iso_prices" && r.method === "vector-hybrid-p20");
  Object.assign(row, {correct:false, required_seed_tables:21, candidate_budget_shortfall:8,
    retrieval:{candidate_policy:{candidate_top_k:13}, shortlist:[], rerank_scores:{}}});
  api.paintBenchmark();
  const summary = element("#benchmark-results").innerHTML;
  assert.match(summary, /20% of 65 tables = 13 candidates/);
  assert.match(summary, /combined dense and keyword shortlist/);
  assert.match(summary, /does not establish production-scale performance/);
  assert.match(summary, /Reference exceeds candidate cap/);
  assert.match(summary, /<td>2\/4 · 50\.0%<\/td>/);
  const answer = element("recorded-all_iso_prices").innerHTML;
  assert.match(answer, /Candidate cap limitation:/);
  assert.match(answer, /21 independent source tables, exceeding the 13-candidate budget/);
  assert.match(answer, /remains included in cumulative accuracy/);
});
