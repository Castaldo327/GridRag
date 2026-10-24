"""Answer one question: request gate → schema routing → the SQL agent reads the routed schema, writes SQL,
and answers from the rows. Any exception becomes a failed record; details go to the log, not the answer."""

import logging
import time
from collections.abc import Callable

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


def answer(question: str, llm=None, on_progress: Callable[[Progress], None] | None = None, *,
           catalog: Catalog | None = None) -> Answer:
    """The answer record (gridrag.records.Answer): question, state, answer, gate, route, tool_calls, timings
    (seconds per stage and total) and usage (model calls, tokens, cost); a failed record adds error and stage.
    state is answered, abstained, write_failed, declined (gate), clarification (routing too broad) or failed.
    catalog is trusted schema documentation, the demo warehouse's by default; on_progress receives synchronous
    JSON-compatible updates. Invalid questions raise ValueError. A disconnected progress consumer stops execution."""
    question = clean_question(question)
    calls: list[ToolCall] = []

    def report(update: Progress) -> None:
        if "tool_calls" in update:
            calls[:] = update["tool_calls"]
        if on_progress is not None:
            on_progress(update)

    llm = llm or LLM()
    check: Gate | None = None
    selection: Selection | None = None
    timings: dict[str, float] = {}
    started = time.perf_counter()
    stage: Stage | None = Stage.GATE
    stage_started = started

    def lap(next_stage: Stage | None = None) -> None:
        nonlocal stage, stage_started
        if stage is not None:
            timings[stage] = round(time.perf_counter() - stage_started, 3)
        stage, stage_started = next_stage, time.perf_counter()

    def finish(state: State, text: str, tool_calls: list[ToolCall] | None = None) -> Answer:
        return {"question": question, "state": state, "answer": text, "gate": check, "route": selection,
                "tool_calls": calls if tool_calls is None else tool_calls,
                "timings": {**timings, "total": round(time.perf_counter() - started, 3)}, "usage": llm.totals()}

    try:
        report({"stage": Stage.GATE})
        check = gate(question, llm)
        if not check["allowed"]:
            lap()
            return finish(State.DECLINED, check["reason"])
        lap(Stage.ROUTE)
        report({"stage": Stage.ROUTE, "gate": check})
        catalog = demo_catalog() if catalog is None else catalog
        selection = route(question, llm, catalog)
        if not selection["tables"]:
            lap()
            return finish(State.ABSTAINED, "No matching warehouse tables were found for this question.")
        lap(Stage.SQL)
        report({"stage": Stage.SQL, "route": selection})
        schema = "\n\n".join(catalog.tables[table].ddl for table in selection["tables"])
        output = agent.run(llm, question, schema=schema, allowed_tables=selection["tables"], on_progress=report)
        lap()
        return finish(output["state"], output["answer"], output["tool_calls"])
    except RoutingTooBroad as exc:  # ask to narrow instead of handing SQL an oversized schema
        selection = exc.selection
        lap()
        return finish(State.CLARIFICATION, str(exc))
    except (BrokenPipeError, ConnectionResetError):
        raise  # stop work when the progress consumer disconnects
    except Exception as exc:
        logger.exception("Question failed during %s", stage)
        failed_stage = stage
        lap()
        record = finish(State.FAILED, "The question could not be completed. Please try again.")
        record["error"] = type(exc).__name__
        if failed_stage is not None:
            record["stage"] = failed_stage
        return record
