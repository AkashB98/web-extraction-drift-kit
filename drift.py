"""Field-level drift diff between two extractions of the same page.

SYNTHETIC DATA ONLY (fictional Helios Home fixtures).

Kinds:
  missing         — baseline field no longer found (renamed hook,
                    removed node, or node moved out of its scope)
  type-changed    — node still found, but its text no longer parses
                    as the declared type (e.g. an int field now reads
                    "unlimited")
  format-changed  — node parses, but under a different format
                    signature (``$1,299.00`` -> ``1.299 €``; an ISO
                    date -> ``15/01/2026``). The value may even be
                    numerically identical; the *format* moved, which
                    is exactly what breaks downstream parsers silently.
  value-changed   — node parses cleanly, same format, different
                    value. Flagged ``silent=True``: a naive extractor
                    would return this plausible-looking wrong value
                    with no error at all.

Every field-level drift above is severity ``breaking``. A pair of
pages with no field drift is clean — cosmetic page changes
(whitespace, unrelated copy, attribute order) never reach the field
level, so they produce an empty diff and cannot false-alarm.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from extract import extract_html

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fixtures")


def diff_extractions(baseline: Dict[str, Any],
                     current: Dict[str, Any]) -> Dict[str, Any]:
    if baseline["page"] != current["page"]:
        raise ValueError("cannot diff different page types: "
                         f"{baseline['page']!r} vs {current['page']!r}")
    diffs: List[Dict[str, Any]] = []
    for name in sorted(baseline["fields"]):
        b = baseline["fields"][name]
        c = current["fields"][name]
        entry = None
        if b["found"] and not c["found"]:
            entry = {"field": name, "kind": "missing",
                     "severity": "breaking", "silent": False}
        elif b["found"] and c["found"]:
            if c["error"] is not None:
                if c["format"] is not None and c["format"] != b["format"]:
                    kind = "format-changed"
                else:
                    kind = "type-changed"
                entry = {"field": name, "kind": kind,
                         "severity": "breaking", "silent": False}
            elif c["format"] != b["format"]:
                entry = {"field": name, "kind": "format-changed",
                         "severity": "breaking", "silent": False}
            elif c["value"] != b["value"]:
                entry = {"field": name, "kind": "value-changed",
                         "severity": "breaking", "silent": True}
        if entry is not None:
            entry["baseline_value"] = b["value"]
            entry["current_value"] = c["value"]
            entry["baseline_raw"] = b["raw"]
            entry["current_raw"] = c["raw"]
            diffs.append(entry)
    breaking = [d for d in diffs if d["severity"] == "breaking"]
    return {"page": baseline["page"],
            "has_breaking": bool(breaking),
            "breaking_count": len(breaking),
            "silent_count": sum(1 for d in breaking if d["silent"]),
            "diffs": diffs}


def diff_html(baseline_html: str, current_html: str,
              page: str) -> Dict[str, Any]:
    return diff_extractions(extract_html(baseline_html, page),
                            extract_html(current_html, page))


def read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def load_manifest() -> List[Dict[str, Any]]:
    with open(os.path.join(FIXTURE_DIR, "manifest.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["mutations"]


def run_mutation(mutation: Dict[str, Any]) -> Dict[str, Any]:
    """Run one labelled mutation: diff its file against its baseline."""
    result = diff_html(read_fixture(mutation["baseline"]),
                       read_fixture(mutation["file"]),
                       mutation["page"])
    result["mutation_id"] = mutation["id"]
    return result
