import io
import json
import os
import sys
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main, make_server
from drift import diff_html
from extract import extract_html
from helpers import FIX, fixture


def _run(argv):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = cli_main(argv)
    return code, out.getvalue()


def _path(name):
    return os.path.join(FIX, name)


class TestCli(unittest.TestCase):
    def test_extract_command(self):
        code, text = _run(["extract", "--page", "product",
                           "--input", _path("product_baseline.html")])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(text)
        self.assertEqual(payload["fields"]["price"]["value"], 129900)

    def test_extract_missing_file_is_error(self):
        code, _ = _run(["extract", "--page", "product",
                        "--input", "/tmp/no-such-page-xyz.html"])
        self.assertEqual(code, EXIT_ERROR)

    def test_diff_command_matches_local(self):
        code, text = _run(["diff", "--page", "pricing",
                           "--baseline", _path("pricing_baseline.html"),
                           "--current", _path("pricing_b5_silent_swap.html")])
        self.assertEqual(code, EXIT_OK)
        expected = diff_html(fixture("pricing_baseline.html"),
                             fixture("pricing_b5_silent_swap.html"),
                             "pricing")
        self.assertEqual(json.loads(text), expected)

    def test_check_exit_codes(self):
        base = _path("product_baseline.html")
        code, _ = _run(["check", "--page", "product", "--baseline", base,
                        "--current", _path("product_c2_unrelated_copy.html")])
        self.assertEqual(code, EXIT_OK)
        code, _ = _run(["check", "--page", "product", "--baseline", base,
                        "--current", _path("product_b1_renamed_class.html")])
        self.assertEqual(code, EXIT_FAIL)
        code, _ = _run(["check", "--page", "product", "--baseline", base,
                        "--current", "/tmp/no-such-page-xyz.html"])
        self.assertEqual(code, EXIT_ERROR)


class TestServe(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _req(self, path, payload=None, method="GET"):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health(self):
        status, body = self._req("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_post_extract_matches_local(self):
        html = fixture("pricing_baseline.html")
        status, body = self._req("/extract", {"page": "pricing",
                                              "html": html}, method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body, extract_html(html, "pricing"))

    def test_post_diff_matches_local(self):
        base = fixture("product_baseline.html")
        cur = fixture("product_b4_price_format.html")
        status, body = self._req(
            "/diff", {"page": "product", "baseline_html": base,
                      "current_html": cur}, method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(body, diff_html(base, cur, "product"))

    def test_unknown_endpoint_404(self):
        status, _ = self._req("/nope")
        self.assertEqual(status, 404)
        status, _ = self._req("/extract")  # GET not supported
        self.assertEqual(status, 404)

    def test_unknown_page_400(self):
        status, body = self._req("/extract", {"page": "checkout",
                                              "html": "<p>x</p>"},
                                 method="POST")
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
