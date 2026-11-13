"""Create a reviewed source snapshot without credentials, local files, or Git history."""

import hashlib
import json
import shutil

from scripts.security_audit import ROOT, local_secrets, scan

FILES = {
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "uv.lock",
    "vercel.json",
    ".gitleaksignore",
    "compose.yaml",
    ".gitignore",
    ".vercelignore",
    ".env.example",
}
TREES = {"app", "api", "gridrag", "benchmarks", "scripts", "tests", ".github/workflows"}
SUFFIXES = {".py", ".js", ".css", ".html", ".svg", ".png", ".json", ".sql", ".md", ".yml"}


def release_files():
    paths = {ROOT / name for name in FILES if (ROOT / name).is_file()}
    for tree in TREES:
        paths.update(
            p
            for p in (ROOT / tree).rglob("*")
            if p.is_file()
            and p.suffix in SUFFIXES
            and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(ROOT / tree).parts)
        )
    return sorted(paths)


def main():
    destination = ROOT / "artifacts" / "public-source"
    secrets, files = local_secrets(), release_files()
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError("Release refuses symlinks or files outside the repository")
        if categories := scan(path.read_bytes(), secrets):
            raise RuntimeError(f"Release blocked: {path.relative_to(ROOT)} ({', '.join(categories)})")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    manifest = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        manifest[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(files)} scanned files in artifacts/public-source; Git history and local metadata excluded.")


if __name__ == "__main__":
    main()
