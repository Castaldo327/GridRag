const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function page() {
  const elements = new Map();
  const scopes = ["all", "easy", "medium", "hard", "very_hard"].map(scope => ({dataset: {scoreScope: scope}}));
  const element = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML: "", focus() {},
      querySelectorAll() { return []; }, querySelector() { return {focus() {}}; }});
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {querySelector: element, getElementById: element,
      querySelectorAll: selector => selector === "[data-score-scope]" ? scopes : []},
    marked: {parse: value => value}, DOMPurify: {sanitize: value => value},
    fetch() { throw new Error("Recorded answers must not request a model"); },
  });
  const script = fs.readFileSync("app/static/app.js", "utf8").replace(/boot\(\);\s*$/, "");
  vm.runInContext(script + "\nglobalThis.page = {state, paintBenchmark, paintRecordedQuestion};", context);
  context.page.state.meta = {evaluation_cases: []};
  const methods = ["routed", "vector-k21", "vector-hybrid-k25"];
  const cases = [
    {id: "easy", type: "scalar", difficulty: "easy", question: "Easy question", expected: 12.5, unit: "MW"},
    {id: "medium", type: "scalar", difficulty: "medium", question: "Medium question"},
    {id: "hard", type: "scalar", difficulty: "hard", question: "Hard question"},
    {id: "all_iso_prices", type: "table", difficulty: "very_hard", question: "Compare all regions",
      reference_csv: "iso_code,product,average_energy_price\n" + Array.from({length: 21}, (_, i) =>
        `${i === 0 ? "<script>unsafe</script>" : "ISO"},product_${i},12.5\n`).join("")},
  ];
  context.page.state.benchmark = {
    manifest: {experiment: "capability-30-v1", created_utc: "2026-11-13T02:58:02Z", repeats: 1,
      models: {sql: "test"}, embedding_model: "test", cost_basis: "test", vector_top_k: 21,
      hybrid: {dense_pool: 48, final_k: 25, reranker: "test-reranker", reranker_endpoint: "/v1/decisions"}, max_routed_tables: 25},
    cases,
    runs: cases.flatMap(c => methods.map(method => ({
      case: c.id, method, repeat: 0, correct: c.id !== "medium",
      state: c.id === "medium" ? "failed" : "answered", seconds: 2,
      cost_usd: .001, required_table_recall: 1,
      answer: `${method} single answer`, tables: [],
      queries: [{query: "SELECT '<script>unsafe</script>'", csv: "answer\n1\n"}],
    }))),
  };
  return {api: context.page, element, scopes};
}

test("difficulty filters recompute all methods' scores and retain failures", () => {
  const {api, element, scopes} = page();
  api.paintBenchmark();
  const summary = () => element("#benchmark-results").innerHTML;
  assert.match(summary(), /4 questions shown · 1 recorded attempt per approach/);
  assert.equal((summary().match(/<td>75\.0%<\/td>/g) || []).length, 3);
  assert.match(summary(), /Top 21 tables/);
  assert.match(summary(), /Qdrant → Decisions/);
  assert.match(summary(), /OpenAI Decisions API \(test-reranker\)/);
  assert.match(summary(), /48 candidates → up to 25 tables/);
  assert.match(summary(), /25 tables including references and 4,096 SQL output tokens/);
  assert.match(summary(), /Nov 12, 2026/);
  for (const [index, difficulty] of ["easy", "medium", "hard", "very_hard"].entries()) {
    scopes[index+1].onclick();
    assert.match(summary(), /1 question shown/);
    const expected = difficulty === "medium" ? "0.0" : "100.0";
    assert.match(summary(), new RegExp(`<td>${expected.replace(".", "\\.")}%<\\/td>`));
    const id = difficulty === "very_hard" ? "all_iso_prices" : difficulty;
    assert.match(element("#recorded-answers").innerHTML, new RegExp(`id="recorded-${id}"`));
    assert.doesNotMatch(summary(), /NaN/);
  }
  scopes[0].onclick();
  assert.match(summary(), /4 questions shown/);
});

test("one attempt shows all three answers without trial controls and escapes evidence", () => {
  const {api, element} = page();
  api.paintBenchmark();
  const scalar = element("recorded-easy").innerHTML;
  for (const method of ["routed", "vector-k21", "vector-hybrid-k25"])
    assert.match(scalar, new RegExp(`${method} single answer`));
  assert.match(scalar, /EASY · SCALAR RESULT/);
  assert.match(scalar, /Warehouse reference:/);
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
  assert.equal((table.match(/Matches reference/g) || []).length, 3);
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
  assert.equal((summary.match(/<td>75\.0%<\/td>/g) || []).length, 3);
  delete api.state.benchmark.manifest.hybrid.metadata;
  api.state.benchmark.manifest.hybrid.fusion_version = "semantic-bm25-v1";
  api.paintBenchmark();
  assert.doesNotMatch(element("#benchmark-results").innerHTML, /Historical retrieval:/);
});
