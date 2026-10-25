"""One frozen Settings object: paths, the API key, models, cost rates, thresholds and budgets.

settings is loaded once, from .env overridden by the process environment. Modules read config.settings when they
need a value, so tests and experiments can swap in dataclasses.replace(config.settings, ...) in one place.
"""

import os
from collections.abc import Mapping
from dataclasses import field
from pathlib import Path
from types import MappingProxyType
from typing import Annotated

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

_VALIDATION = ConfigDict(strict=True, validate_default=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)
Probability = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]
PositiveSeconds = Annotated[float, Field(gt=0)]


@dataclass(frozen=True, config=_VALIDATION)
class Rates:
    """USD per million tokens."""

    input: Annotated[float, Field(ge=0)]
    cached_input: Annotated[float, Field(ge=0)]
    output: Annotated[float, Field(ge=0)]


@dataclass(frozen=True, config=_VALIDATION)
class Settings:
    db_path: Path = ROOT / "data" / "warehouse.duckdb"
    openai_api_key: str | None = field(default=None, repr=False)
    decisions_model: str = "gpt-6-luna"
    answer_model: str = "gpt-6-luna"
    answer_reasoning: str = "none"
    answer_max_output_tokens: PositiveInt = 1600
    call_timeout_s: PositiveSeconds = 30
    api_max_retries: Annotated[int, Field(ge=0)] = 1

    prices: Mapping[str, Rates] = field(default_factory=lambda: MappingProxyType({
        "decisions": Rates(input=0.10, cached_input=0.01, output=0.0),
        "responses": Rates(input=0.10, cached_input=0.01, output=0.50),
    }))

    max_question_chars: PositiveInt = 2000
    gate_min_relevance: Probability = 0.3
    gate_max_malicious: Probability = 0.7
    route_min_probability: Probability = 0.2
    route_min_column_probability: Probability = 0.2
    route_max_unscored: Probability = 0.5
    max_routed_tables: PositiveInt = 10
    route_column_workers: PositiveInt = 4
    sql_max_rounds: PositiveInt = 5
    sql_max_rows: PositiveInt = 500
    sql_max_chars: PositiveInt = 20000
    sql_max_result_bytes: PositiveInt = 64000
    sql_timeout_s: PositiveSeconds = 10
    db_memory_limit: str = "256MB"
    db_threads: PositiveInt = 2

    def __post_init__(self) -> None:
        # Pydantic validates/copies mappings; freeze the validated snapshot as well.
        object.__setattr__(self, "prices", MappingProxyType(dict(self.prices)))


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
    local = _read_env_file(env_file)

    def value(*names: str) -> str | None:
        return next((source[name] for source in (environ, local) for name in names if source.get(name)), None)

    defaults = Settings()
    return Settings(
        openai_api_key=value("OPEN_AI_KEY", "OPENAI_API_KEY"),
        decisions_model=value("GRIDRAG_DECISIONS_MODEL") or defaults.decisions_model,
        answer_model=value("GRIDRAG_ANSWER_MODEL") or defaults.answer_model,
    )


settings = load_settings()
