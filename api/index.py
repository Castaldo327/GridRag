"""Vercel entrypoint using the same request handler as the local demo."""
from urllib.parse import parse_qs, urlsplit

from app.__main__ import Handler


class handler(Handler):
    require_visitor_key = True

    def _route(self):
        # Support both original paths and Vercel's rewritten destination paths.
        parsed = urlsplit(self.path)
        route = parse_qs(parsed.query).get("route", [None])[0]
        if route is not None:
            self.path = "/api/" + route

    def do_GET(self):
        self._route()
        super().do_GET()

    def do_POST(self):
        self._route()
        # The UI requests each evaluation case separately to bound function duration.
        if self.path == "/api/evaluate":
            return self.send(400, {"error": "Use the Evaluation tab to run the suite one case at a time."})
        super().do_POST()
