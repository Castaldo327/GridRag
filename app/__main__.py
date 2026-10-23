"""Local demo server: python -m app [--port 8000]. No web framework required."""

import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.presets import PRESETS, reference, validate
from gridrag.answer import answer
from gridrag.config import load_env
from gridrag.route import schema_blocks

STATIC = Path(__file__).parent / "static"
RUN_LOCK = threading.Lock()
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
                self.send(200, {"catalog_tables": len(schema_blocks()),
                                "model_ready": bool(load_env().get("OPEN_AI_KEY")),
                                "presets": [reference(p) for p in PRESETS]})
            except Exception:
                logging.exception("Could not load demo references")
                self.send(503, {"error": "Warehouse unavailable. Run python -m gridrag.warehouse.build, then retry."})
        else:
            self.send(404, {"error": "Not found"})

    def do_POST(self):
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
            if not 0 < size <= 16384:
                raise ValueError()
            payload = json.loads(self.rfile.read(size))
            question = payload.get("question")
            if not isinstance(question, str) or not 0 < len(question.strip()) <= 2000:
                raise ValueError()
            question = question.strip()
        except (ValueError, AttributeError, UnicodeDecodeError):
            return self.send(400, {"error": "Enter a question of 1–2000 characters"})
        if not load_env().get("OPEN_AI_KEY"):
            return self.send(503, {"error": "Set OPENAI_API_KEY in the environment or .env to run a question."})
        if not RUN_LOCK.acquire(blocking=False):
            return self.send(409, {"error": "A question is already running. Try again when it finishes."})
        streaming = self.headers.get("Accept") == "application/x-ndjson"
        stream_started = False

        def emit(event):
            self.wfile.write((json.dumps(event) + "\n").encode())
            self.wfile.flush()

        try:
            # Resolve expected values independently, and never put them into the model prompt.
            preset = next((p for p in PRESETS if p["question"] == question), None)
            expected = reference(preset) if preset else None
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
            if expected:
                result["validation"] = validate(result, expected)
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
