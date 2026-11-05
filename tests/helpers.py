"""Shared helpers for the test suite (not a test module)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIX = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def manifest():
    with open(os.path.join(FIX, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)["mutations"]


def by_id(mid):
    for m in manifest():
        if m["id"] == mid:
            return m
    raise KeyError(mid)
