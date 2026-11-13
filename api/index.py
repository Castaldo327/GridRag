"""Vercel entrypoint using the same request handler as the local demo."""

from urllib.parse import parse_qs, urlsplit

from app.__main__ import Handler


class handler(Handler):
    require_visitor_key = True

    def _route(self):
        # Support both original paths and Vercel's rewritten destination paths.
        parsed = urlsplit(self.path)
        route = parse_qs(parsed.query).get("route", [None])[0]
        self.path = "/api/" + route if route is not None else parsed.path

    def do_GET(self):
        self._route()
        super().do_GET()

    def do_POST(self):
        self._route()
        if self.path in {"/api/evaluate", "/api/evaluate-case"}:
            return self.send(
                410, {"error": "Evaluation is read-only. View the recorded comparisons in the Evaluation tab."}
            )
        super().do_POST()
