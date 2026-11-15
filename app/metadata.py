"""Load public demo presets from the same artifact served to the browser."""

import json
from pathlib import Path


def presets() -> list[dict[str, str]]:
    return json.loads(Path(__file__).with_name("static").joinpath("demo.json").read_text(encoding="utf-8"))["presets"]
