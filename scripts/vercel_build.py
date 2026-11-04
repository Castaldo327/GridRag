"""Generate the fictional warehouse and publish only the demo's frontend assets."""
import shutil
from pathlib import Path

from gridrag.warehouse.build import build


def main():
    counts = build()
    static = Path("app/static")
    output = Path("public")
    output.mkdir(exist_ok=True)
    shutil.copytree(static, output / "static", dirs_exist_ok=True)
    shutil.copy2(static / "index.html", output / "index.html")
    print(f"Prepared {len(counts)} tables and {sum(counts.values()):,} fictional rows for Vercel.")


if __name__ == "__main__":
    main()
