"""Declarative HTML extraction with strict typed parsing.

SYNTHETIC DATA ONLY — every fixture is a saved page for the fictional
Helios Home store. This module never fetches anything: it parses HTML
text it is handed, using only ``html.parser`` from the stdlib.

A schema declares, per field, where the value lives (an ``id`` hook or
a ``class`` hook, optionally scoped inside a container ``id``) and its
type (``string`` / ``int`` / ``price`` / ``date``). Parsing is strict:
a price must match a recognised currency format exactly, and the
recognised format is recorded as a *format signature* so a later diff
can tell "same value, new format" (``1.299 €``) apart from a value
that merely changed — instead of silently misparsing either.
"""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- schemas

SCHEMAS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "product": {
        "name": {"type": "string", "by": "id", "value": "product-name",
                 "within": "product-main"},
        # The price hook is deliberately document-wide first-match: the
        # fictional template reuses class="price" for related items,
        # which is exactly the fragility the drift diff exists to catch.
        "price": {"type": "price", "by": "class", "value": "price",
                  "within": None},
        "sku": {"type": "string", "by": "id", "value": "sku",
                "within": "product-main"},
        "stock": {"type": "int", "by": "class", "value": "stock-count",
                  "within": "product-main"},
        "release_date": {"type": "date", "by": "id",
                         "value": "release-date", "within": "product-main"},
    },
    "pricing": {
        "plan_name": {"type": "string", "by": "id", "value": "plan-name",
                      "within": "pricing-main"},
        "monthly_price": {"type": "price", "by": "id",
                          "value": "monthly-price", "within": "pricing-main"},
        "annual_price": {"type": "price", "by": "id",
                         "value": "annual-price", "within": "pricing-main"},
        "seats": {"type": "int", "by": "id", "value": "seats-included",
                  "within": "pricing-main"},
        "renewal_date": {"type": "date", "by": "id",
                         "value": "renewal-date", "within": "pricing-main"},
    },
}

PAGE_TYPES = sorted(SCHEMAS)


def get_schema(page: str) -> Dict[str, Dict[str, Any]]:
    if page not in SCHEMAS:
        raise ValueError(f"unknown page type: {page!r} "
                         f"(expected one of {PAGE_TYPES})")
    return SCHEMAS[page]


# ------------------------------------------------------------- DOM builder

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "source", "track", "wbr"}


class _Node:
    __slots__ = ("tag", "attrs", "children", "text_parts")

    def __init__(self, tag: str, attrs: Dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: List["_Node"] = []
        self.text_parts: List[str] = []

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).split())


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("[document]", {})
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        self._stack[-1].text_parts.append(data)


