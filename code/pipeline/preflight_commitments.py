#!/usr/bin/env python3
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


TEXT_FIELDS = ["commitment_text", "supporting_quote", "policy_context"]
HIGH_RISK_SEMANTIC = {"review", "drop_duplicate"}
HIGH_RISK_SCREEN = {"review", "drop"}
HIGH_RISK_GLOBAL = {"review", "drop_duplicate"}
DEFAULT_EXTRACT_CAP = 12
DEFAULT_CHUNK_CAP_RATE_THRESHOLD = 0.25
DEFAULT_SCREEN_REVIEW_RATE_THRESHOLD = 0.20
DEFAULT_NEEDS_REVIEW_RATE_THRESHOLD = 0.10
DEFAULT_ELIGIBLE_RATE_THRESHOLD = 0.70
DEFAULT_CONTEXT_NONEMPTY_RATE_THRESHOLD = 0.80
DEFAULT_CONTEXT_MAX_CHARS = 1200


def normalized_label(value: str) -> str:
    return str(value or "").strip().lower()


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


def has_nul_bytes(row: dict) -> bool:
    return any("\x00" in str(row.get(field, "")) for field in TEXT_FIELDS)


def has_policy_context(row: dict) -> bool:
    return bool((row.get("policy_context") or "").strip())


def context_len(row: dict) -> int:
    return len((row.get("policy_context") or "").strip())


def effective_chunk_id(row: dict) -> str:
    return str(
        row.get("rerun_chunk_id")
        or row.get("effective_chunk_id")
        or row.get("chunk_id")
        or ""
    ).strip()


def eligible_for_scoring(row: dict) -> bool:
    if not (row.get("commitment_text") or "").strip():
        return False
    if has_nul_bytes(row):
        return False

    screen_verdict = normalized_label(row.get("screen_verdict", ""))
    if screen_verdict and screen_verdict != "keep":
        return False

    global_verdict = normalized_label(row.get("global_duplicate_verdict", ""))
    if global_verdict and global_verdict != "unique":
        return False

    semantic_verdict = normalized_label(row.get("semantic_verdict", ""))
    if semantic_verdict in {"drop_duplicate", "review"}:
        return False

    return True


def high_trust_proxy(row: dict) -> bool:
    if not eligible_for_scoring(row):
        return False
    if normalized_label(row.get("validation_status", "")) != "exact_quote_match":
        return False
    if normalized_label(row.get("review_priority", "")) == "high":
        return False
    if has_nul_bytes(row):
        return False
    return True


def risk_band(row: dict) -> tuple[str, str]:
    reasons = []
    validation_status = normalized_label(row.get("validation_status", ""))
    review_priority = normalized_label(row.get("review_priority", ""))
    screen_verdict = normalized_label(row.get("screen_verdict", ""))
    global_verdict = normalized_label(row.get("global_duplicate_verdict", ""))
    semantic_verdict = normalized_label(row.get("semantic_verdict", ""))
    heuristic_flags = (row.get("heuristic_flags") or "").strip()

    if has_nul_bytes(row):
        reasons.append("nul_bytes")
    if validation_status == "needs_review":
        reasons.append("validation_needs_review")
    if review_priority == "high":
        reasons.append("review_priority_high")
    if screen_verdict in HIGH_RISK_SCREEN:
        reasons.append(f"screen_{screen_verdict}")
    if global_verdict in HIGH_RISK_GLOBAL:
        reasons.append(f"global_duplicate_{global_verdict}")
    if semantic_verdict in HIGH_RISK_SEMANTIC:
        reasons.append(f"semantic_{semantic_verdict}")

    if reasons:
        return "high", ";".join(reasons)

    medium_reasons = []
    if validation_status == "normalized_quote_match":
        medium_reasons.append("normalized_quote_match")
    if review_priority == "medium":
        medium_reasons.append("review_priority_medium")
    if heuristic_flags:
        medium_reasons.append("heuristic_flags")
    if not has_policy_context(row):
        medium_reasons.append("missing_policy_context")

    if medium_reasons:
        return "medium", ";".join(medium_reasons)
    return "low", "clean_proxy"


def count_chunks_at_or_above_cap(rows: list[dict], extract_cap: int) -> tuple[int, int]:
    if extract_cap <= 0:
        return 0, 0
    chunk_counts = Counter(effective_chunk_id(row) for row in rows if effective_chunk_id(row))
    nonempty_chunks = len(chunk_counts)
    chunks_at_cap = sum(1 for count in chunk_counts.values() if count >= extract_cap)
    return nonempty_chunks, chunks_at_cap


def rate(value: int, total: int) -> str:
    return f"{(value / total):.4f}" if total else "0.0000"


