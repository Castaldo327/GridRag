"""OpenAI Responses calls.

One OpenAI client per process, so every question reuses pooled HTTPS connections. Code that needs a
model takes an object with respond(), so tests can pass a fake and never reach the provider.
"""

from openai import OpenAI

from gridrag import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.require_key("OPEN_AI_KEY"), timeout=config.CALL_TIMEOUT_S)
    return _client


def output_text(resp: dict) -> str:
    texts, refusals = [], []
    for item in resp.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "refusal":
                refusals.append(part.get("refusal"))
    if refusals:
        raise RuntimeError(f"model refused: {refusals[0]}")
    return "".join(texts)


class LLM:
    def decide(self, input_text: str, questions: list[dict]) -> dict[str, dict]:
        """One Decisions request; answers keyed by question name (a refused question is absent)."""
        resp = client().decisions.create(
            model=config.DECISIONS_MODEL, input=input_text, questions=questions
        ).model_dump(mode="json")
        return {a.get("name"): a for a in resp.get("answers", []) if a.get("type") != "refusal"}

    def respond(self, instructions: str, input_items, **kwargs) -> dict:
        """One Responses request (tools, tool_choice and previous_response_id pass through)."""
        return client().responses.create(
            model=config.ANSWER_MODEL,
            instructions=instructions,
            input=input_items,
            reasoning={"effort": config.ANSWER_REASONING},
            max_output_tokens=config.ANSWER_MAX_OUTPUT_TOKENS,
            **kwargs,
        ).model_dump(mode="json")
