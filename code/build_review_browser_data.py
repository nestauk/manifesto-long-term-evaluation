#!/usr/bin/env python3
"""Build the JSON data file for the review browser.

Reads the scoring universe CSV and documents.csv, groups commitments by
document, extracts page-break offsets for PDFs, and writes a single JSON
file that the browser app loads.

Usage:
    uv run code/build_review_browser_data.py
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCORES = ROOT / "data" / "commitments.csv"
DEFAULT_DOCS = ROOT / "data" / "documents.csv"
DEFAULT_OUTPUT = ROOT / "review_browser" / "data.json"

SCORE_DIMS = [
    "prevention",
    "tangible_investment",
    "intangible_investment",
    "risk_resilience",
    "current_consumption",
    "constitutional_change",
]
DIM_SHORT = {
    "prevention": "P",
    "tangible_investment": "T",
    "intangible_investment": "I",
    "risk_resilience": "R",
    "current_consumption": "C",
    "constitutional_change": "CC",
}
DOC_REQUIRED_COLUMNS = {
    "doc_id",
    "party_slug",
    "party_name",
    "year",
    "title",
    "local_path",
    "detected_format",
    "full_text",
}
SCORE_REQUIRED_COLUMNS = {
    "doc_id",
    "commitment_id",
    "commitment_text",
    "supporting_quote",
    "confidence",
    "ambiguous",
    "trust_tier",
}
SCORE_REQUIRED_COLUMNS.update(SCORE_DIMS)


def safe_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value: str, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def boolish(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def page_breaks_from_text(text: str) -> list[int]:
    """Return character offsets where each page starts, derived from form-feed characters."""
    if "\x0c" not in text:
        return [0]
    offsets = [0]
    pos = 0
    while True:
        idx = text.find("\x0c", pos)
        if idx == -1:
            break
        offsets.append(idx + 1)
        pos = idx + 1
    return offsets


def validate_required_columns(path: Path, fieldnames: list[str] | None, required_columns: set[str]) -> None:
    if fieldnames is None:
        raise ValueError(f"{path} is empty or missing a header row")

    missing = sorted(column for column in required_columns if column not in fieldnames)
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")


def iter_csv_rows(path: Path, required_columns: set[str]) -> Iterator[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        validate_required_columns(path, reader.fieldnames, required_columns)
        for row in reader:
            yield row


def read_documents(path: Path) -> dict[str, dict]:
    docs = {}
    for row in iter_csv_rows(path, DOC_REQUIRED_COLUMNS):
        doc_id = row.get("doc_id", "").strip()
        if doc_id:
            docs[doc_id] = row
    return docs


def iter_scores(path: Path) -> Iterator[dict[str, str]]:
    yield from iter_csv_rows(path, SCORE_REQUIRED_COLUMNS)


def locate_quote(full_text: str, quote: str) -> tuple[int, int]:
    """Find the quote in the document text, tolerating whitespace and punctuation drift.

    Falls back to the quote's first eight, last eight, then first five words.
    Returns (0, 0) when nothing matches.
    """
    words = re.findall(r"\w+", quote)
    for part in (words, words[:8], words[-8:], words[:5]):
        if len(part) < 3 and part is not words:
            continue
        if not part:
            break
        match = re.search(r"\W+".join(map(re.escape, part)), full_text, re.IGNORECASE)
        if match:
            return match.start(), match.end()
    return 0, 0


def browser_asset_path(local_path: str) -> str:
    path = Path((local_path or "").strip())
    if not path.as_posix():
        raise ValueError("Encountered a blank local_path in documents.csv")
    if path.is_absolute():
        raise ValueError(f"Expected a relative local_path, got absolute path: {local_path}")
    if not path.parts or path.parts[0] != "manifestos":
        raise ValueError(f"Expected local_path to start with 'manifestos/', got: {local_path}")

    return (Path("..") / path).as_posix()


def build_commitment(row: dict, full_text: str) -> dict:
    scores = {}
    rationales = {}
    for dim in SCORE_DIMS:
        short = DIM_SHORT[dim]
        scores[short] = safe_int(row.get(dim, "0"))
        rationale = (row.get(f"{dim}_rationale", "") or "").strip()
        if rationale:
            rationales[short] = rationale

    q_start, q_end = locate_quote(full_text, row.get("supporting_quote", "") or "")

    out = {
        "id": row.get("commitment_id", ""),
        "text": (row.get("commitment_text", "") or "").strip(),
        "quote": (row.get("supporting_quote", "") or "").strip(),
        "qStart": q_start,
        "qEnd": q_end,
        "scores": scores,
        "conf": round(safe_float(row.get("confidence", "0")), 2),
        "trust": (row.get("trust_tier", "") or "").strip(),
        "ambig": boolish(row.get("ambiguous", "")),
    }
    ambig_note = (row.get("ambiguity_note", "") or "").strip()
    if ambig_note:
        out["ambigNote"] = ambig_note
    if rationales:
        out["rationales"] = rationales
    return out


def build_document(doc_id: str, doc_row: dict, commitments: list[dict]) -> dict:
    detected_format = (doc_row.get("detected_format", "") or "").strip().lower()
    full_text = doc_row.get("full_text", "") or ""
    browser_path = browser_asset_path(doc_row.get("local_path", ""))

    out = {
        "docId": doc_id,
        "party": (doc_row.get("party_slug", "") or "").strip(),
        "partyName": (doc_row.get("party_name", "") or "").strip(),
        "year": safe_int(doc_row.get("year", "0")),
        "title": (doc_row.get("title", "") or "").strip(),
        "path": browser_path,
        "format": detected_format,
        "nCommitments": len(commitments),
        "commitments": commitments,
    }

    if detected_format == "pdf":
        out["pageBreaks"] = page_breaks_from_text(full_text)
    else:
        out["fullText"] = full_text

    return out


def build_browser_data(doc_rows: dict[str, dict], score_rows: Iterable[dict[str, str]]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in score_rows:
        doc_id = (row.get("doc_id", "") or "").strip()
        if doc_id:
            full_text = (doc_rows.get(doc_id) or {}).get("full_text", "") or ""
            grouped[doc_id].append(build_commitment(row, full_text))

    documents = []
    missing_docs = []
    for doc_id in sorted(grouped):
        doc_row = doc_rows.get(doc_id)
        if not doc_row:
            missing_docs.append(doc_id)
            continue

        commitments = grouped[doc_id]
        commitments.sort(key=lambda c: (c.get("qStart", 0), c.get("qEnd", 0), c.get("id", "")))
        documents.append(build_document(doc_id, doc_row, commitments))

    documents.sort(key=lambda d: (d["party"], d["year"], d["title"], d["docId"]))

    total_commitments = sum(d["nCommitments"] for d in documents)
    pdf_docs = sum(1 for d in documents if d["format"] == "pdf")
    summary = {
        "documents": len(documents),
        "commitments": total_commitments,
        "pdfDocs": pdf_docs,
        "textDocs": len(documents) - pdf_docs,
        "missingDocIds": missing_docs,
    }
    return {"documents": documents, "summary": summary}


def write_output(payload: dict, output_path: Path, pretty: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        if pretty:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def format_missing_docs(missing_docs: list[str], limit: int = 10) -> str:
    preview = ", ".join(missing_docs[:limit])
    if len(missing_docs) > limit:
        preview += f", ... (+{len(missing_docs) - limit} more)"
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the review browser JSON payload from the scoring universe and documents CSVs."
    )
    parser.add_argument(
        "--scores",
        type=Path,
        default=DEFAULT_SCORES,
        help=f"Path to scoring-universe CSV (default: {DEFAULT_SCORES})",
    )
    parser.add_argument(
        "--docs",
        type=Path,
        default=DEFAULT_DOCS,
        help=f"Path to documents CSV (default: {DEFAULT_DOCS})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Path to write JSON payload (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON instead of writing compact output.",
    )
    parser.add_argument(
        "--strict-missing-docs",
        action="store_true",
        help="Exit with status 1 if the scoring universe references doc_ids that are absent from documents.csv.",
    )
    args = parser.parse_args()

    try:
        doc_rows = read_documents(args.docs)
        payload = build_browser_data(doc_rows, iter_scores(args.scores))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    missing_docs = payload["summary"]["missingDocIds"]
    if missing_docs and args.strict_missing_docs:
        print(
            "error: scoring universe references doc_ids that are missing from documents.csv: "
            + format_missing_docs(missing_docs),
            file=sys.stderr,
        )
        raise SystemExit(1)

    output_path = args.output
    write_output(payload, output_path, pretty=args.pretty)

    size_mb = output_path.stat().st_size / 1024 / 1024

    print(f"documents={payload['summary']['documents']}")
    print(f"commitments={payload['summary']['commitments']}")
    print(f"pdf_docs={payload['summary']['pdfDocs']}")
    print(f"text_docs={payload['summary']['textDocs']}")
    print(f"missing_doc_ids={len(missing_docs)}")
    print(f"output_size={size_mb:.1f}MB")
    print(output_path)
    if missing_docs:
        print(f"warning: missing doc rows for: {format_missing_docs(missing_docs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
