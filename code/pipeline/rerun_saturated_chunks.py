#!/usr/bin/env python3
import argparse
import csv
import importlib.util
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_CSV = ROOT / "analysis" / "documents.csv"
EXTRACTOR_PATH = Path(__file__).resolve().parent / "extract_pledges_llm.py"

STANDARD_FIELDS = [
    "commitment_id",
    "doc_id",
    "local_path",
    "party_slug",
    "party_name",
    "year",
    "title",
    "chunk_id",
    "chunk_index",
    "chunk_char_start",
    "chunk_char_end",
    "commitment_text",
    "supporting_quote",
    "quote_char_start",
    "quote_char_end",
    "validation_status",
    "extraction_mode",
]

RERUN_FIELDS = [
    "effective_chunk_id",
    "source_chunk_id",
    "source_chunk_index",
    "source_chunk_char_start",
    "source_chunk_char_end",
    "rerun_chunk_id",
    "rerun_subchunk_index",
    "rerun_subchunk_count",
    "rerun_chunk_chars",
    "rerun_overlap_chars",
    "rerun_reason",
]


def load_extractor():
    spec = importlib.util.spec_from_file_location("extract_module", EXTRACTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def int_or_none(value: str) -> int | None:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None


def effective_chunk_id(row: dict) -> str:
    return str(
        row.get("rerun_chunk_id")
        or row.get("effective_chunk_id")
        or row.get("chunk_id")
        or ""
    ).strip()


def row_sort_key(row: dict) -> tuple[str, int, int, str]:
    chunk_start = int_or_none(row.get("chunk_char_start", "")) or 0
    quote_start = int_or_none(row.get("quote_char_start", "")) or chunk_start
    return (
        row.get("doc_id", ""),
        chunk_start,
        quote_start,
        row.get("commitment_id", ""),
    )


def union_fieldnames(base_fieldnames: list[str], rerun_rows: list[dict]) -> list[str]:
    fieldnames = list(base_fieldnames) if base_fieldnames else list(STANDARD_FIELDS)
    for key in RERUN_FIELDS:
        if key not in fieldnames:
            fieldnames.append(key)
    for row in rerun_rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    return fieldnames


def seed_seen_quotes(module, rows: list[dict]) -> set[tuple[str, str]]:
    seen = set()
    for row in rows:
        doc_id = row.get("doc_id", "")
        quote = (row.get("supporting_quote") or row.get("commitment_text") or "").strip()
        if not doc_id or not quote:
            continue
        seen.add((doc_id, module.dedupe_key(quote)))
    return seen


def build_target_chunks(module, docs: dict[str, dict], rerun_targets: list[dict], chunk_chars: int, overlap_chars: int):
    cleaned_text_cache: dict[str, str] = {}
    chunk_jobs = []
    skipped = []

    for target in rerun_targets:
        doc_id = target.get("doc_id", "")
        if doc_id not in docs:
            skipped.append((target, "missing_doc"))
            continue
        start = int_or_none(target.get("chunk_char_start", ""))
        end = int_or_none(target.get("chunk_char_end", ""))
        if start is None or end is None or end <= start:
            skipped.append((target, "missing_chunk_bounds"))
            continue
        if doc_id not in cleaned_text_cache:
            cleaned_text_cache[doc_id] = module.clean_text_for_extraction(docs[doc_id]["full_text"])
        span_text = cleaned_text_cache[doc_id][start:end].strip()
        if not span_text:
            skipped.append((target, "empty_chunk_span"))
            continue

        effective_id = target.get("effective_chunk_id", "") or target.get("chunk_id", "")
        source_chunk_id = target.get("source_chunk_id", "") or target.get("chunk_id", "")
        source_chunk_index = int_or_none(target.get("chunk_index", "")) or 0
        subchunks = list(module.paragraph_chunks(span_text, chunk_chars, overlap_chars))
        if not subchunks:
            skipped.append((target, "no_subchunks"))
            continue

        doc = docs[doc_id]
        for sub_idx, (sub_start, sub_end, chunk_text) in enumerate(subchunks):
            rerun_chunk_id = f"{effective_id}-r{sub_idx:02d}"
            chunk_jobs.append(
                {
                    "target": target,
                    "chunk": module.Chunk(
                        doc_id=doc["doc_id"],
                        local_path=doc["local_path"],
                        party_slug=doc["party_slug"],
                        party_name=doc["party_name"],
                        year=doc["year"],
                        title=doc["title"],
                        chunk_id=rerun_chunk_id,
                        chunk_index=source_chunk_index,
                        char_start=start + sub_start,
                        char_end=start + sub_end,
                        chunk_text=chunk_text,
                    ),
                    "effective_chunk_id": effective_id,
                    "source_chunk_id": source_chunk_id,
                    "source_chunk_index": source_chunk_index,
                    "source_chunk_char_start": start,
                    "source_chunk_char_end": end,
                    "rerun_subchunk_index": sub_idx,
                    "rerun_subchunk_count": len(subchunks),
                    "rerun_reason": target.get("rerun_reason", ""),
                }
            )
    return chunk_jobs, skipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents-input", default=str(DOCUMENTS_CSV))
    parser.add_argument("--base-extraction-csv", required=True)
    parser.add_argument("--chunk-rerun-csv", required=True)
    parser.add_argument("--output-rerun-csv", required=True)
    parser.add_argument("--output-rerun-jsonl", required=True)
    parser.add_argument("--merged-output-csv")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-pledges-per-chunk", type=int, default=24)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--max-api-retries", type=int, default=6)
    parser.add_argument("--backoff-base-seconds", type=float, default=1.0)
    parser.add_argument("--backoff-max-seconds", type=float, default=30.0)
    parser.add_argument("--rerun-chunk-chars", type=int, default=4000)
    parser.add_argument("--rerun-overlap-chars", type=int, default=400)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--limit-targets", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    module = load_extractor()

    docs_rows, _ = read_csv_rows(Path(args.documents_input))
    docs = {row["doc_id"]: row for row in docs_rows}
    base_rows, base_fieldnames = read_csv_rows(Path(args.base_extraction_csv))
    rerun_targets, _ = read_csv_rows(Path(args.chunk_rerun_csv))
    if args.limit_targets:
        rerun_targets = rerun_targets[: args.limit_targets]

    target_effective_ids = {
        (row.get("effective_chunk_id", "") or row.get("chunk_id", "")).strip()
        for row in rerun_targets
        if (row.get("effective_chunk_id", "") or row.get("chunk_id", "")).strip()
    }
    kept_base_rows = [row for row in base_rows if effective_chunk_id(row) not in target_effective_ids]

    chunk_jobs, skipped = build_target_chunks(
        module=module,
        docs=docs,
        rerun_targets=rerun_targets,
        chunk_chars=args.rerun_chunk_chars,
        overlap_chars=args.rerun_overlap_chars,
    )

    if args.dry_run:
        jobs_by_target = defaultdict(int)
        for job in chunk_jobs:
            jobs_by_target[job["effective_chunk_id"]] += 1
        print(f"targets={len(rerun_targets)}")
        print(f"planned_subchunks={len(chunk_jobs)}")
        print(f"kept_base_rows={len(kept_base_rows)}")
        print(f"skipped_targets={len(skipped)}")
        for target in rerun_targets[:10]:
            effective_id = target.get("effective_chunk_id", "") or target.get("chunk_id", "")
            print(
                effective_id,
                "source_chunk=" + (target.get("chunk_id", "") or effective_id),
                "subchunks=" + str(jobs_by_target.get(effective_id, 0)),
            )
        for target, reason in skipped[:10]:
            print("skipped", target.get("effective_chunk_id", "") or target.get("chunk_id", ""), reason)
        return

    module.load_dotenv(module.ENV_PATH)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    client = OpenAI()
    seen_quotes = seed_seen_quotes(module, kept_base_rows)
    rerun_rows = []
    failed_jobs = 0

    output_rerun_csv = Path(args.output_rerun_csv)
    output_rerun_jsonl = Path(args.output_rerun_jsonl)
    output_rerun_csv.parent.mkdir(parents=True, exist_ok=True)

    with output_rerun_jsonl.open("w", encoding="utf-8") as raw_out:
        for job in chunk_jobs:
            chunk = job["chunk"]
            print(f"rerun {job['effective_chunk_id']} -> {chunk.chunk_id}", flush=True)
            try:
                result = module.extract_chunk(
                    client,
                    args.model,
                    chunk,
                    args.temperature,
                    args.max_pledges_per_chunk,
                    args.max_output_tokens,
                    args.max_api_retries,
                    args.backoff_base_seconds,
                    args.backoff_max_seconds,
                )
                raw_quotes = module.result_quotes(result)
                accepted_rows = []
                accepted_count = 0
                cap_truncated = False
                for idx, quote in enumerate(raw_quotes):
                    if accepted_count >= args.max_pledges_per_chunk:
                        cap_truncated = True
                        break
                    quote = (quote or "").strip()
                    if not quote:
                        continue
                    if module.seems_truncated(quote):
                        continue
                    key = (chunk.doc_id, module.dedupe_key(quote))
                    if key in seen_quotes:
                        continue
                    start, end = module.locate_quote(chunk.chunk_text, quote)
                    validation_status = "exact_quote_match" if start is not None else "needs_review"
                    if start == -1 and end == -1:
                        validation_status = "normalized_quote_match"
                    pledge_text = module.normalize_whitespace(quote)
                    seen_quotes.add(key)
                    accepted_rows.append(
                        {
                            "commitment_id": f"{chunk.chunk_id}-c{idx:03d}",
                            "doc_id": chunk.doc_id,
                            "local_path": chunk.local_path,
                            "party_slug": chunk.party_slug,
                            "party_name": chunk.party_name,
                            "year": chunk.year,
                            "title": chunk.title,
                            "chunk_id": job["source_chunk_id"],
                            "chunk_index": job["source_chunk_index"],
                            "chunk_char_start": chunk.char_start,
                            "chunk_char_end": chunk.char_end,
                            "commitment_text": pledge_text,
                            "supporting_quote": quote,
                            "quote_char_start": "" if start in (None, -1) else chunk.char_start + start,
                            "quote_char_end": "" if end in (None, -1) else chunk.char_start + end,
                            "validation_status": validation_status,
                            "extraction_mode": "verbatim_quote_only_rerun_subchunk",
                            "effective_chunk_id": job["effective_chunk_id"],
                            "source_chunk_id": job["source_chunk_id"],
                            "source_chunk_index": job["source_chunk_index"],
                            "source_chunk_char_start": job["source_chunk_char_start"],
                            "source_chunk_char_end": job["source_chunk_char_end"],
                            "rerun_chunk_id": chunk.chunk_id,
                            "rerun_subchunk_index": job["rerun_subchunk_index"],
                            "rerun_subchunk_count": job["rerun_subchunk_count"],
                            "rerun_chunk_chars": args.rerun_chunk_chars,
                            "rerun_overlap_chars": args.rerun_overlap_chars,
                            "rerun_reason": job["rerun_reason"],
                        }
                    )
                    accepted_count += 1
                record = {
                    "effective_chunk_id": job["effective_chunk_id"],
                    "source_chunk_id": job["source_chunk_id"],
                    "rerun_chunk_id": chunk.chunk_id,
                    "rerun_subchunk_index": job["rerun_subchunk_index"],
                    "rerun_subchunk_count": job["rerun_subchunk_count"],
                    "result": result,
                    "raw_quote_count": len(raw_quotes),
                    "accepted_quote_count": len(accepted_rows),
                    "requested_max_pledges_per_chunk": args.max_pledges_per_chunk,
                    "cap_truncated": cap_truncated,
                }
                rerun_rows.extend(accepted_rows)
            except Exception as exc:
                failed_jobs += 1
                print(f"rerun failed {chunk.chunk_id}: {exc}", flush=True)
                record = {
                    "effective_chunk_id": job["effective_chunk_id"],
                    "source_chunk_id": job["source_chunk_id"],
                    "rerun_chunk_id": chunk.chunk_id,
                    "rerun_subchunk_index": job["rerun_subchunk_index"],
                    "rerun_subchunk_count": job["rerun_subchunk_count"],
                    "result": None,
                    "raw_quote_count": 0,
                    "accepted_quote_count": 0,
                    "requested_max_pledges_per_chunk": args.max_pledges_per_chunk,
                    "cap_truncated": False,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            raw_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            raw_out.flush()
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)

    rerun_rows.sort(key=row_sort_key)
    rerun_fieldnames = union_fieldnames(base_fieldnames, rerun_rows)
    write_csv(output_rerun_csv, rerun_rows, rerun_fieldnames)

    if args.merged_output_csv:
        merged_rows = kept_base_rows + rerun_rows
        merged_rows.sort(key=row_sort_key)
        write_csv(Path(args.merged_output_csv), merged_rows, union_fieldnames(base_fieldnames, rerun_rows))

    print(f"targets={len(rerun_targets)}")
    print(f"planned_subchunks={len(chunk_jobs)}")
    print(f"skipped_targets={len(skipped)}")
    print(f"rerun_rows={len(rerun_rows)}")
    print(f"kept_base_rows={len(kept_base_rows)}")
    if failed_jobs:
        print(f"failed_jobs={failed_jobs}")
    print(output_rerun_csv)
    print(output_rerun_jsonl)
    if args.merged_output_csv:
        print(args.merged_output_csv)


if __name__ == "__main__":
    main()
