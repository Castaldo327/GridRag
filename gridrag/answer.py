"""Answer one question: request gate, then the model reads the warehouse schema, writes SQL, and answers
from the rows."""

from gridrag.gate import gate
from gridrag.llm import LLM
from gridrag.sql import agent
from gridrag.warehouse.build import END, ISOS, SCHEMA, START

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
    prompt = INSTRUCTIONS.format(
        isos=", ".join(ISOS), start=START, end=END, schema=SCHEMA.read_text(), rules=agent.ANSWER_RULES
    )
    return {"question": question, "gate": check, **agent.run(llm, prompt, question)}
