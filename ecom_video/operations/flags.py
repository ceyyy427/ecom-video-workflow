"""Independent write switches; history reads and disconnect remain available."""

import os

FEATURES = ("research", "strategy", "images", "content", "connections", "review", "comments", "handoff")


def features():
    return {name: os.getenv("ECOM_DOMESTIC_" + name.upper(), "1") != "0" for name in FEATURES}


def route_feature(path):
    relative = path.removeprefix("/api/operations/")
    first = relative.split("/", 1)[0]
    return {
        "research": "research", "margin": "strategy", "strategies": "strategy",
        "image-packs": "images", "plans": "content", "content-matrices": "content",
        "accounts": "connections", "sources": "connections", "connectors": "connections",
        "observations": "review", "comments": "comments", "hypotheses": "comments",
        "iterations": "comments", "comparisons": "review",
        "publication-packs": "handoff", "registrations": "handoff",
    }.get(first) if path.startswith("/api/operations/") else None
