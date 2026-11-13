"""Answer one question: request gate → schema routing → the SQL agent reads the routed schema, writes SQL,
and answers from the rows. Any exception becomes a failed record; details go to the log, not the answer."""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from openai import APIError, AuthenticationError, PermissionDeniedError, RateLimitError

from gridrag import config
from gridrag.catalog import Catalog, demo_catalog
from gridrag.gate import gate
from gridrag.grounding import render_grounding
from gridrag.llm import LLM, Model
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

    def __init__(self, question: str, llm: Model, on_progress: Callable[[Progress], None] | None):
        self.question, self.llm, self.on_progress = question, llm, on_progress
        self.gate: Gate | None = None
        self.route: Selection | None = None
        self.tool_calls: list[ToolCall] = []
        self.stage: Stage | None = None
        self.timings: dict[str, float] = {}
        self.started = time.perf_counter()

    def report(self, update: Progress) -> None:
        if update.get("answer_delta") and "first_token" not in self.timings:
            self.timings["first_token"] = round(time.perf_counter() - self.started, 3)
        if "tool_calls" in update:
            self.tool_calls = list(update["tool_calls"])
        if self.on_progress is not None:
            self.on_progress(update)

    @contextmanager
    def timed(self, stage: Stage, update: Progress | None = None) -> Iterator[None]:
        """Report the stage as started, with any results so far, and record its duration even if it fails."""
        self.stage, started = stage, time.perf_counter()
        try:
            self.report({**(update or {}), "stage": stage})
            yield
        finally:
            self.timings[stage] = round(time.perf_counter() - started, 3)

    def record(self, state: State, text: str) -> Answer:
        return {
            "question": self.question,
            "state": state,
            "answer": text,
            "gate": self.gate,
            "route": self.route,
            "tool_calls": self.tool_calls,
            "timings": {**self.timings, "total": round(time.perf_counter() - self.started, 3)},
            "usage": self.llm.totals(),
        }


def answer(
    question: str,
    llm: Model | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    *,
    catalog: Catalog | None = None,
    retriever: Callable[[str, Model, Catalog], Selection] | None = None,
) -> Answer:
    """The answer record (gridrag.records.Answer). state is answered, abstained, write_failed, declined (gate),
    clarification (routing too broad) or failed, which adds error and stage. catalog is trusted schema
    documentation, the demo warehouse's by default; on_progress receives synchronous JSON-compatible updates.
    retriever replaces schema selection for controlled comparisons; it receives no reference answers.
    Invalid questions raise ValueError. A disconnected progress consumer stops execution."""
    trace = _Trace(clean_question(question), LLM() if llm is None else llm, on_progress)
    try:
        return _run(trace, demo_catalog() if catalog is None else catalog, route if retriever is None else retriever)
    except RoutingTooBroad as exc:
        trace.route = exc.selection
        return trace.record(State.CLARIFICATION, str(exc))
    except (BrokenPipeError, ConnectionResetError):
        raise
    except Exception as exc:
        message = "The question could not be completed. Please try again."
        if isinstance(exc, APIError):
            # Provider exception bodies can contain credentials. Do not log them.
            logger.error("Question failed during %s (%s)", trace.stage, type(exc).__name__)
            if isinstance(exc, AuthenticationError):
                message = "Your API key was not accepted. Replace it and try again."
            elif isinstance(exc, PermissionDeniedError):
                message = (
                    "Your API key does not have access to the configured model or API. Check your project permissions."
                )
            elif isinstance(exc, RateLimitError):
                message = (
                    "Your OpenAI project reached a rate or usage limit. Check your API billing and limits, then retry."
                )
        else:
            logger.error("Question failed during %s (%s)", trace.stage, type(exc).__name__)
        record = trace.record(State.FAILED, message)
        record["error"] = type(exc).__name__
        if trace.stage is not None:
            record["stage"] = trace.stage
        return record


def _run(trace: _Trace, catalog: Catalog, retriever: Callable[[str, Model, Catalog], Selection]) -> Answer:
    question, llm = trace.question, trace.llm
    with trace.timed(Stage.GATE):
        trace.gate = gate(question, llm)
    if not trace.gate["allowed"]:
        return trace.record(State.DECLINED, trace.gate["reason"])

    with trace.timed(Stage.ROUTE, {"gate": trace.gate}):
        trace.route = retriever(question, llm, catalog)
    tables = trace.route["tables"]
    if not tables:
        return trace.record(State.ABSTAINED, "No matching warehouse tables were found for this question.")

    with trace.timed(Stage.SQL, {"route": trace.route}):
        schema = "\n\n".join(catalog.tables[table].selected_schema(trace.route["columns"][table]) for table in tables)
        output = agent.run(
            llm,
            question,
            schema=schema,
            allowed_tables=tables,
            on_progress=trace.report,
            grounding=render_grounding(catalog.vocabulary, trace.route["columns"]),
        )
    trace.tool_calls = output["tool_calls"]
    return trace.record(output["state"], output["answer"])
