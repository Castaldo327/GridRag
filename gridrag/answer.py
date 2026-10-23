"""Answer one question: request gate → domain routing → the model reads the routed schema, writes SQL,
and answers from the rows."""

from gridrag.gate import gate
from gridrag.llm import LLM
from gridrag.route import route, schema_blocks
from gridrag.sql import agent
from gridrag.warehouse.build import END, ISOS, START

INSTRUCTIONS = """Answer questions about the US electricity data for {isos} by querying the warehouse.
Write schema-qualified DuckDB SQL and call run_sql before stating any measured result. If a query fails,
repair it. Hourly data covers local dates {start:%b %d %Y} through {end:%b %d %Y}.
Interconnection-queue data is one current snapshot as of {end:%b %d %Y}; it is not a historical queue.
Calendar dates use interval_start_local unless UTC is explicitly requested.

{schema}

{rules}"""


def answer(question: str, llm=None) -> dict:
    llm = llm or LLM()
    check = gate(question, llm)
    if not check["allowed"]:
        return {"question": question, "state": "declined", "answer": check["reason"], "gate": check, "tool_calls": []}
    selection = route(question, llm)
    blocks = schema_blocks()
    prompt = INSTRUCTIONS.format(
        isos=", ".join(ISOS), start=START, end=END, rules=agent.ANSWER_RULES,
        schema="\n\n".join(blocks[table] for table in selection["tables"]),
    )
    return {"question": question, "gate": check, "route": selection, **agent.run(llm, prompt, question)}