def doc_status(summary: dict, thresholds: dict) -> tuple[str, str]:
    reasons = []
    if int(summary["nul_rows"]) > 0:
        reasons.append("nul_rows")
    if int(summary["policy_context_over_cap_rows"]) > 0:
        reasons.append("policy_context_over_cap_rows")
    if float(summary["policy_context_nonempty_rate"]) < thresholds["context_nonempty_rate_threshold"]:
        reasons.append("low_context_coverage")
    if reasons:
        return "fix_text_or_context", ";".join(reasons)

    reasons = []
    if float(summary["nonempty_chunk_at_or_above_cap_rate"]) >= thresholds["chunk_cap_rate_threshold"]:
        reasons.append("chunk_cap_pressure")
    if reasons:
        return "rerun_extraction", ";".join(reasons)

    reasons = []
    if float(summary["screen_review_rate"]) >= thresholds["screen_review_rate_threshold"]:
        reasons.append("high_screen_review_rate")
    if float(summary["validation_needs_review_rate"]) >= thresholds["needs_review_rate_threshold"]:
        reasons.append("high_needs_review_rate")
    if float(summary["eligible_for_scoring_rate"]) < thresholds["eligible_rate_threshold"]:
        reasons.append("low_eligible_for_scoring_rate")
    if reasons:
        return "review_before_scoring", ";".join(reasons)

    return "ready", "meets_default_thresholds"


def summarize_doc(rows: list[dict], extract_cap: int, context_max_chars: int, thresholds: dict) -> dict:
    first = rows[0]
    validation = Counter(normalized_label(row.get("validation_status", "")) for row in rows)
    review_priority = Counter(normalized_label(row.get("review_priority", "")) for row in rows)
    screen = Counter(normalized_label(row.get("screen_verdict", "")) or "missing" for row in rows)
    global_dups = Counter(normalized_label(row.get("global_duplicate_verdict", "")) or "missing" for row in rows)
    semantic = Counter(normalized_label(row.get("semantic_verdict", "")) or "missing" for row in rows)
    risk = Counter(risk_band(row)[0] for row in rows)

    total = len(rows)
    heuristic_flagged_rows = sum(1 for row in rows if (row.get("heuristic_flags") or "").strip())
    context_nonempty_rows = sum(1 for row in rows if has_policy_context(row))
    context_over_cap_rows = sum(1 for row in rows if context_len(row) > context_max_chars)
    nul_rows = sum(1 for row in rows if has_nul_bytes(row))
    eligible_rows = sum(1 for row in rows if eligible_for_scoring(row))
    high_trust_rows = sum(1 for row in rows if high_trust_proxy(row))
    nonempty_chunks, chunks_at_cap = count_chunks_at_or_above_cap(rows, extract_cap)

    summary = {
        "doc_id": first.get("doc_id", ""),
        "party_slug": first.get("party_slug", ""),
        "party_name": first.get("party_name", ""),
        "year": first.get("year", ""),
        "title": first.get("title", ""),
        "rows_total": total,
        "eligible_for_scoring_rows": eligible_rows,
        "eligible_for_scoring_rate": rate(eligible_rows, total),
        "high_trust_proxy_rows": high_trust_rows,
        "high_trust_proxy_rate": rate(high_trust_rows, total),
        "validation_exact_quote_match_rows": validation.get("exact_quote_match", 0),
        "validation_normalized_quote_match_rows": validation.get("normalized_quote_match", 0),
        "validation_needs_review_rows": validation.get("needs_review", 0),
        "validation_needs_review_rate": rate(validation.get("needs_review", 0), total),
        "validation_other_rows": total
        - validation.get("exact_quote_match", 0)
        - validation.get("normalized_quote_match", 0)
        - validation.get("needs_review", 0),
        "review_priority_high_rows": review_priority.get("high", 0),
        "review_priority_medium_rows": review_priority.get("medium", 0),
        "heuristic_flagged_rows": heuristic_flagged_rows,
        "screen_keep_rows": screen.get("keep", 0),
        "screen_review_rows": screen.get("review", 0),
        "screen_review_rate": rate(screen.get("review", 0), total),
        "screen_drop_rows": screen.get("drop", 0),
        "global_unique_rows": global_dups.get("unique", 0),
        "global_review_rows": global_dups.get("review", 0),
        "global_drop_duplicate_rows": global_dups.get("drop_duplicate", 0),
        "semantic_standalone_rows": semantic.get("standalone", 0),
        "semantic_parent_rows": semantic.get("parent", 0),
        "semantic_child_rows": semantic.get("child", 0),
        "semantic_review_rows": semantic.get("review", 0),
        "semantic_drop_duplicate_rows": semantic.get("drop_duplicate", 0),
        "nonempty_chunk_rows": nonempty_chunks,
        "nonempty_chunks_at_or_above_cap_rows": chunks_at_cap,
        "nonempty_chunk_at_or_above_cap_rate": rate(chunks_at_cap, nonempty_chunks),
        "policy_context_nonempty_rows": context_nonempty_rows,
        "policy_context_nonempty_rate": rate(context_nonempty_rows, total),
        "policy_context_over_cap_rows": context_over_cap_rows,
        "nul_rows": nul_rows,
        "high_risk_rows": risk.get("high", 0),
        "medium_risk_rows": risk.get("medium", 0),
        "low_risk_rows": risk.get("low", 0),
    }
    status, reason = doc_status(summary, thresholds)
    summary["doc_status"] = status
    summary["doc_status_reason"] = reason
    return summary


