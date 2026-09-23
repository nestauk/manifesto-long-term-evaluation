#!/usr/bin/env python3
import argparse
import csv
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_CSV = ROOT / "analysis" / "documents.csv"
DEFAULT_INPUT = (
    ROOT
    / "analysis"
    / "extractions"
    / "corpus-rerun-4000-24-postprocess"
    / "commitments-screened-global-dedup.csv"
)
EXTRACTOR_PATH = Path(__file__).resolve().parent / "extract_pledges_llm.py"


def load_extractor():
    spec = importlib.util.spec_from_file_location("extract_module", EXTRACTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def clip_text(text: str, max_chars: int) -> str:
    snippet = (text or "").strip()
    if len(snippet) <= max_chars:
        return snippet
    clipped = snippet[:max_chars].rsplit(" ", 1)[0].strip()
    return clipped or snippet[:max_chars].strip()


def split_unit_spans(text: str, break_re: re.Pattern[str]) -> list[tuple[int, int, str]]:
    spans = []
    start = 0
    for match in break_re.finditer(text):
        end = match.start()
        unit_start = start
        unit_end = end
        while unit_start < unit_end and text[unit_start].isspace():
            unit_start += 1
        while unit_end > unit_start and text[unit_end - 1].isspace():
            unit_end -= 1
        if unit_start < unit_end:
            spans.append((unit_start, unit_end, text[unit_start:unit_end]))
        start = match.end()

    unit_start = start
    unit_end = len(text)
    while unit_start < unit_end and text[unit_start].isspace():
        unit_start += 1
    while unit_end > unit_start and text[unit_end - 1].isspace():
        unit_end -= 1
    if unit_start < unit_end:
        spans.append((unit_start, unit_end, text[unit_start:unit_end]))
    return spans


def find_span_index(spans: list[tuple[int, int, str]], start: int, end: int) -> int | None:
    anchor_mid = start if end <= start else start + ((end - start) // 2)
    for idx, (span_start, span_end, _) in enumerate(spans):
        if span_start <= anchor_mid < span_end:
            return idx
        if start < span_end and end > span_start:
            return idx
    return None


def expand_units(spans: list[tuple[int, int, str]], anchor_idx: int, max_chars: int, joiner: str) -> str:
    selected = [spans[anchor_idx][2]]
    total_len = len(selected[0])

    left = anchor_idx - 1
    right = anchor_idx + 1
    while total_len < max_chars and (left >= 0 or right < len(spans)):
        added = False
        if left >= 0:
            candidate = spans[left][2]
            extra = len(joiner) if selected else 0
            if total_len + extra + len(candidate) <= max_chars:
                selected.insert(0, candidate)
                total_len += extra + len(candidate)
                added = True
            left -= 1
        if total_len >= max_chars:
            break
        if right < len(spans):
            candidate = spans[right][2]
            extra = len(joiner) if selected else 0
            if total_len + extra + len(candidate) <= max_chars:
                selected.append(candidate)
                total_len += extra + len(candidate)
                added = True
            right += 1
        if not added:
            break

    return joiner.join(selected).strip()


def clip_around_anchor(text: str, start: int, end: int, max_chars: int) -> str:
    start = max(0, start)
    end = min(len(text), end)
    if start >= end:
        return clip_text(text, max_chars)
    if end - start >= max_chars:
        return clip_text(text[start:end], max_chars)

    extra = max_chars - (end - start)
    window_start = max(0, start - (extra // 2))
    window_end = min(len(text), end + (extra - (extra // 2)))

    while window_start > 0 and not text[window_start - 1].isspace() and window_end - window_start < max_chars:
        window_start -= 1
    while window_end < len(text) and not text[window_end].isspace() and window_end - window_start < max_chars:
        window_end += 1

    while window_end - window_start > max_chars:
        if start - window_start >= window_end - end and window_start < start:
            window_start += 1
        elif window_end > end:
            window_end -= 1
        else:
            break

    return text[window_start:window_end].strip()


def build_context_around_positions(text: str, start: int, end: int, max_chars: int) -> str:
    paragraph_spans = split_unit_spans(text, re.compile(r"\n\s*\n"))
    if not paragraph_spans:
        return clip_around_anchor(text, start, end, max_chars)

    paragraph_idx = find_span_index(paragraph_spans, start, end)
    if paragraph_idx is None:
        return clip_around_anchor(text, start, end, max_chars)

    paragraph_start, paragraph_end, paragraph_text = paragraph_spans[paragraph_idx]
    if len(paragraph_text) > max_chars:
        relative_start = max(0, start - paragraph_start)
        relative_end = max(relative_start + 1, min(len(paragraph_text), end - paragraph_start))
        return clip_around_anchor(paragraph_text, relative_start, relative_end, max_chars)

    return expand_units(paragraph_spans, paragraph_idx, max_chars, "\n\n")


def expand_window(text: str, start: int, end: int, max_chars: int) -> str:
    start = max(0, start)
    end = min(len(text), end)
    if start >= end:
        return ""

    target_len = max_chars
    extra = max(0, target_len - (end - start))
    left_extra = extra // 2
    right_extra = extra - left_extra
    window_start = max(0, start - left_extra)
    window_end = min(len(text), end + right_extra)

    raw_snippet = text[window_start:window_end].strip()
    if raw_snippet and len(raw_snippet) <= max_chars:
        return raw_snippet

    para_start = text.rfind("\n\n", 0, window_start)
    para_end = text.find("\n\n", window_end)
    if para_start != -1:
        window_start = para_start + 2
    if para_end != -1:
        window_end = para_end

    snippet = text[window_start:window_end].strip()
    if len(snippet) > max_chars:
        snippet = clip_text(text[start:end], max_chars)
    return clip_text(snippet, max_chars)


def score_paragraph(module, paragraph: str, anchor: str) -> tuple[int, int, int]:
    normalized_paragraph = module.normalize_for_match(paragraph)
    normalized_anchor = module.normalize_for_match(anchor)
    if not normalized_paragraph or not normalized_anchor:
        return (0, 0, 0)

    if normalized_anchor in normalized_paragraph:
        return (3, len(normalized_anchor), len(paragraph))

    anchor_tokens = [token for token in normalized_anchor.split() if len(token) > 2]
    if not anchor_tokens:
        return (0, 0, 0)
    overlap = sum(1 for token in anchor_tokens if token in normalized_paragraph)
    return (1 if overlap else 0, overlap, -abs(len(paragraph) - len(anchor)))


def build_context(module, chunk_text: str, commitment_text: str, supporting_quote: str, max_chars: int) -> str:
    paragraphs = split_paragraphs(chunk_text)
    if not paragraphs:
        return clip_text(chunk_text, max_chars)

    anchor = (supporting_quote or "").strip() or (commitment_text or "").strip()
    if not anchor:
        return paragraphs[0][:max_chars].strip()

    scored = []
    for idx, paragraph in enumerate(paragraphs):
        scored.append((score_paragraph(module, paragraph, anchor), idx))
    scored.sort(reverse=True)
    best_idx = scored[0][1]

    selected = [paragraphs[best_idx]]
    total_len = len(selected[0])

    left = best_idx - 1
    right = best_idx + 1
    while total_len < max_chars and (left >= 0 or right < len(paragraphs)):
        if left >= 0:
            candidate = paragraphs[left]
            if total_len + len(candidate) + 2 <= max_chars:
                selected.insert(0, candidate)
                total_len += len(candidate) + 2
            left -= 1
        if total_len >= max_chars:
            break
        if right < len(paragraphs):
            candidate = paragraphs[right]
            if total_len + len(candidate) + 2 <= max_chars:
                selected.append(candidate)
                total_len += len(candidate) + 2
            right += 1

    return clip_text("\n\n".join(selected), max_chars)


def build_context_from_positions(
    module,
    cleaned_text: str,
    row: dict,
    max_chars: int,
) -> str:
    try:
        start = int(row.get("quote_char_start") or "")
        end = int(row.get("quote_char_end") or "")
    except ValueError:
        return ""
    if start < 0 or end <= start:
        return ""
    context = build_context_around_positions(cleaned_text, start, end, max_chars)
    anchor = (row.get("supporting_quote") or "").strip() or (row.get("commitment_text") or "").strip()
    normalized_anchor = module.normalize_for_match(anchor)
    if not normalized_anchor:
        return context
    if normalized_anchor in module.normalize_for_match(context):
        return context
    # Some stored quote positions land on a lead-in line or separator block rather
    # than the paragraph containing the commitment. Fall back to the persisted
    # chunk span and re-anchor on the quote text itself.
    return build_context_from_chunk_bounds(
        module=module,
        cleaned_text=cleaned_text,
        row=row,
        max_chars=max_chars,
    )


def build_context_from_chunk_bounds(
    module,
    cleaned_text: str,
    row: dict,
    max_chars: int,
) -> str:
    try:
        start = int(row.get("chunk_char_start") or "")
        end = int(row.get("chunk_char_end") or "")
    except ValueError:
        return ""
    if start < 0 or end <= start:
        return ""
    span_text = cleaned_text[start:end].strip()
    if not span_text:
        return ""
    # Treat extraction-time bounds as canonical provenance and choose the
    # tightest paragraph window inside that span.
    return build_context(
        module=module,
        chunk_text=span_text,
        commitment_text=row.get("commitment_text", ""),
        supporting_quote=row.get("supporting_quote", ""),
        max_chars=max_chars,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output")
    parser.add_argument("--max-context-chars", type=int, default=1200)
    args = parser.parse_args()

    csv.field_size_limit(sys.maxsize)
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    module = load_extractor()

    with DOCUMENTS_CSV.open(newline="", encoding="utf-8") as f:
        docs = {row["doc_id"]: row for row in csv.DictReader(f)}

    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(f for f in rows[0].keys()) if rows else []

    if "policy_context" not in fieldnames:
        fieldnames.append("policy_context")

    cleaned_text_cache: dict[str, str] = {}
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in cleaned_text_cache:
            cleaned_text_cache[doc_id] = module.clean_text_for_extraction(docs[doc_id]["full_text"])
        context = build_context_from_positions(
            module=module,
            cleaned_text=cleaned_text_cache[doc_id],
            row=row,
            max_chars=args.max_context_chars,
        )
        if context:
            row["policy_context"] = context
            continue
        context = build_context_from_chunk_bounds(
            module=module,
            cleaned_text=cleaned_text_cache[doc_id],
            row=row,
            max_chars=args.max_context_chars,
        )
        if context:
            row["policy_context"] = context
            continue
        row["policy_context"] = ""

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"rows={len(rows)}")
    print(output_path)


if __name__ == "__main__":
    main()
