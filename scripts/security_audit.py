"""Redacted secret checks for source, Git history, and release artifacts.

Reports locations and categories only, never matched values. This is a focused
release guard, not a guarantee that every possible credential format is detected.
"""

import argparse
import json
import re
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import MappingProxyType

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
# Reviewed immutable historical blob, not a path or a token-pattern exemption.
# Its VERCEL_OIDC_TOKEN expired 2026-11-05 07:26:57 UTC. It remains disclosed
# as an advisory. Any current-file copy or changed blob is still a blocking finding.
EXPIRED_HISTORICAL_BLOB = "4c5c1f9c41b15dc6dc7afe38ddb361e93b7a223d"


def reviewed_advisory(oid: str, categories: Iterable[str]) -> bool:
    """Recognize findings covered by the reviewed historical-blob exception."""
    return oid == EXPIRED_HISTORICAL_BLOB and set(categories) <= {"JWT credential", "copy of local secret"}


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


def git(*args: str) -> bytes:
    """Capture Git output from the repository, propagating command failures."""
    return subprocess.check_output(["git", *args], cwd=ROOT)


def _file_candidates(directory: Path | None) -> Iterator[tuple[str, bytes]]:
    if directory is not None:
        for path in directory.rglob("*"):
            if path.is_file():
                yield str(path.relative_to(directory)), path.read_bytes()
        return
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    for name in names:
        path = ROOT / name
        if name and path.is_file():
            yield name, path.read_bytes()


def _scan_history(
    secrets: Iterable[bytes],
) -> tuple[int, list[dict[str, str | list[str]]], list[dict[str, str | list[str]]]]:
    findings: list[dict[str, str | list[str]]] = []
    advisories: list[dict[str, str | list[str]]] = []
    count = 0
    for entry in git("rev-list", "--objects", "--all").decode().splitlines():
        oid, _, name = entry.partition(" ")
        if not name or git("cat-file", "-t", oid).strip() != b"blob":
            continue
        count += 1
        if categories := scan(git("cat-file", "blob", oid), secrets):
            finding: dict[str, str | list[str]] = {"object": oid[:12], "path": name, "categories": categories}
            if reviewed_advisory(oid, categories):
                advisories.append({**finding, "reason": "Reviewed Vercel OIDC token expired 2026-11-05 07:26:57 UTC"})
            else:
                findings.append(finding)
    return count, findings, advisories


def main() -> None:
    """Print a redacted scan report and exit unsuccessfully on blocking findings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    secrets = local_secrets()
    findings: list[dict[str, str | list[str]]] = []
    advisories: list[dict[str, str | list[str]]] = []
    count = 0
    for name, data in _file_candidates(args.directory):
        count += 1
        if categories := scan(data, secrets):
            findings.append({"path": name, "categories": categories})
    if args.history:
        history_count, history_findings, advisories = _scan_history(secrets)
        count += history_count
        findings.extend(history_findings)
    print(
        json.dumps(
            {
                "scanned": count,
                "findings": findings,
                "advisories": advisories,
                "history_note": "Git commits contain author metadata; clean exports omit Git history.",
            },
            indent=2,
        )
    )
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
