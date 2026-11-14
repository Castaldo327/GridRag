"""Generate the fictional warehouse and publish only the demo's frontend assets."""

import shutil
from pathlib import Path

from app.assets import ASSETS
from gridrag.warehouse.build import build
from scripts.public_assets import build as build_public_assets

STATIC = Path("app/static")
OUTPUT = Path("public")


def _prepare_public_directory() -> None:
    # A clean output directory prevents stale files from being deployed.
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    for route, (name, _) in ASSETS.items():
        source = STATIC / name
        if name == "benchmark.json" and not source.exists():
            continue
        destination = OUTPUT / (route.lstrip("/") or "index.html")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main() -> None:
    """Build the fictional warehouse and stage its allowlisted frontend assets."""
    counts = build()
    build_public_assets()
    _prepare_public_directory()
    print(f"Prepared {len(counts)} tables and {sum(counts.values()):,} fictional rows for Vercel.")


if __name__ == "__main__":
    main()