def build_chunk_rerun_rows(rows: list[dict], extract_cap: int) -> list[dict]:
    if extract_cap <= 0:
        return []
    by_chunk: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        chunk_key = effective_chunk_id(row)
        if chunk_key:
            by_chunk[chunk_key].append(row)

    rerun_rows = []
    for chunk_id, chunk_rows in sorted(by_chunk.items(), key=lambda item: row_order(item[1][0])):
        if len(chunk_rows) < extract_cap:
            continue
        first = chunk_rows[0]
        chunk_starts = []
        chunk_ends = []
        for row in chunk_rows:
            try:
                chunk_starts.append(int(row.get("chunk_char_start") or ""))
                chunk_ends.append(int(row.get("chunk_char_end") or ""))
            except ValueError:
                continue
        rerun_rows.append(
            {
                "doc_id": first.get("doc_id", ""),
                "party_slug": first.get("party_slug", ""),
                "party_name": first.get("party_name", ""),
                "year": first.get("year", ""),
                "title": first.get("title", ""),
                "chunk_id": first.get("chunk_id", ""),
                "effective_chunk_id": chunk_id,
                "source_chunk_id": first.get("source_chunk_id", "") or first.get("chunk_id", ""),
                "chunk_index": first.get("chunk_index", ""),
                "chunk_char_start": min(chunk_starts) if chunk_starts else first.get("chunk_char_start", ""),
                "chunk_char_end": max(chunk_ends) if chunk_ends else first.get("chunk_char_end", ""),
                "rows_in_chunk": len(chunk_rows),
                "rerun_reason": "chunk_at_or_above_extract_cap",
            }
        )
    return rerun_rows


