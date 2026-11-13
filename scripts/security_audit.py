"""Redacted secret checks for source, Git history, and release artifacts.

Reports locations and categories only, never matched values. This is a focused
release guard, not a guarantee that every possible credential format is detected.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider credential": re.compile(
        rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,})"
    ),
    "JWT credential": re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}\b"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "personal filesystem path": re.compile(rb"/(?:Users|home)/[A-Za-z][^/\s]+/"),
    "email address": re.compile(rb"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
}
# Exact fake credentials from contract tests; no blanket exemption for test files.
FIXTURES = {b"sk-private-visitor-test-key", b"sk-valid-shaped-test-key"}
# Reviewed immutable historical blob, not a path or a token-pattern exemption.
# Its VERCEL_OIDC_TOKEN expired 2026-11-05 07:26:57 UTC. It remains disclosed
# as an advisory. Any current-file copy or changed blob is still a blocking finding.
EXPIRED_HISTORICAL_BLOB = "4c5c1f9c41b15dc6dc7afe38ddb361e93b7a223d"


def reviewed_advisory(oid, categories):
    return oid == EXPIRED_HISTORICAL_BLOB and set(categories) <= {"JWT credential", "copy of local secret"}


def local_secrets():
    values = []
    for path in (ROOT / ".env", ROOT / ".env.local"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                value = value.strip().strip("\"'")
                if (
                    sep
                    and len(value) > 16
                    and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
                ):
                    values.append(value.encode())
    return values


def scan(data, secrets=()):
    categories = [
        label
        for label, pattern in PATTERNS.items()
        if any(match[0] not in FIXTURES for match in pattern.finditer(data))
    ]
    if any(value in data for value in secrets):
        categories.append("copy of local secret")
    return categories


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    secrets = local_secrets()
    findings, advisories, count = [], [], 0
    if args.directory:
        candidates = [
            (str(p.relative_to(args.directory)), p.read_bytes()) for p in args.directory.rglob("*") if p.is_file()
        ]
    else:
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
        candidates = [(name, (ROOT / name).read_bytes()) for name in names if name and (ROOT / name).is_file()]
    for name, data in candidates:
        count += 1
        if categories := scan(data, secrets):
            findings.append({"path": name, "categories": categories})
    if args.history:
        for item in git("rev-list", "--objects", "--all").decode().splitlines():
            oid, _, name = item.partition(" ")
            if not name or git("cat-file", "-t", oid).strip() != b"blob":
                continue
            count += 1
            if categories := scan(git("cat-file", "blob", oid), secrets):
                item = {"object": oid[:12], "path": name, "categories": categories}
                if reviewed_advisory(oid, categories):
                    advisories.append({**item, "reason": "Reviewed expired Vercel OIDC token; see SECURITY.md"})
                else:
                    findings.append(item)
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
