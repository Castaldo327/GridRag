"""Local demo server: python -m app [--port 8000]. No web framework required."""

import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gridrag import config
from gridrag.answer import answer, clean_question
from gridrag.catalog import demo_catalog
from gridrag.warehouse.evaluation import assess, case_info
from gridrag.warehouse.evals import CASES

PRESETS = [{"id": case.id, "label": case.label, "concept": case.concept, "question": case.question}
           for case in CASES if case.label]
STATIC = Path(__file__).parent / "static"
RUN_LOCK = threading.Lock()
MAX_BODY_BYTES = 16384
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/logo-mark.png": ("logo-mark.png", "image/png"),
}


class Handler(BaseHTTPRequestHandler):
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
            self.send(200, (STATIC / name).read_bytes(), content_type)
        elif path == "/api/meta":
            try:
                catalog = demo_catalog()
                self.send(200, {"catalog_tables": len(catalog.tables), "isos": list(catalog.isos),
                                "max_question_chars": config.settings.max_question_chars,
                                "model_ready": bool(config.settings.openai_api_key),
                                "presets": PRESETS,
                                "evaluation_cases": [case_info(case) for case in CASES]})
            except Exception:
                logging.exception("Could not load the catalog")
                self.send(503, {"error": "Catalog unavailable. See the server log for details."})
        else:
            self.send(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/evaluate":
            return self.do_evaluate()
        if self.path != "/api/ask":
            return self.send(404, {"error": "Not found"})
        # Accept same-origin JSON only; this local endpoint can make paid model calls.
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.send(403, {"error": "Cross-origin requests are not accepted"})
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self.send(415, {"error": "Expected application/json"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY_BYTES:
                raise ValueError()
            question = clean_question(json.loads(self.rfile.read(size)).get("question"))
        except (ValueError, AttributeError, UnicodeDecodeError):
            return self.send(400, {"error": f"Enter a question of 1–{config.settings.max_question_chars} characters"})
        if not config.settings.openai_api_key:
            return self.send(503, {"error": "Set OPENAI_API_KEY in the environment or .env to run a question."})
        if not RUN_LOCK.acquire(blocking=False):
            return self.send(409, {"error": "A question is already running. Try again when it finishes."})
        streaming = self.headers.get("Accept") == "application/x-ndjson"
        stream_started = False

        def emit(event):
            self.wfile.write((json.dumps(event) + "\n").encode())
            self.wfile.flush()

        try:
            if streaming:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                stream_started = True
                result = answer(question, on_progress=lambda update: emit({"type": "progress", **update}))
            else:
                result = answer(question)
            if streaming:
                emit({"type": "done", "result": result})
            else:
                self.send(200, result)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Demo request failed")
            error = "Could not complete the question. See the server log for details."
            if stream_started:
                emit({"type": "error", "error": error})
            else:
                self.send(500, {"error": error})
        finally:
            RUN_LOCK.release()

    def do_evaluate(self):
        """Run the shared live evaluation suite and stream each case as it finishes."""
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.send(403, {"error": "Cross-origin requests are not accepted"})
        if self.headers.get("Accept") != "application/x-ndjson":
            return self.send(406, {"error": "Expected application/x-ndjson"})
        if self.headers.get("Content-Length", "0") != "0":
            return self.send(400, {"error": "Evaluation requests must not include a body"})
        if not config.settings.openai_api_key:
            return self.send(503, {"error": "Set OPENAI_API_KEY in the environment or .env to run evaluations."})
        if not RUN_LOCK.acquire(blocking=False):
            return self.send(409, {"error": "A question is already running. Try again when it finishes."})

        def emit(event):
            self.wfile.write((json.dumps(event) + "\n").encode())
            self.wfile.flush()

        stream_started = False
        started = time.perf_counter()
        passed = 0
        cost = 0.0
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            stream_started = True
            for index, case in enumerate(CASES):
                emit({"type": "case_start", "index": index, "id": case.id})
                try:
                    result = answer(case.question, on_progress=lambda update: (
                        emit({"type": "case_progress", "index": index, "id": case.id,
                              "stage": update["stage"]}) if "stage" in update else None))
                    assessment = assess(case, result)
                    passed += assessment["passed"]
                    cost += result["usage"]["cost_usd"]
                    emit({"type": "case_done", "index": index, "assessment": assessment})
                except (BrokenPipeError, ConnectionResetError):
                    raise
                except Exception:
                    logging.exception("Evaluation case %s failed", case.id)
                    emit({"type": "case_error", "index": index, "id": case.id,
                          "error": "Could not complete this case. See the server log for details."})
            emit({"type": "done", "summary": {"passed": passed, "total": len(CASES),
                                               "cost_usd": round(cost, 6),
                                               "seconds": round(time.perf_counter() - started, 3)}})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Evaluation run failed")
            if stream_started:
                try:
                    emit({"type": "error", "error": "Evaluation stopped. See the server log for details."})
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send(500, {"error": "Evaluation could not start. See the server log for details."})
        finally:
            RUN_LOCK.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Grid History: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