def choose_audit_rows(rows: list[dict], sample_size: int, max_per_doc: int) -> list[dict]:
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        band, reason = risk_band(row)
        out = dict(row)
        out["audit_risk_band"] = band
        out["audit_reason"] = reason
        by_doc[row.get("doc_id", "")].append(out)

    for doc_rows in by_doc.values():
        doc_rows.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}[row["audit_risk_band"]], row_order(row)))

    def pick_from_doc(doc_id: str, allowed_bands: set[str], chosen_ids: set[str]) -> dict | None:
        for row in by_doc[doc_id]:
            commitment_id = row.get("commitment_id", "")
            if commitment_id in chosen_ids:
                continue
            if row["audit_risk_band"] not in allowed_bands:
                continue
            return row
        return None

    chosen_ids = set()
    per_doc = Counter()
    chosen = []

    for doc_id in sorted(by_doc):
        if len(chosen) >= sample_size or per_doc[doc_id] >= max_per_doc:
            continue
        candidate = pick_from_doc(doc_id, {"high"}, chosen_ids)
        if candidate is None:
            continue
        chosen.append(candidate)
        chosen_ids.add(candidate.get("commitment_id", ""))
        per_doc[doc_id] += 1

    for doc_id in sorted(by_doc):
        if len(chosen) >= sample_size or per_doc[doc_id] >= max_per_doc:
            continue
        candidate = pick_from_doc(doc_id, {"medium", "low"}, chosen_ids)
        if candidate is None:
            continue
        chosen.append(candidate)
        chosen_ids.add(candidate.get("commitment_id", ""))
        per_doc[doc_id] += 1

    for band in ["high", "medium", "low"]:
        while len(chosen) < sample_size:
            made_pick = False
            for doc_id in sorted(by_doc):
                if per_doc[doc_id] >= max_per_doc:
                    continue
                row = pick_from_doc(doc_id, {band}, chosen_ids)
                if row is not None:
                    chosen.append(row)
                    chosen_ids.add(row.get("commitment_id", ""))
                    per_doc[doc_id] += 1
                    made_pick = True
                if len(chosen) >= sample_size:
                    break
            if not made_pick:
                break

    if len(chosen) < sample_size:
        for doc_id in sorted(by_doc):
            if len(chosen) >= sample_size:
                break
            while per_doc[doc_id] < max_per_doc and len(chosen) < sample_size:
                row = pick_from_doc(doc_id, {"high", "medium", "low"}, chosen_ids)
                if row is None:
                    break
                chosen.append(row)
                chosen_ids.add(row.get("commitment_id", ""))
                per_doc[doc_id] += 1

    return chosen


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--audit-csv", required=True)
    parser.add_argument("--chunk-rerun-csv")
    parser.add_argument("--audit-sample-size", type=int, default=120)
    parser.add_argument("--audit-max-per-doc", type=int, default=2)
    parser.add_argument("--extract-cap", type=int, default=DEFAULT_EXTRACT_CAP)
    parser.add_argument("--chunk-cap-rate-threshold", type=float, default=DEFAULT_CHUNK_CAP_RATE_THRESHOLD)
    parser.add_argument("--screen-review-rate-threshold", type=float, default=DEFAULT_SCREEN_REVIEW_RATE_THRESHOLD)
    parser.add_argument("--needs-review-rate-threshold", type=float, default=DEFAULT_NEEDS_REVIEW_RATE_THRESHOLD)
    parser.add_argument("--eligible-rate-threshold", type=float, default=DEFAULT_ELIGIBLE_RATE_THRESHOLD)
    parser.add_argument(
        "--context-nonempty-rate-threshold", type=float, default=DEFAULT_CONTEXT_NONEMPTY_RATE_THRESHOLD
    )
    parser.add_argument("--context-max-chars", type=int, default=DEFAULT_CONTEXT_MAX_CHARS)
    args = parser.parse_args()

    csv.field_size_limit(sys.maxsize)
    input_path = Path(args.input)
    with input_path.open(newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
        input_fieldnames = reader_fieldnames = list(rows[0].keys()) if rows else []

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_doc[row.get("doc_id", "")].append(row)

    thresholds = {
        "chunk_cap_rate_threshold": args.chunk_cap_rate_threshold,
        "screen_review_rate_threshold": args.screen_review_rate_threshold,
        "needs_review_rate_threshold": args.needs_review_rate_threshold,
        "eligible_rate_threshold": args.eligible_rate_threshold,
        "context_nonempty_rate_threshold": args.context_nonempty_rate_threshold,
    }

    summary_rows = [
        summarize_doc(
            by_doc[doc_id],
            extract_cap=args.extract_cap,
            context_max_chars=args.context_max_chars,
            thresholds=thresholds,
        )
        for doc_id in sorted(by_doc)
    ]
    summary_rows.sort(key=lambda row: (row.get("year", ""), row.get("party_slug", ""), row.get("title", "")))
    summary_fieldnames = list(summary_rows[0].keys()) if summary_rows else []
    write_csv(Path(args.summary_csv), summary_rows, summary_fieldnames)

    audit_rows = choose_audit_rows(rows, args.audit_sample_size, args.audit_max_per_doc)
    audit_fieldnames = list(input_fieldnames)
    for key in ["audit_risk_band", "audit_reason"]:
        if key not in audit_fieldnames:
            audit_fieldnames.append(key)
    write_csv(Path(args.audit_csv), audit_rows, audit_fieldnames)

    if args.chunk_rerun_csv:
        chunk_rerun_rows = build_chunk_rerun_rows(rows, args.extract_cap)
        chunk_rerun_fieldnames = [
            "doc_id",
            "party_slug",
            "party_name",
            "year",
            "title",
            "chunk_id",
            "effective_chunk_id",
            "source_chunk_id",
            "chunk_index",
            "chunk_char_start",
            "chunk_char_end",
            "rows_in_chunk",
            "rerun_reason",
        ]
        write_csv(Path(args.chunk_rerun_csv), chunk_rerun_rows, chunk_rerun_fieldnames)

    corpus_total = len(rows)
    eligible_total = sum(1 for row in rows if eligible_for_scoring(row))
    high_trust_total = sum(1 for row in rows if high_trust_proxy(row))
    risk_counts = Counter(risk_band(row)[0] for row in rows)
    status_counts = Counter(row["doc_status"] for row in summary_rows)

    print(f"docs={len(by_doc)}")
    print(f"rows={corpus_total}")
    print(f"eligible_for_scoring_rows={eligible_total}")
    print(f"high_trust_proxy_rows={high_trust_total}")
    print(f"high_risk_rows={risk_counts.get('high', 0)}")
    print(f"medium_risk_rows={risk_counts.get('medium', 0)}")
    print(f"low_risk_rows={risk_counts.get('low', 0)}")
    print(f"docs_ready={status_counts.get('ready', 0)}")
    print(f"docs_review_before_scoring={status_counts.get('review_before_scoring', 0)}")
    print(f"docs_rerun_extraction={status_counts.get('rerun_extraction', 0)}")
    print(f"docs_fix_text_or_context={status_counts.get('fix_text_or_context', 0)}")
    print(args.summary_csv)
    print(args.audit_csv)
    if args.chunk_rerun_csv:
        print(args.chunk_rerun_csv)


if __name__ == "__main__":
    main()
