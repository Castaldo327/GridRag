"""Generate the fictional warehouse and publish only the demo's frontend assets."""
import shutil
from pathlib import Path

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
    (output / "static").mkdir()
    for name in ("app.js", "app.css", "energy-mark.svg", "demo.json", "benchmark.json"):
        source = static / name
        if name == "benchmark.json" and not source.exists():
            continue
        shutil.copy2(source, output / "static" / name)
    shutil.copy2(static / "index.html", output / "index.html")
    print(f"Prepared {len(counts)} tables and {sum(counts.values()):,} fictional rows for Vercel.")


if __name__ == "__main__":
    main()
