"""Public export checks remain redacted and never traverse repository history."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import security_audit
from scripts.security_audit import scan


class SecretScanTests(unittest.TestCase):
    def test_jwt_credentials_are_detected_even_after_expiry(self):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")

        token = b".".join(
            (encode({"alg": "HS256", "typ": "JWT"}), encode({"exp": 1, "sub": "synthetic-test"}), b"x" * 32)
        )
        self.assertIn("JWT credential", scan(token))
        self.assertIn("copy of local secret", scan(token, [token]))

    def test_default_scan_only_reads_assets_that_are_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app" / "static").mkdir(parents=True)
            (root / "app" / "static" / "demo.json").write_text("{}")
            (root / "private.txt").write_text("not a public export")
            assets = {"/static/demo.json": ("demo.json", "application/json")}
            with patch.object(security_audit, "ROOT", root), patch.object(security_audit, "ASSETS", assets):
                files = list(security_audit._file_candidates(None))
            self.assertEqual(files, [("app/static/demo.json", b"{}")])

    def test_explicit_export_directory_checks_every_exported_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "nested" / "report.json").write_text("{}")
            self.assertEqual(list(security_audit._file_candidates(root)), [("nested/report.json", b"{}")])

    def test_fixtures_do_not_exempt_other_provider_credentials(self):
        self.assertEqual(scan(b"sk-private-visitor-test-key"), [])
        self.assertIn("provider credential", scan(b"sk-" + b"x" * 40))
