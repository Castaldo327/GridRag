"""Answer one question: the model reads the warehouse schema, writes SQL, and answers from the rows."""

from gridrag.llm import LLM
from gridrag.sql import agent
from gridrag.warehouse.build import END, ISOS, SCHEMA, START

INSTRUCTIONS = """Answer questions about the US electricity data for {isos} by querying the warehouse.
Write schema-qualified DuckDB SQL and call run_sql before stating any measured result. If a query fails,
repair it. Hourly data covers local dates {start:%b %d %Y} through {end:%b %d %Y}.
Calendar dates use interval_start_local unless UTC is explicitly requested.

{schema}

{rules}"""


def answer(question: str, llm=None) -> dict:
    prompt = INSTRUCTIONS.format(
        isos=", ".join(ISOS), start=START, end=END, schema=SCHEMA.read_text(), rules=agent.ANSWER_RULES
    )
    return {"question": question, **agent.run(llm or LLM(), prompt, question)}
