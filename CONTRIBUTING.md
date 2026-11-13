# Contributing

Use Python 3.11–3.13 and the checked-in `uv.lock`:

```sh
uv sync --locked
uv run python -m gridrag.warehouse.build
uv run python -m scripts.public_assets
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests
node --check app/static/app.js
node --check app/static/stream.js
node --test tests/test_*.js
uv run python -m scripts.security_audit --history
uv run python -m scripts.public_release
```

These checks run without provider requests. The live regression suite requires
explicit opt-in with `GRIDRAG_LIVE_TESTS=1` and a configured key; it incurs charges.
See [the benchmark specification](benchmarks/README.md) for optional retrieval
dependencies and controlled comparisons. Recorded results must come from a
complete live report; do not edit their outcomes manually.

Run `uv run ruff format .` to format Python and `uv run ruff check . --fix` to
apply safe lint fixes. CI checks formatting, lint, tests, release artifacts and
secret scanning on Python 3.11, 3.12 and 3.13.

Keep provider access in `gridrag/llm.py`, orchestration in `gridrag/answer.py`,
schema selection in `gridrag/route.py`, tool execution in `gridrag/sql/agent.py`
and independent SQL enforcement in `gridrag/db.py`. Catalog metadata and optional
entity vocabulary belong to the supplied catalog. The HTTP layer handles request
validation and response framing; it must not weaken the SQL boundary.

Add regression coverage for changed behavior and failure paths. Preserve
deterministic fixtures, explicit resource budgets, request-scoped visitor clients
and redacted logs. Never commit local credentials, databases, caches, deployment
metadata or private historical exports. Build the warehouse before starting the
server, and restart the server after replacing its fixed snapshot.

For a deployment smoke test, run `uv run python -m scripts.vercel_build` and verify
the approved files under `public/`. Publishing to a hosting service is a separate
operation from building the artifacts.
