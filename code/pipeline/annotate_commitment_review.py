#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path


ACTION_PATTERNS = [
    r"\bwe will\b",
    r"\blabour will\b",
    r"\bthe government will\b",
    r"\bmayors will\b",
    r"\blocal areas will\b",
    r"\bcouncils will\b",
    r"\bwe shall\b",
    r"\bwill [a-z]+\b",
]

RETROSPECTIVE_PATTERNS = [
    r"\bhelped to\b",
    r"\bmade the\b",
    r"\bwas a key pillar\b",
    r"\bhas delivered\b",
    r"\bhave delivered\b",
    r"\bhas achieved\b",
    r"\bhave achieved\b",
    r"\bwithout which\b",
    r"\bin\s+(?:19|20)\d{2}\b",
]

STATUS_PATTERNS = [
    r"\bwe are set to achieve\b",
    r"\bis set to achieve\b",
    r"\bwe estimate that to meet these commitments\b",
    r"\bwe estimate that\b",
    r"\bwe have\b",
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def classify_row(text: str) -> list[str]:
    reasons = []
    stripped = normalize(text)
    words = stripped.split()
    lower = stripped.lower()

    if len(words) <= 4:
        reasons.append("very_short")

    if stripped.endswith(";") or stripped.endswith(":"):
        reasons.append("trailing_fragment_punctuation")

    if re.fullmatch(r"(?:[A-Z][A-Za-z0-9’'/-]+(?:\s+|$)){1,8}\.?", stripped) and len(words) <= 8:
        reasons.append("headline_like")

    if not any(re.search(pat, lower) for pat in ACTION_PATTERNS):
        if re.match(r"^(?:A|An|The|Over|\d)", stripped):
            reasons.append("no_action_verb_surface")

    if re.match(r"^(?:Over\s+)?£?\d[\d,]*(?:\.\d+)?\b", stripped) and len(words) <= 8:
        reasons.append("amount_or_count_label")

    if any(re.search(pat, lower) for pat in RETROSPECTIVE_PATTERNS):
        reasons.append("retrospective_or_record_claim")

    if any(re.search(pat, lower) for pat in STATUS_PATTERNS):
        reasons.append("status_or_progress_claim")

    return reasons


def priority_for(reasons: list[str]) -> str:
    if not reasons:
        return "low"
    if "trailing_fragment_punctuation" in reasons:
        return "high"
    if "retrospective_or_record_claim" in reasons:
        return "high"
    if "status_or_progress_claim" in reasons:
        return "high"
    if "headline_like" in reasons and "very_short" in reasons:
        return "high"
    if "amount_or_count_label" in reasons and "no_action_verb_surface" in reasons:
        return "high"
    return "medium"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--flagged-csv", required=True)
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    output_path = Path(args.output_csv)
    flagged_path = Path(args.flagged_csv)

    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys()) + ["heuristic_flags", "review_priority"]
    annotated = []
    flagged = []

    for row in rows:
        reasons = classify_row(row["commitment_text"])
        out = dict(row)
        out["heuristic_flags"] = ";".join(reasons)
        out["review_priority"] = priority_for(reasons)
        annotated.append(out)
        if out["review_priority"] != "low":
            flagged.append(out)

    for path, subset in [(output_path, annotated), (flagged_path, flagged)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(subset)

    print(f"input_rows={len(rows)}")
    print(f"flagged_rows={len(flagged)}")
    print(output_path)
    print(flagged_path)


if __name__ == "__main__":
    main()
