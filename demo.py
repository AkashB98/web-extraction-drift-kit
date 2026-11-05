"""End-to-end demo: extract -> diff every labelled mutation -> check
exit codes -> live localhost serve round-trip.

SYNTHETIC DATA ONLY (fictional Helios Home fixtures). Runs fully
offline except the loopback serve round-trip on an ephemeral port.
Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main, make_server  # noqa: E402
from drift import load_manifest, read_fixture, run_mutation  # noqa: E402
from extract import extract_html  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    print("== 1. extract the two baselines (strict typed schema) ==")
    product = extract_html(read_fixture("product_baseline.html"), "product")
    pricing = extract_html(read_fixture("pricing_baseline.html"), "pricing")
    pf = product["fields"]
    assert pf["price"]["value"] == 129900, pf["price"]
    assert pf["price"]["raw"] == "$1,299.00"
    assert pf["stock"]["value"] == 42
    assert pf["release_date"]["value"] == "2026-01-15"
    assert pricing["fields"]["monthly_price"]["value"] == 2900
    assert pricing["fields"]["seats"]["value"] == 10
    print("   product price $1,299.00 -> 129900 cents; stock 42; "
          "release 2026-01-15; pricing seats 10")

    print("\n== 2. run the labelled mutation suite ==")
    mutations = load_manifest()
    breaking = [m for m in mutations if m["category"] == "breaking"]
    cosmetic = [m for m in mutations if m["category"] == "cosmetic"]
    caught = silent_caught = 0
    for m in breaking:
        result = run_mutation(m)
        assert result["has_breaking"], f"{m['id']} not caught"
        caught += 1
        if m["silent"]:
            assert result["silent_count"] >= 1, f"{m['id']} not silent-flagged"
            silent_caught += 1
        kinds = ", ".join(d["kind"] for d in result["diffs"])
        print(f"   {m['id']} CAUGHT  {m['label']} [{kinds}]")
    false_alarms = 0
    for m in cosmetic:
        result = run_mutation(m)
        if result["has_breaking"]:
            false_alarms += 1
        print(f"   {m['id']} quiet   {m['label']}")
    assert false_alarms == 0
    print(f"   headline: {caught}/{len(breaking)} breaking caught "
          f"({silent_caught} silent wrong-value cases), "
          f"{false_alarms} false alarms on {len(cosmetic)} cosmetic")

    print("\n== 3. CLI check gate exit codes ==")
    base = os.path.join(FIX, "product_baseline.html")
    clean = cli_main(["check", "--page", "product", "--baseline", base,
                      "--current", os.path.join(FIX, "product_c1_whitespace.html")])
    drifted = cli_main(["check", "--page", "product", "--baseline", base,
                        "--current", os.path.join(FIX, "product_b4_price_format.html")])
    error = cli_main(["check", "--page", "product", "--baseline", base,
                      "--current", "/tmp/no-such-page-xyz.html"])
    print(f"   clean={clean} breaking={drifted} missing-file={error}")
    assert (clean, drifted, error) == (EXIT_OK, EXIT_FAIL, EXIT_ERROR)

    print("\n== 4. live localhost serve round-trip ==")
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, health = _request(port, "/health")
        assert status == 200 and health == {"status": "ok"}
        html = read_fixture("product_baseline.html")
        status, served = _request(port, "/extract",
                                  {"page": "product", "html": html},
                                  method="POST")
        assert status == 200 and served == product
        status, served_diff = _request(
            port, "/diff",
            {"page": "product", "baseline_html": html,
             "current_html": read_fixture("product_b6_silent_price_move.html")},
            method="POST")
        assert status == 200 and served_diff["has_breaking"] \
            and served_diff["silent_count"] == 1
        print("   POST /extract matches local; POST /diff flags the "
              "silent price move")
    finally:
        server.shutdown()
        server.server_close()

    print("\nDemo OK: extract, drift suite, check gate and serve verified.")


if __name__ == "__main__":
    main()
