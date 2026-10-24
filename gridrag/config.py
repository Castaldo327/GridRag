"""Paths, the API key and model settings."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
DB = ROOT / "data" / "warehouse.duckdb"

DECISIONS_MODEL = os.environ.get("GRIDRAG_DECISIONS_MODEL", "gpt-6-luna")
ANSWER_MODEL = os.environ.get("GRIDRAG_ANSWER_MODEL", "gpt-6-luna")
ANSWER_REASONING = "none"
ANSWER_MAX_OUTPUT_TOKENS = 1600
CALL_TIMEOUT_S = 30
API_MAX_RETRIES = 1  # explicit SDK retry budget, separate from SQL repair rounds

# Illustrative demo rates per million tokens, not a verified billing tariff.
# Update these alongside model changes before using cost estimates operationally.
PRICES = {
    "decisions": {"input": 0.10, "cached_input": 0.01, "output": 0.0},
    "responses": {"input": 0.10, "cached_input": 0.01, "output": 0.50},
}

MAX_QUESTION_CHARS = 2000
GATE_MIN_RELEVANCE = 0.3
GATE_MAX_MALICIOUS = 0.7
ROUTE_MIN_PROBABILITY = 0.2

MAX_ROUTED_TABLES = 12  # largest schema slice SQL may receive, dimensions included; broader asks to narrow
SQL_MAX_ROUNDS = 5
SQL_MAX_ROWS = 500
SQL_MAX_CHARS = 20000
SQL_MAX_RESULT_BYTES = 64000
SQL_TIMEOUT_S = 10
DB_MEMORY_LIMIT = "256MB"
DB_THREADS = 2


def load_env() -> dict[str, str]:
    """Keys from .env, overridden by the process environment. OPENAI_API_KEY is accepted as an
    alias for OPEN_AI_KEY."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    # Resolve aliases within each source first, so either exported spelling wins
    # over either spelling in the local file.
    key = (os.environ.get("OPEN_AI_KEY") or os.environ.get("OPENAI_API_KEY")
           or env.get("OPEN_AI_KEY") or env.get("OPENAI_API_KEY"))
    env.update(os.environ)
    if key:
        env["OPEN_AI_KEY"] = key
    return env


def require_key(name: str) -> str:
    if value := load_env().get(name):
        return value
    raise RuntimeError(f"{name} is not set; put it in .env or export it")
