"""Answer one question: request gate → domain routing → the model reads the routed schema, writes SQL,
and answers from the rows. Any exception becomes a failed record; details go to the log, not the answer."""

import logging
import time

from gridrag.gate import gate
from gridrag.llm import LLM
from gridrag.route import route, schema_blocks
from gridrag.sql import agent
from gridrag.warehouse.build import END, ISOS, START

logger = logging.getLogger(__name__)
INSTRUCTIONS = """Answer questions about the US electricity data for {isos} by querying the warehouse.
Write schema-qualified DuckDB SQL and call run_sql before stating any measured result. If a query fails,
repair it. Hourly data covers local dates {start:%b %d %Y} through {end:%b %d %Y}.
Interconnection-queue data is one current snapshot as of {end:%b %d %Y}; it is not a historical queue.
Calendar dates use interval_start_local unless UTC is explicitly requested.

{schema}

{rules}"""


def answer(question: str, llm=None) -> dict:
    """The answer record: question, state, answer, gate, route, tool_calls, timings (seconds per stage and
    total) and usage (model calls, tokens, cost); a failed record adds error and stage."""
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
        check = gate(question, llm)
        lap("route")
        if not check["allowed"]:
            return finish(state="declined", answer=check["reason"])
        selection = route(question, llm)
        lap("sql")
        blocks = schema_blocks()
        prompt = INSTRUCTIONS.format(
            isos=", ".join(ISOS), start=START, end=END, rules=agent.ANSWER_RULES,
            schema="\n\n".join(blocks[table] for table in selection["tables"]),
        )
        output = agent.run(llm, prompt, question, set(selection["tables"]))
        lap()
        return finish(**output)
    except Exception as exc:
        logger.exception("Question failed during %s", stage)
        failed_stage = stage
        lap()
        return finish(state="failed", answer="The question could not be completed. Please try again.",
                      error=type(exc).__name__, stage=failed_stage)
