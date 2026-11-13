const assert = require("node:assert/strict");
const {test} = require("node:test");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const vm = require("node:vm");

const {readJsonEvents} = vm.runInNewContext(
  readFileSync(join(__dirname, "../app/static/stream.js"), "utf8") + ";({readJsonEvents})",
  {TextDecoder},
);

function stream(chunks, onCancel = () => {}) {
  return new ReadableStream({
    start(controller) {
      chunks.forEach(chunk => controller.enqueue(chunk));
      controller.close();
    },
    cancel: onCancel,
  });
}

async function collect(body) {
  const events = [];
  for await (const event of readJsonEvents(body)) events.push(event);
  return JSON.parse(JSON.stringify(events));
}

test("preserves split UTF-8, blank lines, and the final event without a newline", async () => {
  const encoded = new TextEncoder().encode('\n{"type":"progress","answer_delta":"MW → MWh"}\r\n{"type":"done"}');
  const chunks = Array.from(encoded, byte => Uint8Array.of(byte));
  const body = stream(chunks);
  assert.deepEqual(await collect(body), [
    {type: "progress", answer_delta: "MW → MWh"}, {type: "done"},
  ]);
  assert.equal(body.locked, false);
});

test("malformed events propagate and release the reader", async () => {
  const body = stream([new TextEncoder().encode('{broken}\n')]);
  await assert.rejects(collect(body), {name: "SyntaxError"});
  assert.equal(body.locked, false);
});

test("stopping at the done event cancels an unfinished response", async () => {
  let cancelled = false;
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"type":"done"}\n'));
    },
    cancel() { cancelled = true; },
  });
  for await (const event of readJsonEvents(body)) {
    assert.equal(event.type, "done");
    break;
  }
  assert.equal(cancelled, true);
  assert.equal(body.locked, false);
});

test("missing or interrupted response streams fail explicitly", async () => {
  await assert.rejects(collect(null), /no response stream/);
  const body = new ReadableStream({start(controller) { controller.error(new Error("connection lost")); }});
  await assert.rejects(collect(body), /connection lost/);
  assert.equal(body.locked, false);
});
