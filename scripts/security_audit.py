"""Redacted privacy and credential-copy checks for public export artifacts.

Gitleaks owns repository and Git-history credential scanning in CI. This guard
checks the assets we actually publish, including copies of local secret values.
"""

import argparse
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import MappingProxyType

from app.assets import ASSETS

ROOT = Path(__file__).resolve().parents[1]
MIN_SECRET_LENGTH = 16
PATTERNS = MappingProxyType(
    {
        "provider credential": re.compile(
            rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,})"
        ),
        "JWT credential": re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}\b"),
        "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "personal filesystem path": re.compile(rb"/(?:Users|home)/[A-Za-z][^/\s]+/"),
        "email address": re.compile(rb"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    }
)
# Exact fake credentials from contract tests; no blanket exemption for test files.
FIXTURES = frozenset({b"sk-private-visitor-test-key", b"sk-valid-shaped-test-key"})


def local_secrets() -> list[bytes]:
    """Read potential secret values from the repository's local environment files."""
    values = []
    for path in (ROOT / ".env", ROOT / ".env.local"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                value = value.strip().strip("\"'")
                if (
                    sep
                    and len(value) > MIN_SECRET_LENGTH
                    and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
                ):
                    values.append(value.encode())
    return values


def scan(data: bytes, secrets: Iterable[bytes] = ()) -> list[str]:
    """Return matching categories without exposing credential values."""
    categories = [
        label
        for label, pattern in PATTERNS.items()
        if any(match[0] not in FIXTURES for match in pattern.finditer(data))
    ]
    if any(value in data for value in secrets):
        categories.append("copy of local secret")
    return categories


def _file_candidates(directory: Path | None) -> Iterator[tuple[str, bytes]]:
    if directory is None:
        paths = (ROOT / "app" / "static" / name for name, _ in ASSETS.values())
    else:
        paths = directory.rglob("*")
    for path in paths:
        if path.is_file():
            yield str(path.relative_to(directory or ROOT)), path.read_bytes()


def main() -> None:
    """Print a redacted scan report and exit unsuccessfully on blocking findings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    secrets = local_secrets()
    findings: list[dict[str, str | list[str]]] = []
    count = 0
    for name, data in _file_candidates(args.directory):
        count += 1
        if categories := scan(data, secrets):
            findings.append({"path": name, "categories": categories})
    print(json.dumps({"scanned": count, "findings": findings}, indent=2))
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
