#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


STRONG_REVIEW_FLAGS = {
    "retrospective_or_record_claim",
    "status_or_progress_claim",
}


def split_flags(text: str) -> set[str]:
    return {part.strip() for part in (text or "").split(";") if part.strip()}


def merge_review_rows(base_rows: list[dict], reviewed_rows: list[dict]) -> list[dict]:
    reviewed_by_id = {row["commitment_id"]: row for row in reviewed_rows if row.get("commitment_id")}
    merged = []
    for row in base_rows:
        out = dict(row)
        reviewed = reviewed_by_id.get(row.get("commitment_id", ""))
        if reviewed is not None:
            for key, value in reviewed.items():
                if key not in out:
                    out[key] = value
        merged.append(out)
    return merged


def screen_row(row: dict) -> tuple[str, str]:
    adversarial_verdict = (row.get("adversarial_verdict") or "").strip().lower()
    adversarial_reason = (row.get("adversarial_reason") or "").strip()
    heuristic_flags = split_flags(row.get("heuristic_flags", ""))
    review_priority = (row.get("review_priority") or "").strip().lower()

    if adversarial_verdict == "drop":
        return "drop", adversarial_reason or "adversarial_drop"
    if adversarial_verdict == "review":
        return "review", adversarial_reason or "adversarial_review"
    if adversarial_verdict == "keep":
        return "keep", adversarial_reason or "adversarial_keep"

    strong_flags = sorted(flag for flag in heuristic_flags if flag in STRONG_REVIEW_FLAGS)
    if strong_flags:
        return "review", ";".join(strong_flags)
    if review_priority == "high":
        return "review", "heuristic_high_priority"
    return "keep", "default_keep"


def write_subset(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--reviewed-csv")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--keep-csv")
    parser.add_argument("--review-csv")
    parser.add_argument("--drop-csv")
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    with input_path.open(newline="", encoding="utf-8") as f:
        base_rows = list(csv.DictReader(f))

    reviewed_rows = []
    if args.reviewed_csv:
        with Path(args.reviewed_csv).open(newline="", encoding="utf-8") as f:
            reviewed_rows = list(csv.DictReader(f))

    rows = merge_review_rows(base_rows, reviewed_rows)

    fieldnames = list(rows[0].keys()) if rows else []
    for key in ["screen_verdict", "screen_reason"]:
        if key not in fieldnames:
            fieldnames.append(key)

    keep_rows = []
    review_rows = []
    drop_rows = []
    output_rows = []

    for row in rows:
        out = dict(row)
        verdict, reason = screen_row(out)
        out["screen_verdict"] = verdict
        out["screen_reason"] = reason
        output_rows.append(out)
        if verdict == "keep":
            keep_rows.append(out)
        elif verdict == "review":
            review_rows.append(out)
        else:
            drop_rows.append(out)

    output_path = Path(args.output_csv)
    write_subset(output_path, output_rows, fieldnames)

    if args.keep_csv:
        write_subset(Path(args.keep_csv), keep_rows, fieldnames)
    if args.review_csv:
        write_subset(Path(args.review_csv), review_rows, fieldnames)
    if args.drop_csv:
        write_subset(Path(args.drop_csv), drop_rows, fieldnames)

    print(f"rows={len(output_rows)}")
    print(f"keep_rows={len(keep_rows)}")
    print(f"review_rows={len(review_rows)}")
    print(f"drop_rows={len(drop_rows)}")
    print(output_path)


if __name__ == "__main__":
    main()
