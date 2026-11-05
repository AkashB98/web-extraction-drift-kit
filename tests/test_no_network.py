"""No-network enforcement: with sockets blocked, extracting,
diffing and running the whole mutation suite must still work.
(``serve`` is the only intentional exception — it binds loopback
on demand, and is not used here.)"""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from drift import load_manifest, run_mutation
        from extract import extract_html
        from helpers import fixture
        result = extract_html(fixture("product_baseline.html"), "product")
        self.assertEqual(result["fields"]["price"]["value"], 129900)
        for m in load_manifest():
            outcome = run_mutation(m)
            self.assertEqual(outcome["has_breaking"],
                             m["category"] == "breaking", m["id"])

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("extract", "drift", "cli", "demo"):
            sys.modules.pop(mod, None)
        import cli, demo, drift, extract  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
