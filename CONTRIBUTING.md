# Contributing

Use Python 3.11–3.13 and the checked-in uv lockfile. Keep changes focused and
include the motivation and relevant verification in the pull request.

```sh
uv sync --locked
uv run python -m gridrag.warehouse.build
uv run python -m scripts.public_assets
uv run python -m unittest discover -s tests
node --check app/static/app.js
uv run python -m scripts.security_audit --history
```

Offline tests must never make provider calls. Live evaluation requires explicit
opt-in and a locally configured key. Keep questions and expected SQL independent
of the retriever. Do not tune retrieval settings on published evaluation cases,
drop failed attempts, or present model token estimates as complete operating cost.

Document tables with their grain, keys, units, time semantics and coverage. Register
new tables explicitly in the catalog. Keep SQL guard changes separate and include
regression cases for attempted bypasses. All committed data must be fictional.
