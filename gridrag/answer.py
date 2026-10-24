"""Answer one question: request gate → schema routing → the model reads the routed schema, writes SQL,
and answers from the rows. Any exception becomes a failed record; details go to the log, not the answer."""

import logging
import time

from gridrag.catalog import schema_blocks
from gridrag.config import MAX_QUESTION_CHARS
from gridrag.gate import gate
from gridrag.llm import LLM
from gridrag.route import RoutingTooBroad, route
from gridrag.sql import agent

logger = logging.getLogger(__name__)
INSTRUCTIONS = """Answer the request by querying the available warehouse tables below.
Write schema-qualified DuckDB SQL and call run_sql before stating measured results.
Inspect values or coverage with SQL when needed; repair failed queries using the returned error.

{schema}

{rules}"""


def answer(question: str, llm=None, on_progress=None, *, catalog: dict[str, str] | None = None) -> dict:
    """The answer record: question, state, answer, gate, route, tool_calls, timings (seconds per stage and
    total) and usage (model calls, tokens, cost); a failed record adds error and stage. state is answered,
    abstained, write_failed, declined (gate), clarification (routing too broad) or failed.
    catalog is trusted schema documentation; on_progress receives synchronous JSON-compatible updates.
    Invalid questions raise ValueError. A disconnected progress consumer stops execution."""
    if not isinstance(question, str) or not 0 < len(question.strip()) <= MAX_QUESTION_CHARS:
        raise ValueError(f"question must contain 1–{MAX_QUESTION_CHARS} characters")
    question = question.strip()
    calls = []

    def report(update: dict) -> None:
        if "tool_calls" in update:
            calls[:] = update["tool_calls"]
        if on_progress is not None:
            on_progress(update)

    llm = llm or LLM()
    check, selection, timings, started = None, None, {}, time.perf_counter()
    stage, stage_started = "gate", started

    def lap(next_stage: str | None = None) -> None:
        nonlocal stage, stage_started
        timings[stage] = round(time.perf_counter() - stage_started, 3)
        stage, stage_started = next_stage, time.perf_counter()

    def finish(**fields) -> dict:
        return {"question": question, "gate": check, "route": selection, "tool_calls": calls, **fields,
                "timings": {**timings, "total": round(time.perf_counter() - started, 3)}, "usage": llm.totals()}

    try:
        report({"stage": "gate"})
        check = gate(question, llm)
        if not check["allowed"]:
            lap()
            return finish(state="declined", answer=check["reason"])
        lap("route")
        report({"stage": "route", "gate": check})
        blocks = schema_blocks() if catalog is None else dict(catalog)
        selection = route(question, llm, blocks)
        if not selection["tables"]:
            lap()
            return finish(state="abstained", answer="No matching warehouse tables were found for this question.")
        lap("sql")
        report({"stage": "sql", "route": selection})
        prompt = INSTRUCTIONS.format(
            rules=agent.ANSWER_RULES,
            schema="\n\n".join(blocks[table] for table in selection["tables"]),
        )
        output = agent.run(llm, prompt, question, set(selection["tables"]), on_progress=report)
        lap()
        return finish(**output)
    except RoutingTooBroad as exc:  # ask to narrow instead of handing SQL an oversized schema
        selection = exc.selection
        lap()
        return finish(state="clarification", answer=str(exc))
    except (BrokenPipeError, ConnectionResetError):
        raise  # stop work when the progress consumer disconnects
    except Exception as exc:
        logger.exception("Question failed during %s", stage)
        failed_stage = stage
        lap()
        return finish(state="failed", answer="The question could not be completed. Please try again.",
                      error=type(exc).__name__, stage=failed_stage)
