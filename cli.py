"""CLI: extract | diff | check | demo | serve.

SYNTHETIC DATA ONLY — Helios Home is a fictional store and every page
handled here is a saved sample fixture. Nothing is fetched, ever.

Exit codes:
  check : 0 = no breaking drift, 1 = breaking drift found,
          2 = usage / IO error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drift import diff_extractions  # noqa: E402
from extract import PAGE_TYPES, extract_html  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _extract_or_error(path: str, page: str):
    text = _read(path)
    if text is None:
        return None
    try:
        return extract_html(text, page)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def cmd_extract(args) -> int:
    result = _extract_or_error(args.input, args.page)
    if result is None:
        return EXIT_ERROR
    print(canonical(result))
    return EXIT_OK


def _diff_or_error(args):
    baseline = _extract_or_error(args.baseline, args.page)
    if baseline is None:
        return None
    current = _extract_or_error(args.current, args.page)
    if current is None:
        return None
    return diff_extractions(baseline, current)


def cmd_diff(args) -> int:
    result = _diff_or_error(args)
    if result is None:
        return EXIT_ERROR
    print(canonical(result))
    return EXIT_OK


def cmd_check(args) -> int:
    result = _diff_or_error(args)
    if result is None:
        return EXIT_ERROR
    print(f"page={result['page']} breaking={result['breaking_count']} "
          f"silent={result['silent_count']}")
    for d in result["diffs"]:
        print(f"  {d['severity'].upper()} {d['field']}: {d['kind']} "
              f"({d['baseline_raw']!r} -> {d['current_raw']!r})")
    if result["has_breaking"]:
        print("check FAIL: breaking drift detected")
        return EXIT_FAIL
    print("check PASS: no breaking drift")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: Any) -> None:
        body = (canonical(payload) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw.strip() else {}
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/extract", "/diff"):
            return self._send_json(404, {"error": "unknown endpoint"})
        try:
            body = self._body()
            page = body["page"]
            if self.path == "/extract":
                result = extract_html(body["html"], page)
            else:
                result = diff_extractions(
                    extract_html(body["baseline_html"], page),
                    extract_html(body["current_html"], page))
            return self._send_json(200, result)
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  "
          f"(POST /extract, POST /diff, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="web-extraction-drift-kit",
        description="Extract saved HTML pages into a strict schema "
                    "and detect structure drift (Helios Home samples).")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="extract one saved page")
    e.add_argument("--page", required=True, choices=PAGE_TYPES)
    e.add_argument("--input", required=True)
    e.set_defaults(func=cmd_extract)

    d = sub.add_parser("diff", help="field-level drift diff")
    d.add_argument("--page", required=True, choices=PAGE_TYPES)
    d.add_argument("--baseline", required=True)
    d.add_argument("--current", required=True)
    d.set_defaults(func=cmd_diff)

    c = sub.add_parser("check", help="CI gate: exit 0 clean / 1 breaking / 2 error")
    c.add_argument("--page", required=True, choices=PAGE_TYPES)
    c.add_argument("--baseline", required=True)
    c.add_argument("--current", required=True)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON API")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
