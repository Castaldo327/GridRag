"""Generate the fictional warehouse and publish only the demo's frontend assets."""
import shutil
from pathlib import Path

from app.assets import ASSETS
from gridrag.warehouse.build import build
from scripts.public_assets import build as build_public_assets


def main():
    counts = build()
    build_public_assets()
    static = Path("app/static")
    output = Path("public")
    # A clean output directory prevents stale files from being deployed.
    if output.exists():
        shutil.rmtree(output)
    output.mkdir()
    for route, (name, _) in ASSETS.items():
        source = static / name
        if name == "benchmark.json" and not source.exists():
            continue
        destination = output / (route.lstrip("/") or "index.html")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    print(f"Prepared {len(counts)} tables and {sum(counts.values()):,} fictional rows for Vercel.")


if __name__ == "__main__":
    main()
