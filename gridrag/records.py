"""The records the pipeline returns and streams, as JSON-compatible TypedDicts, and the names they use.

State and Stage are StrEnums, so a record serializes to the same strings the web UI, CLI and tests read.
"""

from enum import StrEnum
from typing import Literal, NotRequired, TypedDict


class State(StrEnum):
    """How a question ended."""

    ANSWERED = "answered"  # backed by at least one successful query
    ABSTAINED = "abstained"  # the SQL model ran no query
    WRITE_FAILED = "write_failed"  # every query failed
    DECLINED = "declined"  # the gate declined the request
    CLARIFICATION = "clarification"  # routing needs a narrower question
    FAILED = "failed"  # an exception; details go to the log, not the answer


class Stage(StrEnum):
    """Pipeline stages: timed, reported as progress and tagged on model calls."""

    GATE = "gate"
    ROUTE = "route"
    SQL = "sql"
    ANSWER = "answer"  # progress only: the SQL model is interpreting query results


class Gate(TypedDict):
    allowed: bool
    reason: str
    relevance: float
    malicious: float


class Selection(TypedDict):
    tables: list[str]  # handed to SQL in catalog order, referenced tables included
    scores: dict[str, float | None]  # core table or product family -> probability it is needed
    iso_scores: dict[str, float | None]  # ISO -> probability the request needs it
    fallback: bool  # an unusable score kept its table, family or ISO


class QueryResult(TypedDict, total=False):
    """One run_sql result: rows and csv (and truncated past the row cap), or error for the model to repair."""

    rows: int
    csv: str
    truncated: str
    error: str


class ToolCall(TypedDict):
    execution_seconds: NotRequired[float]  # database guard, execution and result serialization
    query: str | None  # the SQL, or the raw arguments when they were invalid
    rows: int | None
    error: str | None
    csv: str | None
    truncated: str | None


class ModelCall(TypedDict):
    kind: Literal["decisions", "responses"]
    stage: Stage
    seconds: float
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float
    error: str | None


class Usage(TypedDict):
    calls: int
    failed_calls: int
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: float
    per_call: list[ModelCall]


class AgentResult(TypedDict):
    answer: str
    state: State
    tool_calls: list[ToolCall]


class Answer(TypedDict):
    """One question's record. A failed record adds error (the exception type) and the stage that failed."""

    question: str
    state: State
    answer: str
    gate: Gate | None
    route: Selection | None
    tool_calls: list[ToolCall]
    timings: dict[str, float]  # seconds per stage, total, and first_token when answer text streamed
    usage: Usage
    error: NotRequired[str]
    stage: NotRequired[Stage]


class Progress(TypedDict, total=False):
    """A synchronous progress update: the stage now running, and results as they arrive."""

    answer_text: str  # reset provisional text at a new model turn
    answer_delta: str  # append streamed text; final Answer remains authoritative
    stage: Stage
    gate: Gate
    route: Selection
    tool_calls: list[ToolCall]
