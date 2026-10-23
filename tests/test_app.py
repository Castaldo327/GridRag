"""Local API contracts and honest reference validation, without provider calls."""

import io
import json
import unittest
from unittest.mock import patch

from app.__main__ import Handler
from app.presets import PRESETS, validate


def post(payload, origin="http://localhost:8000", stream=False):
    body = json.dumps(payload).encode()
    accept = "application/x-ndjson" if stream else "application/json"
    request = (f"POST /api/ask HTTP/1.1\r\nHost: localhost:8000\r\nOrigin: {origin}\r\n"
               f"Accept: {accept}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body

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


class AppTests(unittest.TestCase):
    def test_invalid_and_cross_origin_requests_never_reach_model(self):
        with patch("app.__main__.answer") as model:
            for payload in ([], {}, {"question": " "}, {"question": 1}, {"question": "x" * 2001}):
                with self.subTest(payload=type(payload).__name__):
                    self.assertEqual(post(payload)[0], 400)
            self.assertEqual(post({"question": "demand?"}, "https://unrelated.example")[0], 403)
            model.assert_not_called()

    def test_preset_api_keeps_reference_out_of_model_input(self):
        result = {"state": "answered", "answer": "14 projects", "tool_calls": [
            {"query": "SELECT count(*)", "csv": "projects\n14\n", "rows": 1, "error": None},
        ]}
        reference = {"expected": 14, "unit": "projects", "tolerance": 0}
        def fake_answer(question, on_progress=None):
            self.assertEqual(question, PRESETS[2]["question"])
            if on_progress:
                for stage in ("gate", "route", "sql", "answer"):
                    on_progress({"stage": stage})
            return result

        for stream in (False, True):
            with (self.subTest(stream=stream),
                  patch("app.__main__.answer", side_effect=fake_answer),
                  patch("app.__main__.reference", return_value=reference),
                  patch("app.__main__.load_env", return_value={"OPEN_AI_KEY": "test"})):
                status, body = post({"question": PRESETS[2]["question"]}, stream=stream)
                self.assertEqual(status, 200)
                if stream:
                    self.assertEqual([e["stage"] for e in body[:-1]], ["gate", "route", "sql", "answer"])
                    self.assertEqual(body[-1]["type"], "done")
                    body = body[-1]["result"]
                self.assertEqual(body["validation"]["status"], "match")
                self.assertEqual(body["tool_calls"][0]["csv"], "projects\n14\n")

    def test_mismatch_or_missing_evidence_requires_review(self):
        expected = {"expected": -1.09, "unit": "USD/MWh", "tolerance": .01}
        for result in (
            {"state": "answered", "answer": "-1.09", "tool_calls": []},
            {"state": "answered", "tool_calls": [{"csv": "value\n1.09\n"}]},
            {"state": "answered", "tool_calls": [{"csv": "value\n-1.09\n"}, {"csv": "value\n2\n"}]},
            {"state": "failed", "tool_calls": [{"csv": "value\n-1.09\n"}]},
        ):
            with self.subTest(result=result):
                self.assertEqual(validate(result, expected)["status"], "review")
