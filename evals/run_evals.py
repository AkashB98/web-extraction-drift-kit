"""Golden evals for web-extraction-drift-kit.

SYNTHETIC DATA ONLY (fictional Helios Home fixtures). Every eval is
deterministic: run_evals.py writes eval_report.json and the file must
be byte-identical across runs. No timestamps, ports, or temp paths
enter the report — only names, booleans, pinned counts and values.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tests"))

from cli import (EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main,  # noqa: E402
                 make_server)
from drift import diff_html, load_manifest, read_fixture, run_mutation  # noqa: E402
from extract import extract_html, parse_price  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(ROOT, "fixtures")
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def _suite_results():
    return {m["id"]: run_mutation(m) for m in load_manifest()}


def main():
    print("== golden evals: web-extraction-drift-kit ==")
    mutations = load_manifest()
    results = _suite_results()

    # E1: baseline extraction pinned on both page types.
    product = extract_html(read_fixture("product_baseline.html"), "product")
    pricing = extract_html(read_fixture("pricing_baseline.html"), "pricing")
    pf, rf = product["fields"], pricing["fields"]
    check("E1 baseline extraction pinned (product + pricing)",
          pf["price"]["value"] == 129900 and pf["stock"]["value"] == 42
          and pf["release_date"]["value"] == "2026-01-15"
          and pf["name"]["value"] == "Aurora Home Hub Pro"
          and rf["monthly_price"]["value"] == 2900
          and rf["annual_price"]["value"] == 29000
          and rf["seats"]["value"] == 10
          and rf["renewal_date"]["value"] == "2026-02-01"
          and all(e["found"] and e["error"] is None
                  for e in list(pf.values()) + list(rf.values())))

    # E2: the format trap — "$1,299.00" and "1.299 €" are the same
    # number of cents under different signatures; the diff must call
    # it format-changed, never silently accept or misparse it.
    usd, eur = parse_price("$1,299.00"), parse_price("1.299 €")
    d = results["PB4"]["diffs"][0]
    check("E2 price format trap (same cents, new format, flagged)",
          usd["value"] == eur["value"] == 129900
          and usd["format"] != eur["format"]
          and d["kind"] == "format-changed"
          and d["baseline_value"] == d["current_value"])

    # E3: HEADLINE — every breaking mutation caught, every silent
    # wrong-value case flagged silent, zero cosmetic false alarms.
    breaking = [m for m in mutations if m["category"] == "breaking"]
    cosmetic = [m for m in mutations if m["category"] == "cosmetic"]
    silent = [m for m in mutations if m["silent"]]
    caught = sum(1 for m in breaking if results[m["id"]]["has_breaking"])
    silent_caught = sum(1 for m in silent
                        if results[m["id"]]["silent_count"] >= 1)
    false_alarms = sum(1 for m in cosmetic
                       if results[m["id"]]["has_breaking"])
    check("E3 headline: 12/12 breaking caught, 3/3 silent flagged, "
          "0 cosmetic false alarms",
          len(breaking) == 12 and caught == 12
          and len(silent) == 3 and silent_caught == 3
          and len(cosmetic) == 6 and false_alarms == 0,
          f"breaking={caught}/{len(breaking)} "
          f"silent={silent_caught}/{len(silent)} "
          f"false_alarms={false_alarms}/{len(cosmetic)}")

    # E4: every breaking mutation's fields and kinds match its label
    # exactly — no extra noisy diffs, none missing.
    labelled = all(
        sorted(x["field"] for x in results[m["id"]]["diffs"])
        == sorted(m["expected_fields"])
        and sorted(x["kind"] for x in results[m["id"]]["diffs"])
        == sorted(m["expected_kinds"])
        for m in breaking)
    check("E4 labelled fields/kinds match exactly for all breaking",
          labelled)

    # E5: missing and type-changed stay distinct failure modes —
    # a removed node is found=False with no error; an unparseable
    # node is found=True with an error.
    removed = extract_html(read_fixture("product_b3_removed_field.html"),
                           "product")["fields"]["release_date"]
    typed = extract_html(read_fixture("pricing_b3_type_changed.html"),
                         "pricing")["fields"]["seats"]
    check("E5 missing (found=False) vs type-changed (error) distinct",
          removed["found"] is False and removed["error"] is None
          and typed["found"] is True and typed["error"] is not None
          and results["RB3"]["diffs"][0]["kind"] == "type-changed")

    # E6: CLI check exit codes 0 / 1 / 2.
    base = os.path.join(FIX, "product_baseline.html")
    codes = (
        _run_cli(["check", "--page", "product", "--baseline", base,
                  "--current", os.path.join(
                      FIX, "product_c1_whitespace.html")]),
        _run_cli(["check", "--page", "product", "--baseline", base,
                  "--current", os.path.join(
                      FIX, "product_b4_price_format.html")]),
        _run_cli(["check", "--page", "product", "--baseline", base,
                  "--current", "/tmp/no-such-page-xyz.html"]))
    check("E6 CLI check exit codes 0/1/2",
          codes == (EXIT_OK, EXIT_FAIL, EXIT_ERROR), f"codes={codes}")

    # E7: serve round-trip matches local extract + diff exactly.
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=10) as resp:
            health = json.loads(resp.read())
        html = read_fixture("pricing_baseline.html")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/extract",
            data=json.dumps({"page": "pricing", "html": html}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served_extract = json.loads(resp.read())
        cur = read_fixture("pricing_b5_silent_swap.html")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/diff",
            data=json.dumps({"page": "pricing", "baseline_html": html,
                             "current_html": cur}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served_diff = json.loads(resp.read())
        serve_ok = health == {"status": "ok"} \
            and served_extract == extract_html(html, "pricing") \
            and served_diff == diff_html(html, cur, "pricing")
    finally:
        server.shutdown()
        server.server_close()
    check("E7 serve round-trip matches local extract + diff", serve_ok)

    # E8: suite determinism — canonical JSON of all 18 mutation
    # results identical across two independent runs.
    r1 = json.dumps(_suite_results(), sort_keys=True)
    r2 = json.dumps(_suite_results(), sort_keys=True)
    check("E8 mutation-suite determinism (canonical JSON identical)",
          r1 == r2, f"suite_md5={hashlib.md5(r1.encode()).hexdigest()}")

    # E9: fixture inventory pinned — 20 HTML files, 18 labelled
    # mutations, both baselines diff-clean against themselves.
    html_files = sorted(f for f in os.listdir(FIX) if f.endswith(".html"))
    self_clean = all(
        not diff_html(read_fixture(b), read_fixture(b), page)["has_breaking"]
        for b, page in (("product_baseline.html", "product"),
                        ("pricing_baseline.html", "pricing")))
    check("E9 fixtures pinned (20 HTML, 18 mutations, baselines clean)",
          len(html_files) == 20 and len(mutations) == 18 and self_clean,
          f"html_files={len(html_files)} mutations={len(mutations)}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_count = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_count,
                   "all_passed": passed == total_count, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_count} evals passed -> evals/eval_report.json")
    return 0 if passed == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
