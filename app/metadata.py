"""Demo question presets shared by HTTP responses and the static build."""

from gridrag.evals.cases import CASES


def presets() -> list[dict[str, str]]:
    """Return labeled demo questions in their display order."""
    return [
        {"id": case.id, "label": case.label, "concept": case.concept, "question": case.question}
        for case in CASES
        if case.label
    ]
