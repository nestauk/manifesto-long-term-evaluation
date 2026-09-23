#!/usr/bin/env python3
import argparse
import csv
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path


MIN_EXACT_TEXT_TOKENS = 4
MIN_NEAR_EXACT_TOKENS = 6
MIN_QUOTE_CHARS = 30
DEFAULT_NEAR_EXACT_THRESHOLD = 0.96
DEFAULT_BUCKET_TOKENS = 6


def normalize_for_match(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def chunk_num(chunk_id: str) -> int:
    try:
        return int((chunk_id or "").rsplit("-", 1)[-1])
    except ValueError:
        return 0


def row_order(row: dict) -> tuple[int, int, str]:
    try:
        chunk_index = int(row.get("chunk_index", "") or 0)
    except ValueError:
        chunk_index = 0
    return (
        chunk_num(row.get("chunk_id", "")),
        chunk_index,
        row.get("commitment_id", ""),
    )


def prefix_bucket(text: str, bucket_tokens: int) -> str:
    tokens = text.split()
    if not tokens:
        return ""
    return " ".join(tokens[:bucket_tokens])


def find_near_exact_anchor(
    normalized_text: str,
    candidates: list[dict],
    threshold: float,
) -> tuple[dict | None, float]:
    if not normalized_text:
        return None, 0.0

    best_anchor = None
    best_ratio = 0.0
    tokens = normalized_text.split()
    token_set = set(tokens)

    for candidate in candidates:
        candidate_text = candidate.get("_normalized_commitment", "")
        if not candidate_text:
            continue
        ratio = SequenceMatcher(None, normalized_text, candidate_text).ratio()
        if ratio < threshold or ratio < best_ratio:
            continue

        candidate_tokens = candidate_text.split()
        if not candidate_tokens:
            continue

        overlap = len(token_set & set(candidate_tokens)) / max(len(token_set | set(candidate_tokens)), 1)
        if overlap < 0.85:
            continue

        best_anchor = candidate
        best_ratio = ratio

    return best_anchor, best_ratio


def annotate_doc(rows: list[dict], threshold: float, bucket_tokens: int) -> list[dict]:
    seen_commitment = {}
    seen_quote = {}
    prefix_candidates: dict[str, list[dict]] = defaultdict(list)
    annotated = []

    for row in sorted(rows, key=row_order):
        out = dict(row)
        normalized_commitment = normalize_for_match(row.get("commitment_text", ""))
        normalized_quote = normalize_for_match(row.get("supporting_quote", ""))
        out["_normalized_commitment"] = normalized_commitment

        verdict = "unique"
        duplicate_of = ""
        reason = ""
        similarity = ""
        group = row.get("commitment_id", "")

        if (
            normalized_commitment
            and len(normalized_commitment.split()) >= MIN_EXACT_TEXT_TOKENS
            and normalized_commitment in seen_commitment
        ):
            anchor = seen_commitment[normalized_commitment]
            verdict = "drop_duplicate"
            duplicate_of = anchor.get("commitment_id", "")
            group = anchor.get("global_duplicate_group", duplicate_of)
            reason = "exact_commitment_text"
            similarity = "1.000"
        elif normalized_quote and len(normalized_quote) >= MIN_QUOTE_CHARS and normalized_quote in seen_quote:
            anchor = seen_quote[normalized_quote]
            verdict = "drop_duplicate"
            duplicate_of = anchor.get("commitment_id", "")
            group = anchor.get("global_duplicate_group", duplicate_of)
            reason = "exact_supporting_quote"
            similarity = "1.000"
        elif normalized_commitment and len(normalized_commitment.split()) >= MIN_NEAR_EXACT_TOKENS:
            anchor, ratio = find_near_exact_anchor(
                normalized_commitment,
                prefix_candidates.get(prefix_bucket(normalized_commitment, bucket_tokens), []),
                threshold,
            )
            if anchor is not None:
                verdict = "review"
                duplicate_of = anchor.get("commitment_id", "")
                group = anchor.get("global_duplicate_group", duplicate_of)
                reason = "near_exact_commitment_text"
                similarity = f"{ratio:.3f}"

        out["global_duplicate_group"] = group
        out["global_duplicate_verdict"] = verdict
        out["global_duplicate_of"] = duplicate_of
        out["global_duplicate_reason"] = reason
        out["global_duplicate_similarity"] = similarity
        annotated.append(out)

        if verdict == "unique":
            if normalized_commitment:
                seen_commitment.setdefault(normalized_commitment, out)
                prefix_candidates[prefix_bucket(normalized_commitment, bucket_tokens)].append(out)
            if normalized_quote:
                seen_quote.setdefault(normalized_quote, out)

    for out in annotated:
        out.pop("_normalized_commitment", None)
    return annotated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--near-exact-threshold", type=float, default=DEFAULT_NEAR_EXACT_THRESHOLD)
    parser.add_argument("--bucket-tokens", type=int, default=DEFAULT_BUCKET_TOKENS)
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    output_path = Path(args.output_csv)

    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_doc[row.get("doc_id", "")].append(row)

    output_rows = []
    for doc_id in sorted(by_doc):
        output_rows.extend(annotate_doc(by_doc[doc_id], args.near_exact_threshold, args.bucket_tokens))

    fieldnames = list(rows[0].keys()) if rows else []
    for key in [
        "global_duplicate_group",
        "global_duplicate_verdict",
        "global_duplicate_of",
        "global_duplicate_reason",
        "global_duplicate_similarity",
    ]:
        if key not in fieldnames:
            fieldnames.append(key)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    verdict_counts = defaultdict(int)
    for row in output_rows:
        verdict_counts[row.get("global_duplicate_verdict", "")] += 1

    print(f"docs={len(by_doc)}")
    print(f"rows={len(output_rows)}")
    print(f"unique_rows={verdict_counts.get('unique', 0)}")
    print(f"review_rows={verdict_counts.get('review', 0)}")
    print(f"drop_duplicate_rows={verdict_counts.get('drop_duplicate', 0)}")
    print(output_path)


if __name__ == "__main__":
    main()
