"""Local demo server: python -m app [--port 8000]. No web framework required."""

import argparse
import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.assets import ASSETS
from app.metadata import evaluation_metadata, presets
from gridrag import config
from gridrag.answer import answer, clean_question
from gridrag.catalog import demo_catalog
from gridrag.llm import LLM
from gridrag.warehouse.evaluation import assess, evaluation_question
from gridrag.warehouse.suite import EVALUATION_CASES as CASES

PRESETS = presets()
STATIC = Path(__file__).parent / "static"
RUN_LOCK = threading.Lock()
MAX_BODY_BYTES = 16384


class Handler(BaseHTTPRequestHandler):
    timeout = 30  # Bound slow/incomplete request bodies and stalled response writes.
    # Hosting always requires a visitor key, even if an owner key is configured.
    require_visitor_key = os.environ.get("VERCEL") == "1"

    def log_message(self, format, *args):
        # Request URLs may contain user data; access logs contain only status codes.
        if len(args) >= 2 and str(args[1]).isdigit():
            logging.info("HTTP status %s", args[1])

    def same_origin(self):
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1:
            return False
        origin = origins[0] if origins else None
        schemes = ("https",) if self.require_visitor_key else ("http", "https")
        return not origin or origin in {f"{scheme}://{self.headers.get('Host')}" for scheme in schemes}

    def authorize_model(self):
        authorizations = self.headers.get_all("Authorization", [])
        self.visitor_key = None
        if len(authorizations) > 1:
            self.send(401, {"error": "Expected one Authorization header."})
            return False
        authorization = authorizations[0] if authorizations else ""
        if authorization:
            match = re.fullmatch(r"Bearer (sk-[A-Za-z0-9_-]{10,500})", authorization)
            if not match:
                self.send(401, {"error": "Enter a valid OpenAI API key and try again."})
                return False
            self.visitor_key = match[1]
        if not self.visitor_key and (self.require_visitor_key or not config.settings.openai_api_key):
            self.send(401, {"error": "Add your OpenAI API key to ask a live question."})
            return False
        return True

    def read_json(self):
        """Accept one bounded, complete JSON body with unambiguous HTTP framing."""
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise ValueError("Expected one Content-Length")
        if not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
            raise ValueError("Invalid Content-Length")
        size = int(lengths[0])
        if not 0 < size <= MAX_BODY_BYTES:
            raise ValueError("Body too large")
        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError("Incomplete body")
        try:
            payload = json.loads(body)
        except RecursionError as exc:
            raise ValueError("JSON nesting too deep") from exc
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def run_answer(self, question, on_progress=None):
        if not self.visitor_key:
            return answer(question, on_progress=on_progress)
        model = LLM(api_key=self.visitor_key)
        try:
            return answer(question, llm=model, on_progress=on_progress)
        finally:
            model.close()

    def send(self, status, body, content_type="application/json"):
        data = json.dumps(body).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ASSETS:
            name, content_type = ASSETS[path]
            asset = STATIC / name
            if not asset.is_file():
                return self.send(404, {"error": "Asset not available"})
            self.send(200, asset.read_bytes(), content_type)
        elif path == "/api/meta":
            try:
                catalog = demo_catalog()
                self.send(
                    200,
                    {
                        "catalog_tables": len(catalog.tables),
                        "isos": list(catalog.isos),
                        "max_question_chars": config.settings.max_question_chars,
                        "model_ready": bool(config.settings.openai_api_key) and not self.require_visitor_key,
                        "requires_api_key": self.require_visitor_key,
                        "models": {
                            "decisions": config.settings.decisions_model,
                            "answer": config.settings.answer_model,
                        },
                        "presets": PRESETS,
                        **evaluation_metadata(CASES),
                    },
                )
            except Exception:
                logging.error("Could not load the catalog")
                self.send(503, {"error": "Catalog unavailable. See the server log for details."})
        else:
            self.send(404, {"error": "Not found"})

    def do_POST(self):
        if self.path in {"/api/evaluate", "/api/evaluate-case"}:
            return self.do_evaluate()
        if self.path != "/api/ask":
            return self.send(404, {"error": "Not found"})
        # Accept same-origin JSON only; this local endpoint can make paid model calls.
        if not self.same_origin():
            return self.send(403, {"error": "Cross-origin requests are not accepted"})
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self.send(415, {"error": "Expected application/json"})
        try:
            question = clean_question(self.read_json().get("question"))
        except TimeoutError:
            return self.send(408, {"error": "Request body timed out. Please retry."})
        except (ValueError, AttributeError, UnicodeDecodeError):
            return self.send(400, {"error": f"Enter a question of 1–{config.settings.max_question_chars} characters"})
        if not self.authorize_model():
            return
        streaming = self.headers.get("Accept") == "application/x-ndjson"
        self.execute_request(
            lambda: self.answer_question(question, streaming),
            streaming=streaming,
            failure_message="Could not complete the question. See the server log for details.",
            label="Demo request failed",
        )

    def emit(self, event):
        self.wfile.write((json.dumps(event) + "\n").encode())
        self.wfile.flush()

    def start_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def send_failure(self, message, stream_started):
        try:
            if stream_started:
                self.emit({"type": "error", "error": message})
            else:
                self.send(500, {"error": message})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def execute_request(self, action, *, streaming, failure_message, label):
        """Own admission, response framing, disconnect handling, and lock release."""
        if not RUN_LOCK.acquire(blocking=False):
            return self.send(409, {"error": "A question is already running. Try again when it finishes."})
        stream_started = False
        try:
            if streaming:
                self.start_stream()
                stream_started = True
            action()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            # Log a diagnostic type, never a provider exception body or visitor credentials.
            logging.error("%s (%s)", label, type(exc).__name__)
            self.send_failure(failure_message, stream_started)
        finally:
            RUN_LOCK.release()

    def answer_question(self, question, streaming):
        progress = (lambda update: self.emit({"type": "progress", **update})) if streaming else None
        result = self.run_answer(question, on_progress=progress)
        if streaming:
            self.emit({"type": "done", "result": result})
        else:
            self.send(200, result)

    def do_evaluate(self):
        """Run the shared live evaluation suite and stream each case as it finishes."""
        if not self.same_origin():
            return self.send(403, {"error": "Cross-origin requests are not accepted"})
        if self.headers.get("Accept") != "application/x-ndjson":
            return self.send(406, {"error": "Expected application/x-ndjson"})
        cases = CASES
        if self.path == "/api/evaluate-case":
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                return self.send(415, {"error": "Expected application/json"})
            try:
                case_id = self.read_json().get("id")
                cases = tuple(case for case in CASES if case.id == case_id)
                if not cases:
                    raise ValueError()
            except TimeoutError:
                return self.send(408, {"error": "Request body timed out. Please retry."})
            except (ValueError, AttributeError, UnicodeDecodeError):
                return self.send(400, {"error": "Choose a valid evaluation case."})
        elif self.headers.get("Transfer-Encoding") or self.headers.get_all("Content-Length", ["0"]) != ["0"]:
            return self.send(400, {"error": "Evaluation requests must not include a body"})
        if not self.authorize_model():
            return
        self.execute_request(
            lambda: self.evaluate_cases(cases),
            streaming=True,
            failure_message="Evaluation stopped. See the server log for details.",
            label="Evaluation run failed",
        )

    def evaluate_case(self, index, case):
        def progress(update):
            if "stage" in update:
                self.emit({"type": "case_progress", "index": index, "id": case.id, "stage": update["stage"]})

        self.emit({"type": "case_start", "index": index, "id": case.id})
        try:
            result = self.run_answer(evaluation_question(case), on_progress=progress)
            assessment = assess(case, result)
            outcome = assessment["passed"], result["usage"]["cost_usd"]
            self.emit({"type": "case_done", "index": index, "assessment": assessment})
            return outcome
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as exc:
            logging.error("Evaluation case %s failed (%s)", case.id, type(exc).__name__)
            self.emit(
                {
                    "type": "case_error",
                    "index": index,
                    "id": case.id,
                    "error": "Could not complete this case. See the server log for details.",
                }
            )
            return False, 0.0

    def evaluate_cases(self, cases):
        """Keep case failures independent while accumulating the full-suite denominator."""
        started = time.perf_counter()
        passed, cost = 0, 0.0
        for index, case in enumerate(cases):
            case_passed, case_cost = self.evaluate_case(index, case)
            passed += case_passed
            cost += case_cost
        self.emit(
            {
                "type": "done",
                "summary": {
                    "passed": passed,
                    "total": len(cases),
                    "cost_usd": round(cost, 6),
                    "seconds": round(time.perf_counter() - started, 3),
                },
            }
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"GridRag: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
