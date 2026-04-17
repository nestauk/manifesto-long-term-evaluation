#!/usr/bin/env python3
"""Build the JSON payload that drives the review browser's Long-term Language mode.

For every document the browser knows about, run the NLP profiler's regex
patterns against the document's full text and record every match's character
offsets + matched substring. Ship groups metadata (labels, colours, example
terms) alongside so the JS only needs one fetch.

Usage:
    uv run code/build_nlp_highlights.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = ROOT / "data" / "documents.csv"
DEFAULT_DATA_JSON = ROOT / "review_browser" / "data.json"
DEFAULT_OUTPUT = ROOT / "review_browser" / "nlp_hits.json"

sys.path.insert(0, str(Path(__file__).resolve().parent / "nlp"))
from profile_manifestos_nlp import COMPILED_PATTERNS  # noqa: E402

GROUP_ORDER = [
    "long_term",
    "short_term",
    "definite_commitment",
    "aspirational",
    "prevention",
    "investment",
    "resilience",
    "relief",
    "intergenerational",
    "institutional",
]

GROUP_META = {
    "long_term": {
        "label": "Long-term",
        "colour": "#7fb8e8",
        "examples": ["future", "long-term", "decade", "generation", "legacy", "sustainable", "resilience"],
    },
    "short_term": {
        "label": "Short-term",
        "colour": "#f2a673",
        "examples": ["day one", "immediate", "urgent", "right now", "crisis", "emergency", "quickly"],
    },
    "definite_commitment": {
        "label": "Definite commitment",
        "colour": "#7fcf91",
        "examples": ["we will", "will deliver", "will build", "committed to", "guarantee"],
    },
    "aspirational": {
        "label": "Aspirational",
        "colour": "#c39be8",
        "examples": ["aim to", "seek to", "working towards", "aspire", "ambition", "hope", "would", "could", "may"],
    },
    "prevention": {
        "label": "Prevention",
        "colour": "#5bc5c5",
        "examples": ["prevent", "early intervention", "root cause", "upstream", "public health"],
    },
    "investment": {
        "label": "Investment",
        "colour": "#96d994",
        "examples": ["invest", "infrastructure", "R&D", "science", "innovation", "training", "housing"],
    },
    "resilience": {
        "label": "Resilience",
        "colour": "#e8c26a",
        "examples": ["resilience", "security", "safeguard", "mitigate", "adapt", "risk", "stability"],
    },
    "relief": {
        "label": "Relief",
        "colour": "#f2a5c0",
        "examples": ["cut tax", "freeze", "relief", "boost", "extra", "cost-of-living", "waiting times"],
    },
    "intergenerational": {
        "label": "Intergenerational",
        "colour": "#8a9fd9",
        "examples": ["children", "young people", "future generations", "grandchildren", "legacy", "inheritance"],
    },
    "institutional": {
        "label": "Institutional",
        "colour": "#a8b5c9",
        "examples": ["independent commission", "statutory", "binding", "targets", "milestones", "framework", "pathway"],
    },
}

assert set(GROUP_ORDER) == set(GROUP_META), "GROUP_ORDER and GROUP_META must cover the same keys"
for _key in GROUP_ORDER:
    assert _key in COMPILED_PATTERNS, f"missing regex group in COMPILED_PATTERNS: {_key}"


def read_documents(path: Path) -> dict[str, dict]:
    csv.field_size_limit(sys.maxsize)
    docs: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path} is empty or missing a header row")
        for required in ("doc_id", "full_text"):
            if required not in reader.fieldnames:
                raise ValueError(f"{path} is missing required column: {required}")
        for row in reader:
            doc_id = (row.get("doc_id") or "").strip()
            if doc_id:
                docs[doc_id] = row
    return docs


def load_browser_doc_ids(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return [doc["docId"] for doc in payload.get("documents", [])]


def find_hits(text: str, patterns: list[re.Pattern[str]]) -> Iterator[re.Match[str]]:
    for pattern in patterns:
        yield from pattern.finditer(text)


def hits_for_document(text: str) -> dict:
    hits_by_group: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for group in GROUP_ORDER:
        matches = list(find_hits(text, COMPILED_PATTERNS[group]))
        matches.sort(key=lambda m: m.start())
        hits_by_group[group] = [
            {"s": m.start(), "e": m.end(), "t": m.group(0)} for m in matches
        ]
        counts[group] = len(matches)
    hits_by_group["_counts"] = counts
    return hits_by_group


def build_payload(doc_ids: list[str], docs: dict[str, dict]) -> dict:
    missing_docs = [doc_id for doc_id in doc_ids if doc_id not in docs]
    if missing_docs:
        raise ValueError(
            f"documents.csv is missing full_text for {len(missing_docs)} browser doc(s): "
            + ", ".join(missing_docs[:5])
            + (f", ... (+{len(missing_docs) - 5} more)" if len(missing_docs) > 5 else "")
        )

    groups = [
        {
            "key": key,
            "label": GROUP_META[key]["label"],
            "colour": GROUP_META[key]["colour"],
            "examples": GROUP_META[key]["examples"],
        }
        for key in GROUP_ORDER
    ]

    hits: dict[str, dict] = {}
    for doc_id in doc_ids:
        text = docs[doc_id].get("full_text") or ""
        hits[doc_id] = hits_for_document(text)

    return {"groups": groups, "hits": hits}


def summarize(payload: dict) -> None:
    totals = {group: 0 for group in GROUP_ORDER}
    max_per_group = {group: 0 for group in GROUP_ORDER}
    densest_doc: tuple[str, int] = ("", 0)

    for doc_id, hits_by_group in payload["hits"].items():
        doc_total = 0
        for group in GROUP_ORDER:
            count = hits_by_group["_counts"][group]
            totals[group] += count
            max_per_group[group] = max(max_per_group[group], count)
            doc_total += count
        if doc_total > densest_doc[1]:
            densest_doc = (doc_id, doc_total)

    print(f"documents={len(payload['hits'])}")
    print(f"groups={len(payload['groups'])}")
    for group in GROUP_ORDER:
        print(f"  {group:22s} total={totals[group]:6d}  max_in_one_doc={max_per_group[group]}")
    print(f"densest_doc={densest_doc[0]} total_hits={densest_doc[1]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    parser.add_argument("--data-json", type=Path, default=DEFAULT_DATA_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        doc_ids = load_browser_doc_ids(args.data_json)
        docs = read_documents(args.docs)
        payload = build_payload(doc_ids, docs)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    summarize(payload)
    size_mb = args.output.stat().st_size / 1024 / 1024
    print(f"output_size={size_mb:.1f}MB")
    print(args.output)


if __name__ == "__main__":
    main()