def parse_html(html_text: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(html_text)
    builder.close()
    return builder.root


def _walk(node: _Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _find_first(root: _Node, hook: Dict[str, Any]) -> Optional[_Node]:
    scope = root
    within = hook.get("within")
    if within:
        scope = None
        for node in _walk(root):
            if node.attrs.get("id") == within:
                scope = node
                break
        if scope is None:
            return None
    for node in _walk(scope):
        if hook["by"] == "id" and node.attrs.get("id") == hook["value"]:
            return node
        if hook["by"] == "class" and \
                hook["value"] in (node.attrs.get("class") or "").split():
            return node
    return None


# ------------------------------------------------------------ typed parsing

_USD_RE = re.compile(r"^\$(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})$")
_EUR_DOT_RE = re.compile(r"^(\d{1,3}(?:\.\d{3})+|\d+)\s*€$")
_EUR_COMMA_RE = re.compile(r"^(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*€$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EU_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_US_LONG_DATE_RE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
_INT_PLAIN_RE = re.compile(r"^-?\d+$")
_INT_COMMA_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})+$")


def parse_price(raw: str) -> Dict[str, Any]:
    """Return {value_cents, format, error}. Recognised non-USD formats
    parse to a value AND keep their own signature, so the diff flags
    the format change instead of silently accepting the number."""
    m = _USD_RE.match(raw)
    if m:
        dollars = int(m.group(1).replace(",", ""))
        return {"value": dollars * 100 + int(m.group(2)),
                "format": "USD|prefix-$|thousands=,|decimal=.",
                "error": None}
    m = _EUR_DOT_RE.match(raw)
    if m:
        euros = int(m.group(1).replace(".", ""))
        return {"value": euros * 100,
                "format": "EUR|suffix-euro|thousands=.|decimal=none",
                "error": None}
    m = _EUR_COMMA_RE.match(raw)
    if m:
        euros = int(m.group(1).replace(".", ""))
        return {"value": euros * 100 + int(m.group(2)),
                "format": "EUR|suffix-euro|thousands=.|decimal=,",
                "error": None}
    return {"value": None, "format": None,
            "error": f"unparseable price: {raw!r}"}


def parse_date(raw: str) -> Dict[str, Any]:
    if _ISO_DATE_RE.match(raw):
        try:
            datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return {"value": None, "format": None,
                    "error": f"invalid ISO date: {raw!r}"}
        return {"value": raw, "format": "ISO|YYYY-MM-DD", "error": None}
    m = _EU_DATE_RE.match(raw)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        try:
            parsed = datetime.strptime(f"{year}-{month}-{day}",
                                       "%Y-%m-%d")
        except ValueError:
            return {"value": None, "format": None,
                    "error": f"invalid EU date: {raw!r}"}
        return {"value": parsed.strftime("%Y-%m-%d"),
                "format": "EU|DD/MM/YYYY", "error": None}
    m = _US_LONG_DATE_RE.match(raw)
    if m:
        try:
            parsed = datetime.strptime(raw, "%b %d, %Y")
        except ValueError:
            return {"value": None, "format": None,
                    "error": f"invalid US long date: {raw!r}"}
        return {"value": parsed.strftime("%Y-%m-%d"),
                "format": "US_LONG|Mon D, YYYY", "error": None}
    return {"value": None, "format": None,
            "error": f"unparseable date: {raw!r}"}


def parse_int(raw: str) -> Dict[str, Any]:
    if _INT_PLAIN_RE.match(raw):
        return {"value": int(raw), "format": "int|plain", "error": None}
    if _INT_COMMA_RE.match(raw):
        return {"value": int(raw.replace(",", "")),
                "format": "int|comma-thousands", "error": None}
    return {"value": None, "format": None,
            "error": f"unparseable int: {raw!r}"}


_PARSERS = {"price": parse_price, "date": parse_date, "int": parse_int}


def _parse_typed(field_type: str, raw: str) -> Dict[str, Any]:
    if field_type == "string":
        if raw == "":
            return {"value": None, "format": None,
                    "error": "empty string field"}
        return {"value": raw, "format": "text|plain", "error": None}
    return _PARSERS[field_type](raw)


# --------------------------------------------------------------- extraction

def extract_html(html_text: str, page: str) -> Dict[str, Any]:
    """Extract one saved page against its schema.

    Returns {"page": page, "fields": {name: entry}} where each entry is
    {"found", "raw", "value", "format", "error"}. A missing node is
    found=False; a present-but-unparseable node is found=True with an
    error — the two failure modes a drift report must not conflate.
    """
    schema = get_schema(page)
    root = parse_html(html_text)
    fields: Dict[str, Any] = {}
    for name in sorted(schema):
        hook = schema[name]
        node = _find_first(root, hook)
        if node is None:
            fields[name] = {"found": False, "raw": None, "value": None,
                            "format": None, "error": None}
            continue
        raw = node.text()
        parsed = _parse_typed(hook["type"], raw)
        fields[name] = {"found": True, "raw": raw,
                        "value": parsed["value"],
                        "format": parsed["format"],
                        "error": parsed["error"]}
    return {"page": page, "fields": fields}


def extract_file(path: str, page: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return extract_html(fh.read(), page)
