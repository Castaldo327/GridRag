"""Answer one question: request gate → schema routing → the model reads the routed schema, writes SQL,
and answers from the rows. Any exception becomes a failed record; details go to the log, not the answer."""

import logging
import time

from gridrag.gate import gate
from gridrag.llm import LLM
from gridrag.route import RoutingTooBroad, route, schema_blocks
from gridrag.sql import agent

logger = logging.getLogger(__name__)
INSTRUCTIONS = """Answer the request by querying the available warehouse tables below.
Write schema-qualified DuckDB SQL and call run_sql before stating measured results.
Inspect values or coverage with SQL when needed; repair failed queries using the returned error.

{schema}

{rules}"""

def answer(question: str, llm=None, on_progress=None) -> dict:
    """The answer record: question, state, answer, gate, route, tool_calls, timings (seconds per stage and
    total) and usage (model calls, tokens, cost); a failed record adds error and stage. state is answered,
    abstained, write_failed, declined (gate), clarification (routing too broad) or failed."""
    report = on_progress or (lambda update: None)
    llm = llm or LLM()
    check, selection, timings, started = None, None, {}, time.perf_counter()
    stage, stage_started = "gate", started

    def lap(next_stage: str | None = None) -> None:
        nonlocal stage, stage_started
        timings[stage] = round(time.perf_counter() - stage_started, 3)
        stage, stage_started = next_stage, time.perf_counter()

    def finish(**fields) -> dict:
        return {"question": question, "gate": check, "route": selection, "tool_calls": [], **fields,
                "timings": {**timings, "total": round(time.perf_counter() - started, 3)}, "usage": llm.totals()}

    try:
        report({"stage": "gate"})
        check = gate(question, llm)
        if not check["allowed"]:
            lap()
            return finish(state="declined", answer=check["reason"])
        lap("route")
        report({"stage": "route", "gate": check})
        selection = route(question, llm)
        lap("sql")
        report({"stage": "sql", "route": selection})
        blocks = schema_blocks()
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
    except Exception as exc:
        logger.exception("Question failed during %s", stage)
        failed_stage = stage
        lap()
        return finish(state="failed", answer="The question could not be completed. Please try again.",
                      error=type(exc).__name__, stage=failed_stage)
