"""Local API contracts, without provider calls."""

import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from app.__main__ import PRESETS, Handler
from gridrag import config


def send(head, body=b""):
    request = (head + "\r\n\r\n").encode() + body

    class Connection:
        output = b""

        def makefile(self, *args):
            return io.BytesIO(request)

        def sendall(self, data):
            self.output += data

    connection = Connection()
    with patch.object(Handler, "log_message"):
        Handler(connection, ("127.0.0.1", 1234), None)
    headers, result = connection.output.split(b"\r\n\r\n", 1)
    return int(headers.split()[1]), ([json.loads(line) for line in result.splitlines()]
                                  if b"application/x-ndjson" in headers else json.loads(result))


def post(payload, origin="http://localhost:8000", stream=False):
    body = json.dumps(payload).encode()
    accept = "application/x-ndjson" if stream else "application/json"
    return send(f"POST /api/ask HTTP/1.1\r\nHost: localhost:8000\r\nOrigin: {origin}\r\nAccept: {accept}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}", body)


class AppTests(unittest.TestCase):
    def test_invalid_and_cross_origin_requests_never_reach_model(self):
        too_long = "x" * (config.settings.max_question_chars + 1)
        with patch("app.__main__.answer") as model:
            for payload in ([], {}, {"question": " "}, {"question": 1}, {"question": too_long}):
                with self.subTest(payload=type(payload).__name__):
                    self.assertEqual(post(payload)[0], 400)
            self.assertEqual(post({"question": "demand?"}, "https://unrelated.example")[0], 403)
            model.assert_not_called()

    def test_meta_serves_the_limits_and_coverage_the_page_shows(self):
        status, meta = send("GET /api/meta HTTP/1.1\r\nHost: localhost:8000")
        self.assertEqual(status, 200)
        self.assertEqual(meta["max_question_chars"], config.settings.max_question_chars)
        self.assertEqual(meta["isos"], ["CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SPP"])
        self.assertEqual(meta["catalog_tables"], 65)
        self.assertEqual([p["id"] for p in meta["presets"]], [p["id"] for p in PRESETS])

    def test_answers_return_whole_or_as_a_progress_stream(self):
        result = {"state": "answered", "answer": "14 projects", "tool_calls": [
            {"query": "SELECT count(*)", "csv": "projects\n14\n", "rows": 1, "error": None},
        ]}
        def fake_answer(question, on_progress=None):
            self.assertEqual(question, PRESETS[2]["question"])
            if on_progress:
                for stage in ("gate", "route", "sql", "answer"):
                    on_progress({"stage": stage})
                on_progress({"answer_delta": "14 "})
                on_progress({"answer_delta": "projects"})
            return result

        for stream in (False, True):
            with (self.subTest(stream=stream),
                  patch("app.__main__.answer", side_effect=fake_answer),
                  patch.object(config, "settings", replace(config.settings, openai_api_key="test"))):
                status, body = post({"question": PRESETS[2]["question"]}, stream=stream)
                self.assertEqual(status, 200)
                if stream:
                    self.assertEqual([e["stage"] for e in body if "stage" in e], ["gate", "route", "sql", "answer"])
                    self.assertEqual("".join(e.get("answer_delta", "") for e in body), "14 projects")
                    self.assertEqual(body[-1]["type"], "done")
                    body = body[-1]["result"]
                self.assertNotIn("validation", body)
                self.assertEqual(body["tool_calls"][0]["csv"], "projects\n14\n")
