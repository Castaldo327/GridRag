"""Credential checks stay blocking for new files and modified historical blobs."""
import base64
import json
import unittest

from scripts.security_audit import EXPIRED_HISTORICAL_BLOB, reviewed_advisory, scan


class SecretScanTests(unittest.TestCase):
    def test_jwt_credentials_are_detected_even_after_expiry(self):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")
        token = b".".join((encode({"alg": "HS256", "typ": "JWT"}),
                           encode({"exp": 1, "sub": "synthetic-test"}), b"x" * 32))
        self.assertIn("JWT credential", scan(token))
        self.assertIn("copy of local secret", scan(token, [token]))

    def test_only_the_reviewed_immutable_blob_is_an_advisory(self):
        self.assertTrue(reviewed_advisory(EXPIRED_HISTORICAL_BLOB, ["JWT credential"]))
        self.assertFalse(reviewed_advisory("different-object", ["JWT credential"]))
        self.assertFalse(reviewed_advisory(EXPIRED_HISTORICAL_BLOB, ["provider credential"]))

    def test_fixtures_do_not_exempt_other_provider_credentials(self):
        self.assertEqual(scan(b"sk-private-visitor-test-key"), [])
        self.assertIn("provider credential", scan(b"sk-" + b"x" * 40))
