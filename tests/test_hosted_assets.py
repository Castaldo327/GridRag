"""Public Markdown assets and the read-only evaluation boundary."""

import unittest
from unittest.mock import Mock, patch

from api.index import handler
from app.__main__ import ASSETS, STATIC, Handler


class HostedAssetsTests(unittest.TestCase):
    def test_every_required_asset_is_available_to_the_local_server(self):
        for route, (name, content_type) in ASSETS.items():
            if name == "benchmark.json" and not (STATIC / name).is_file():
                continue
            with self.subTest(route=route):
                request = Handler.__new__(Handler)
                request.path = route
                request.send = Mock()
                request.do_GET()
                status, content, kind = request.send.call_args.args
                self.assertEqual(status, 200)
                self.assertEqual(content, (STATIC / name).read_bytes())
                self.assertEqual(kind, content_type)

    def test_markdown_browser_bundles_are_served(self):
        for path, marker in [
            ("/static/vendor/marked.umd.js", b"marked"),
            ("/static/vendor/purify.min.js", b"DOMPurify"),
        ]:
            with self.subTest(path=path):
                request = Handler.__new__(Handler)
                request.path = path
                request.send = Mock()
                request.do_GET()
                status, content, kind = request.send.call_args.args
                self.assertEqual(status, 200)
                self.assertIn(marker, content)
                self.assertEqual(kind, "text/javascript; charset=utf-8")

    def test_hosted_evaluation_cannot_make_provider_calls(self):
        for path in (
            "/api/evaluate",
            "/api/evaluate-case",
            "/api?route=evaluate-case",
            "/api/evaluate?source=playground",
            "/api/evaluate-case?source=playground",
        ):
            with self.subTest(path=path), patch("app.__main__.LLM") as client:
                request = handler.__new__(handler)
                request.path = path
                request.send = Mock()
                request.do_POST()
                self.assertEqual(request.send.call_args.args[0], 410)
                client.assert_not_called()
