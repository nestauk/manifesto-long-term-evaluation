#!/usr/bin/env python3
import argparse
import csv
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR_PATH = ROOT / "scripts" / "extract_pledges_llm.py"


@dataclass
class Shard:
    index: int
    rows: list[dict] = field(default_factory=list)
    estimated_chunks: int = 0
    total_words: int = 0


def load_extractor():
    spec = importlib.util.spec_from_file_location("extract_module", EXTRACTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
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


def safe_int(value: str) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return 0


def estimate_doc_chunks(module, row: dict, chunk_chars: int, overlap_chars: int) -> int:
    return len(module.build_chunks(row, chunk_chars, overlap_chars))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--num-shards", type=int, default=4)
    parser.add_argument("--chunk-chars", type=int, required=True)
    parser.add_argument("--overlap-chars", type=int, required=True)
    args = parser.parse_args()

    module = load_extractor()
    rows, fieldnames = read_rows(Path(args.input))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    estimated = []
    for row in rows:
        estimated_chunks = estimate_doc_chunks(module, row, args.chunk_chars, args.overlap_chars)
        out = dict(row)
        out["estimated_chunks"] = estimated_chunks
        out["word_count"] = safe_int(row.get("word_count", ""))
        estimated.append(out)

    estimated.sort(
        key=lambda row: (
            -int(row["estimated_chunks"]),
            -int(row["word_count"]),
            row.get("doc_id", ""),
        )
    )

    shards = [Shard(index=i) for i in range(args.num_shards)]
    for row in estimated:
        shard = min(shards, key=lambda item: (item.estimated_chunks, item.total_words, item.index))
        shard.rows.append(row)
        shard.estimated_chunks += int(row["estimated_chunks"])
        shard.total_words += int(row["word_count"])

    summary_rows = []
    shard_fieldnames = list(fieldnames)
    for extra in ["estimated_chunks"]:
        if extra not in shard_fieldnames:
            shard_fieldnames.append(extra)

    for shard in shards:
        shard_rows = []
        for row in sorted(shard.rows, key=lambda item: (safe_int(item.get("year", "")), item.get("party_slug", ""), item.get("title", ""))):
            out = dict(row)
            out["estimated_chunks"] = row["estimated_chunks"]
            shard_rows.append(out)
        shard_path = output_dir / f"documents-shard-{shard.index:02d}.csv"
        write_csv(shard_path, shard_rows, shard_fieldnames)
        summary_rows.append(
            {
                "shard_index": shard.index,
                "docs": len(shard.rows),
                "estimated_chunks": shard.estimated_chunks,
                "total_words": shard.total_words,
                "shard_csv": str(shard_path),
            }
        )

    write_csv(
        output_dir / "shard-summary.csv",
        summary_rows,
        ["shard_index", "docs", "estimated_chunks", "total_words", "shard_csv"],
    )

    print(f"docs={len(rows)}")
    print(f"num_shards={args.num_shards}")
    for row in summary_rows:
        print(
            f"shard={row['shard_index']} docs={row['docs']} "
            f"estimated_chunks={row['estimated_chunks']} total_words={row['total_words']}"
        )
    print(output_dir / "shard-summary.csv")


if __name__ == "__main__":
    main()
