"""OpenAI Decisions and Responses calls with per-call usage, cost and timing.

One OpenAI client per process, so every question reuses pooled HTTPS connections. An LLM object records
one question's calls, each tagged with the stage (gate, route, sql) that made it.
"""

import time

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


def call_cost(kind: str, usage: dict) -> float:
    """USD for one call from its provider usage; cached input tokens are billed at the cached rate."""
    price = config.PRICES[kind]
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
    uncached = (usage.get("input_tokens") or 0) - cached
    return (uncached * price["input"] + cached * price["cached_input"]
            + (usage.get("output_tokens") or 0) * price["output"]) / 1e6


class LLM:
    """One question's model calls, each recorded with the stage that made it."""

    def __init__(self):
        self.calls: list[dict] = []

    def _request(self, kind: str, stage: str, method, **kwargs) -> dict:
        t = time.perf_counter()
        try:
            resp = method(**kwargs).model_dump(mode="json")
        except Exception as exc:
            self.calls.append({"kind": kind, "stage": stage, "seconds": round(time.perf_counter() - t, 3),
                               "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                               "error": type(exc).__name__})
            raise
        usage = resp.get("usage") or {}
        self.calls.append({
            "kind": kind,
            "stage": stage,
            "seconds": round(time.perf_counter() - t, 3),
            "input_tokens": usage.get("input_tokens") or 0,
            "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0,
            "output_tokens": usage.get("output_tokens") or 0,
            "cost_usd": call_cost(kind, usage),
            "error": None,
        })
        return resp

    def decide(self, stage: str, input_text: str, questions: list[dict]) -> dict[str, dict]:
        """One Decisions request; answers keyed by question name (a refused question is absent)."""
        resp = self._request(
            "decisions", stage, client().decisions.create,
            model=config.DECISIONS_MODEL, input=input_text, questions=questions,
        )
        return {a.get("name"): a for a in resp.get("answers", []) if a.get("type") != "refusal"}

    def respond(self, stage: str, instructions: str, input_items, **kwargs) -> dict:
        """One Responses request (tools, tool_choice and previous_response_id pass through)."""
        return self._request(
            "responses", stage, client().responses.create,
            model=config.ANSWER_MODEL,
            instructions=instructions,
            input=input_items,
            reasoning={"effort": config.ANSWER_REASONING},
            max_output_tokens=config.ANSWER_MAX_OUTPUT_TOKENS,
            **kwargs,
        )

    def totals(self) -> dict:
        return {
            "calls": len(self.calls),
            "failed_calls": sum(c["error"] is not None for c in self.calls),
            "input_tokens": sum(c["input_tokens"] for c in self.calls),
            "cached_tokens": sum(c["cached_tokens"] for c in self.calls),
            "output_tokens": sum(c["output_tokens"] for c in self.calls),
            "cost_usd": sum(c["cost_usd"] for c in self.calls),
            "per_call": list(self.calls),
        }
