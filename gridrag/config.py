"""One frozen Settings object: paths, the API key, models, cost rates, thresholds and budgets.

settings is loaded once, from .env overridden by the process environment. Modules read config.settings when they
need a value, so tests and experiments can swap in dataclasses.replace(config.settings, ...) in one place.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


@dataclass(frozen=True)
class Rates:
    """USD per million tokens."""

    input: float
    cached_input: float
    output: float


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "data" / "warehouse.duckdb"
    openai_api_key: str | None = field(default=None, repr=False)
    decisions_model: str = "gpt-6-luna"
    answer_model: str = "gpt-6-luna"
    answer_reasoning: str = "none"
    answer_max_output_tokens: int = 1600
    call_timeout_s: float = 30
    api_max_retries: int = 1  # explicit SDK retry budget, separate from SQL repair rounds

    # Illustrative demo rates per million tokens, not a verified billing tariff.
    # Update these alongside model changes before using cost estimates operationally.
    prices: Mapping[str, Rates] = field(default_factory=lambda: MappingProxyType({
        "decisions": Rates(input=0.10, cached_input=0.01, output=0.0),
        "responses": Rates(input=0.10, cached_input=0.01, output=0.50),
    }))

    max_question_chars: int = 2000
    gate_min_relevance: float = 0.3
    gate_max_malicious: float = 0.7
    route_min_probability: float = 0.2
    route_max_unscored: float = 0.5  # a larger share of unusable routing scores is a classifier failure

    max_routed_tables: int = 12  # largest schema slice SQL may receive, dimensions included; broader asks to narrow
    sql_max_rounds: int = 5
    sql_max_rows: int = 500
    sql_max_chars: int = 20000
    sql_max_result_bytes: int = 64000
    sql_timeout_s: float = 10
    db_memory_limit: str = "256MB"
    db_threads: int = 2


def _read_env_file(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


def load_settings(env_file: Path = ENV_FILE, environ: Mapping[str, str] = os.environ) -> Settings:
    """Settings from env_file, overridden by environ. OPEN_AI_KEY and OPENAI_API_KEY are aliases for the API key;
    GRIDRAG_DECISIONS_MODEL and GRIDRAG_ANSWER_MODEL override the default models."""
    local = _read_env_file(env_file)

    def value(*names: str) -> str | None:
        # Resolve aliases within each source first, so either exported spelling wins
        # over either spelling in the local file.
        return next((source[name] for source in (environ, local) for name in names if source.get(name)), None)

    defaults = Settings()
    return Settings(
        openai_api_key=value("OPEN_AI_KEY", "OPENAI_API_KEY"),
        decisions_model=value("GRIDRAG_DECISIONS_MODEL") or defaults.decisions_model,
        answer_model=value("GRIDRAG_ANSWER_MODEL") or defaults.answer_model,
    )


settings = load_settings()
