"""Local API contracts, without provider calls."""

import io
import json
import unittest
import tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from app.__main__ import PRESETS, Handler
from gridrag import config
from gridrag.warehouse.suite import EVALUATION_CASES as CASES
from gridrag.warehouse.evaluation import evaluation_question


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


def post(payload, origin="http://localhost:8000", stream=False, api_key=None):
    body = json.dumps(payload).encode()
    accept = "application/x-ndjson" if stream else "application/json"
    auth = f"Authorization: Bearer {api_key}\r\n" if api_key is not None else ""
    return send(f"POST /api/ask HTTP/1.1\r\nHost: localhost:8000\r\nOrigin: {origin}\r\nAccept: {accept}\r\n{auth}"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}", body)


def post_evaluation(origin="http://localhost:8000"):
    return send(f"POST /api/evaluate HTTP/1.1\r\nHost: localhost:8000\r\nOrigin: {origin}\r\n"
                "Accept: application/x-ndjson\r\nContent-Length: 0")


class AppTests(unittest.TestCase):
    def test_invalid_http_framing_and_nested_json_never_reach_model(self):
        body = b'{"question":"demand?"}'
        base = "POST /api/ask HTTP/1.1\r\nHost: localhost:8000\r\nContent-Type: application/json\r\n"
        requests = [
            ("Content-Length: -1", body),
            ("Content-Length: 999999", body),
            ("Content-Length: nope", body),
            (f"Content-Length: {len(body)+1}", body),
            (f"Content-Length: {len(body)}\r\nContent-Length: {len(body)}", body),
            (f"Content-Length: {len(body)}\r\nTransfer-Encoding: chunked", body),
            ("", body),
        ]
        nested = b'{"question":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'
        requests.append((f"Content-Length: {len(nested)}", nested))
        with patch("app.__main__.answer") as model:
            for headers, payload in requests:
                with self.subTest(headers=headers):
                    self.assertEqual(send(base + headers, payload)[0], 400)
            model.assert_not_called()

    def test_missing_optional_report_returns_a_clean_404(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.__main__.STATIC", Path(directory)):
            self.assertEqual(send("GET /static/benchmark.json HTTP/1.1\r\nHost: localhost:8000")[0], 404)

    def test_private_files_and_path_traversal_are_not_served(self):
        for path in ("/.env", "/.env.local", "/.git/config", "/.vercel/project.json",
                     "/data/warehouse.duckdb", "/static/../../.env"):
            with self.subTest(path=path):
                self.assertEqual(send(f"GET {path} HTTP/1.1\r\nHost: localhost:8000")[0], 404)

    def test_access_logs_exclude_request_urls_and_user_input(self):
        with self.assertLogs(level="INFO") as logs:
            Handler.log_message(None, "%s %s %s", "GET /?private-input HTTP/1.1", "200", "-")
        self.assertNotIn("private-input", "\n".join(logs.output))
        self.assertIn("200", "\n".join(logs.output))

    def test_public_demo_data_needs_no_key(self):
        with patch.object(config, "settings", replace(config.settings, openai_api_key=None)):
            status, data = send("GET /static/demo.json HTTP/1.1\r\nHost: localhost:8000")
        self.assertEqual(status, 200)
        self.assertEqual([demo["id"] for demo in data["demos"]], [case.id for case in CASES if case.label])
        for demo in data["demos"]:
            with self.subTest(example=demo["id"]):
                self.assertTrue(demo["answer"])
                self.assertIn(demo["unit"], demo["answer"])
                self.assertTrue(demo["evidence"])
                for table in demo["tables"]:
                    self.assertIn(table, demo["sql"])
        self.assertEqual(len(data["catalog"]), 65)
        self.assertNotIn("api_key", data)

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
        self.assertEqual([c["id"] for c in meta["evaluation_cases"]], [case.id for case in CASES])
        self.assertEqual(meta["evaluation_cases"][0]["expected_state"], "answered")
        self.assertIsInstance(meta["evaluation_cases"][0]["expected"], float)
        hard = next(c for c in meta["evaluation_cases"] if c["id"] == "spread_forecast_error")
        self.assertAlmostEqual(hard["expected"], -418.53)
        self.assertIn("09:00 UTC", hard["verification"])
        self.assertIsNone(meta["evaluation_cases"][-1]["expected"])
        self.assertNotIn("sql", meta["evaluation_cases"][0])

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

    def test_full_evaluation_stream_runs_every_shared_case(self):
        questions = []
        def fake_answer(question, on_progress=None):
            questions.append(question)
            on_progress({"stage": "gate"})
            return {"state": "answered", "answer": "example", "usage": {"cost_usd": 0.01},
                    "tool_calls": [], "timings": {"total": 0.1}}

        def fake_assess(case, result):
            return {"id": case.id, "passed": True, "checks": [], "result": result}

        with (patch("app.__main__.answer", side_effect=fake_answer),
              patch("app.__main__.assess", side_effect=fake_assess),
              patch.object(config, "settings", replace(config.settings, openai_api_key="test"))):
            status, events = post_evaluation()
        self.assertEqual(status, 200)
        self.assertEqual(questions, [evaluation_question(case) for case in CASES])
        self.assertEqual([event["id"] for event in events if event["type"] == "case_start"],
                         [case.id for case in CASES])
        self.assertEqual(len([event for event in events if event["type"] == "case_done"]), len(CASES))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["summary"]["passed"], len(CASES))
        self.assertAlmostEqual(events[-1]["summary"]["cost_usd"], len(CASES) * 0.01)

    def test_evaluation_rejects_cross_origin_and_missing_model(self):
        with patch("app.__main__.answer") as model:
            self.assertEqual(post_evaluation("https://unrelated.example")[0], 403)
            with patch.object(config, "settings", replace(config.settings, openai_api_key="")):
                self.assertEqual(post_evaluation()[0], 401)
            model.assert_not_called()

    def test_hosted_requests_require_a_visitor_key_even_with_an_owner_key(self):
        with (patch.object(Handler, "require_visitor_key", True),
              patch.object(config, "settings", replace(config.settings, openai_api_key="owner-secret")),
              patch("app.__main__.answer") as model):
            status, meta = send("GET /api/meta HTTP/1.1\r\nHost: localhost:8000")
            self.assertEqual(status, 200)
            self.assertFalse(meta["model_ready"])
            self.assertTrue(meta["requires_api_key"])
            self.assertNotIn("owner-secret", json.dumps(meta))
            self.assertEqual(post({"question": "demand?"}, "https://localhost:8000")[0], 401)
            self.assertEqual(post_evaluation("https://localhost:8000")[0], 401)
            model.assert_not_called()

    def test_visitor_credentials_are_request_scoped_and_clients_are_closed(self):
        with (patch.object(Handler, "require_visitor_key", True),
              patch("app.__main__.LLM") as factory,
              patch("app.__main__.answer", return_value={"state": "answered", "answer": "example"}) as model):
            for key in ("sk-first-visitor-key", "sk-second-visitor-key"):
                status, _ = post({"question": "demand?"}, "https://localhost:8000", api_key=key)
                self.assertEqual(status, 200)
                factory.assert_called_with(api_key=key)
                self.assertIs(model.call_args.kwargs["llm"], factory.return_value)
            self.assertEqual(factory.return_value.close.call_count, 2)
            self.assertEqual(post({"question": "demand?"}, "https://localhost:8000")[0], 401)
            self.assertEqual(model.call_count, 2)

    def test_invalid_keys_and_cross_origin_requests_do_not_reach_the_model(self):
        with patch("app.__main__.answer") as model:
            for key in ("bad", "sk-", "sk-" + "x" * 501, "sk-with spaces in it"):
                self.assertEqual(post({"question": "demand?"}, api_key=key)[0], 401)
            self.assertEqual(post({"question": "demand?"}, "https://elsewhere.example",
                                  api_key="sk-valid-shaped-test-key")[0], 403)
            model.assert_not_called()

    def test_one_evaluation_case_streams_using_the_visitor_key(self):
        body = json.dumps({"id": CASES[0].id}).encode()
        headers = ("POST /api/evaluate-case HTTP/1.1\r\nHost: localhost:8000\r\n"
                   "Origin: https://localhost:8000\r\nAuthorization: Bearer sk-visitor-test-key\r\n"
                   "Accept: application/x-ndjson\r\nContent-Type: application/json\r\n"
                   f"Content-Length: {len(body)}")
        def fake_answer(question, llm, on_progress):
            self.assertEqual(question, evaluation_question(CASES[0]))
            on_progress({"stage": "gate"})
            return {"usage": {"cost_usd": 0.01}}
        with (patch.object(Handler, "require_visitor_key", True),
              patch("app.__main__.LLM") as factory,
              patch("app.__main__.answer", side_effect=fake_answer),
              patch("app.__main__.assess", return_value={"id": CASES[0].id, "passed": True})):
            status, events = send(headers, body)
            self.assertEqual(status, 200)
            self.assertEqual(events[-1]["summary"]["total"], 1)
            self.assertEqual(events[-1]["summary"]["passed"], 1)
            factory.assert_called_once_with(api_key="sk-visitor-test-key")
            factory.return_value.close.assert_called_once()

    def test_bad_evaluation_case_is_rejected_before_model_calls(self):
        for payload in ({"id": "missing"}, {"id": "off_topic"}, {"id": "unrelated_task"}, [], {}):
            body = json.dumps(payload).encode()
            with patch("app.__main__.answer") as model:
                status, _ = send("POST /api/evaluate-case HTTP/1.1\r\nHost: localhost:8000\r\n"
                                 "Accept: application/x-ndjson\r\nContent-Type: application/json\r\n"
                                 f"Content-Length: {len(body)}", body)
                self.assertEqual(status, 400)
                model.assert_not_called()
