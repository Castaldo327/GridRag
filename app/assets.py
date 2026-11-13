"""Approved public assets shared by the local server and deployment build."""

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/demo.json": ("demo.json", "application/json; charset=utf-8"),
    "/static/benchmark.json": ("benchmark.json", "application/json; charset=utf-8"),
    "/static/logo-mark.png": ("logo-mark.png", "image/png"),
    "/static/stream.js": ("stream.js", "text/javascript; charset=utf-8"),
    "/static/energy-mark.svg": ("energy-mark.svg", "image/svg+xml"),
    "/static/architecture.svg": ("architecture.svg", "image/svg+xml"),
    "/static/vendor/marked.umd.js": ("vendor/marked.umd.js", "text/javascript; charset=utf-8"),
    "/static/vendor/purify.min.js": ("vendor/purify.min.js", "text/javascript; charset=utf-8"),
}
