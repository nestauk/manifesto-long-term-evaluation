#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from pathlib import Path


def read_csv_rows(path: Path) -> tuple[list[dict], list[str]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []
    return rows, fieldnames


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict) -> tuple[str, str]:
    return row.get("doc_id", ""), row.get("commitment_id", "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-jsonl", required=True)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    shard_csvs = sorted(input_dir.glob("shard-*/commitments.csv"))
    shard_jsonls = sorted(input_dir.glob("shard-*/commitments.jsonl"))

    merged_rows = []
    fieldnames = []
    for shard_csv in shard_csvs:
        rows, shard_fields = read_csv_rows(shard_csv)
        if not fieldnames:
            fieldnames = shard_fields
        else:
            for field in shard_fields:
                if field not in fieldnames:
                    fieldnames.append(field)
        merged_rows.extend(rows)

    merged_rows.sort(key=row_key)
    write_csv(Path(args.output_csv), merged_rows, fieldnames)

    output_jsonl = Path(args.output_jsonl)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as out:
        for shard_jsonl in shard_jsonls:
            with shard_jsonl.open(encoding="utf-8", errors="replace") as inp:
                for line in inp:
                    line = line.strip()
                    if not line:
                        continue
                    out.write(line + "\n")

    print(f"shard_csvs={len(shard_csvs)}")
    print(f"shard_jsonls={len(shard_jsonls)}")
    print(f"rows={len(merged_rows)}")
    print(args.output_csv)
    print(args.output_jsonl)


if __name__ == "__main__":
    main()
