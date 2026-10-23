# Schema-driven routing

The router scores each documented table in one Decisions request. It retains
selected tables whole and follows their foreign-key references recursively.
Missing decisions retain the affected tables; the existing table budget asks
for clarification when the selection is too broad. The database still enforces
read-only queries and the selected-table allowlist.

New products belong in the warehouse schema with their measures, units, grain,
coverage and references. No family predicate, ISO/product matrix or column
classifier needs updating. The catalog currently comes from `schema_text()`;
adding a table only to the database does not register it with the router.

The SQL prompt supplies general analytical guidance. Product-specific semantics
remain with the schema, and the model can query actual values and coverage.
Selected columns are never hidden, so a later calculation can use a field the
router did not anticipate.

This trades several small classification calls for one larger catalog request.
Routing cost grows with the catalog, and similar tables may still confuse the
model. The probability cutoff and table budget remain heuristics. For a much
larger warehouse, catalog retrieval or on-demand schema discovery would be the
next approach to evaluate, with recall measured before restricting SQL access.

Tests retain database safety, numerical output, time-zone and aggregate
invariants, failure handling, and representative live answer checks. Routing
unit tests cover unfamiliar schema and recursive references, uncertainty and
the context budget. Tests of removed routing stages and synthetic fixture
counts were removed. The route record now exposes `tables`,
`table_probabilities` and `fallback`; the CLI uses that shape.

Offline tests pass. Live-model accuracy and latency must still be validated:
the attempted run could not connect, and network escalation was denied. Run
`python -m unittest discover -s tests -p 'test_live.py'` in an environment
approved to send the synthetic warehouse context to the configured model API.
