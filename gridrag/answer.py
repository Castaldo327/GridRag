"""Answer one question: request gate → schema routing → the SQL agent reads the routed schema, writes SQL,
and answers from the rows. Any exception becomes a failed record; details go to the log, not the answer."""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from gridrag import config
from gridrag.catalog import Catalog, demo_catalog
from gridrag.gate import gate
from gridrag.llm import LLM
from gridrag.records import Answer, Gate, Progress, Selection, Stage, State, ToolCall
from gridrag.route import RoutingTooBroad, route
from gridrag.sql import agent

logger = logging.getLogger(__name__)


def clean_question(question: object) -> str:
    """The question without surrounding whitespace; ValueError unless that is 1 to max_question_chars characters."""
    limit = config.settings.max_question_chars
    if not isinstance(question, str) or not 0 < len(question.strip()) <= limit:
        raise ValueError(f"question must contain 1–{limit} characters")
    return question.strip()


class _Trace:
    """What one question has produced so far: stage results, query evidence, and seconds per stage."""
    def __init__(self, question: str, llm, on_progress: Callable[[Progress], None] | None):
        self.question, self.llm, self.on_progress = question, llm, on_progress
        self.gate: Gate | None = None
        self.route: Selection | None = None
        self.tool_calls: list[ToolCall] = []
        self.stage: Stage | None = None  
        self.timings: dict[str, float] = {}
        self.started = time.perf_counter()

    def report(self, update: Progress) -> None:
        if "tool_calls" in update:  
            self.tool_calls = list(update["tool_calls"])
        if self.on_progress is not None:
            self.on_progress(update)

    @contextmanager
    def timed(self, stage: Stage, update: Progress | None = None) -> Iterator[None]:
        """Report the stage as started, with any results so far, and record its duration even if it fails."""
        self.stage, started = stage, time.perf_counter()
        self.report({**(update or {}), "stage": stage})
        try:
            yield
        finally:
            self.timings[stage] = round(time.perf_counter() - started, 3)

    def record(self, state: State, text: str) -> Answer:
        return {"question": self.question, "state": state, "answer": text, "gate": self.gate, "route": self.route,
                "tool_calls": self.tool_calls,
                "timings": {**self.timings, "total": round(time.perf_counter() - self.started, 3)},
                "usage": self.llm.totals()}


def answer(question: str, llm=None, on_progress: Callable[[Progress], None] | None = None, *,
           catalog: Catalog | None = None) -> Answer:
    """The answer record (gridrag.records.Answer). state is answered, abstained, write_failed, declined (gate),
    clarification (routing too broad) or failed, which adds error and stage. catalog is trusted schema
    documentation, the demo warehouse's by default; on_progress receives synchronous JSON-compatible updates.
    Invalid questions raise ValueError. A disconnected progress consumer stops execution."""
    trace = _Trace(clean_question(question), llm or LLM(), on_progress)
    try:
        return _run(trace, demo_catalog() if catalog is None else catalog)
    except RoutingTooBroad as exc: 
        trace.route = exc.selection
        return trace.record(State.CLARIFICATION, str(exc))
    except (BrokenPipeError, ConnectionResetError):
        raise  
    except Exception as exc:
        logger.exception("Question failed during %s", trace.stage)
        record = trace.record(State.FAILED, "The question could not be completed. Please try again.")
        record["error"] = type(exc).__name__
        if trace.stage is not None:
            record["stage"] = trace.stage
        return record


def _run(trace: _Trace, catalog: Catalog) -> Answer:
    question, llm = trace.question, trace.llm
    with trace.timed(Stage.GATE):
        trace.gate = gate(question, llm)
    if not trace.gate["allowed"]:
        return trace.record(State.DECLINED, trace.gate["reason"])

    with trace.timed(Stage.ROUTE, {"gate": trace.gate}):
        trace.route = route(question, llm, catalog)
    tables = trace.route["tables"]
    if not tables:
        return trace.record(State.ABSTAINED, "No matching warehouse tables were found for this question.")

    with trace.timed(Stage.SQL, {"route": trace.route}):
        schema = "\n\n".join(catalog.tables[table].ddl for table in tables)
        output = agent.run(llm, question, schema=schema, allowed_tables=tables, on_progress=trace.report)
    trace.tool_calls = output["tool_calls"]
    return trace.record(output["state"], output["answer"])
