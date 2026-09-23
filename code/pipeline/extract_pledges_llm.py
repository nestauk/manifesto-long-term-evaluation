#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError


ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "analysis"
DOCUMENTS_CSV = ANALYSIS_DIR / "documents.csv"
OUTPUT_CSV = ANALYSIS_DIR / "commitments_candidates.csv"
OUTPUT_JSONL = ANALYSIS_DIR / "commitments_candidates.jsonl"
ENV_PATH = ROOT / ".env"
CACHE_DIR = ROOT / ".cache" / "llm" / "extract_commitments"

SYSTEM_PROMPT = """You extract policy commitments from UK political manifestos.

Return only valid JSON with this shape:
{
  "quotes": [
    "exact contiguous quote from the source chunk",
    "exact contiguous quote from the source chunk"
  ]
}

Rules:
- Extract only distinct policy commitments.
- Exclude rhetoric, criticism, values statements, section slogans, mission headings, broad goals, and aspirational framing.
- Exclude retrospective claims about what the party or government already did, historical record statements, and status or progress updates about what is already being achieved.
- Prefer commitments with at least one concrete policy signal such as an action verb, number, funding mechanism, institution, law, timeline, target, or delivery mechanism.
- Prefer forward-looking commitments about what the party or government will do, shall do, plans to do, or commits to do.
- Prefer atomic commitments. If a paragraph contains multiple commitments, split them.
- Do not extract high-level mission lines unless they themselves contain a concrete policy action or measurable target.
- Do not paraphrase, summarize, simplify, or modernize the wording.
- Every item in `quotes` must be copied exactly from the chunk.
- Return at most the requested number of quotes.
- If there are no real commitments, return {"quotes":[]}.
- Do not wrap JSON in markdown fences.
"""

JSON_REPAIR_SYSTEM_PROMPT = """You repair malformed JSON.

Return only valid JSON.
Do not add commentary.
Preserve the original structure and content as closely as possible.
"""

USER_TEMPLATE = """Document metadata:
- party: {party_name}
- year: {year}
- title: {title}
- chunk_id: {chunk_id}
- return no more than {max_pledges} pledges for this chunk

Task:
Extract exact policy commitment quotes from the chunk below.

Only extract text that a researcher could score later as a concrete manifesto commitment.
Do not extract:
- section headings
- mission statements
- vague intentions without a delivery mechanism
- generic promises like "build a better Britain" unless paired with a concrete action
- retrospective or historical record claims
- status or progress lines such as "we are set to achieve" or "these measures helped"

Good examples:
- "Cut NHS waiting times with 40,000 more appointments each week..."
- "Set up Great British Energy..."

Bad examples:
- "Kickstart economic growth..."
- "Build an NHS fit for the future..."
- "The party made the retention of..."
- "We are set to achieve..."
- "These measures helped to..."

Chunk:
\"\"\"
{chunk_text}
\"\"\"
"""


@dataclass
class Chunk:
    doc_id: str
    local_path: str
    party_slug: str
    party_name: str
    year: str
    title: str
    chunk_id: str
    chunk_index: int
    char_start: int
    char_end: int
    chunk_text: str


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("[e]", "e")
    text = text.replace("(e)", "e")
    text = re.sub(r"\[\s*([A-Za-z])\s*\]", r"\1", text)
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def clean_text_for_extraction(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"\f", "\n", text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text)

    cleaned_paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        raw_lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        lines = []
        for line in raw_lines:
            if should_drop_line(line):
                continue
            lines.append(line)
        if not lines:
            continue
        if len(lines) == 1 and re.fullmatch(r"\d+", lines[0]):
            continue
        cleaned = " ".join(lines)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            cleaned_paragraphs.extend(split_structured_block(cleaned))

    return "\n\n".join(cleaned_paragraphs)


def split_structured_block(text: str) -> list[str]:
    bullet_markers = ("•", "§")
    if not any(marker in text for marker in bullet_markers):
        return [text]

    pieces = []
    current = []
    tokens = re.split(r"(?=(?:•|§)\s*)", text)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token[0] in bullet_markers:
            if current:
                joined = " ".join(current).strip()
                if joined:
                    pieces.append(joined)
                current = []
            pieces.append(re.sub(r"^\s*[•§]\s*", "", token).strip())
        else:
            current.append(token)
    if current:
        joined = " ".join(current).strip()
        if joined:
            pieces.append(joined)
    return pieces or [text]


def should_drop_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    if re.fullmatch(r"Change Labour Party Manifesto 2024", stripped):
        return True
    if re.fullmatch(r"Clear Plan\. Bold Action\. Secure Future\.", stripped):
        return True
    if re.fullmatch(r"(Contents|Foreword)", stripped):
        return False
    if re.fullmatch(r"\d+\s+[A-Z][A-Za-z .'-]{0,40}$", stripped):
        return True
    if re.fullmatch(r"[A-Z][A-Za-z .'-]{0,40}\s+\d+$", stripped):
        return True
    if re.fullmatch(r"\d+\s+[A-Z][A-Za-z .'-]{0,20}\.?$", stripped):
        return True
    return False


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def paragraph_chunks(text: str, chunk_chars: int, overlap_chars: int) -> Iterable[tuple[int, int, str]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return

    starts = []
    pos = 0
    for paragraph in paragraphs:
        starts.append(pos)
        pos += len(paragraph) + 2

    i = 0
    while i < len(paragraphs):
        start = starts[i]
        parts = [paragraphs[i]]
        end = start + len(paragraphs[i])
        j = i + 1
        while j < len(paragraphs):
            candidate = "\n\n".join(parts + [paragraphs[j]])
            if len(candidate) > chunk_chars and parts:
                break
            parts.append(paragraphs[j])
            end = starts[j] + len(paragraphs[j])
            j += 1

        chunk = "\n\n".join(parts).strip()
        if chunk:
            yield start, end, chunk

        if j >= len(paragraphs):
            break

        overlap_target = max(1, overlap_chars)
        back = len(parts) - 1
        overlap_used = 0
        while back > 0 and overlap_used < overlap_target:
            overlap_used += len(parts[back]) + 2
            back -= 1
        i = max(i + 1, i + back + 1)


def build_chunks(row: dict, chunk_chars: int, overlap_chars: int) -> list[Chunk]:
    text = clean_text_for_extraction(row["full_text"])
    chunks = []
    for idx, (char_start, char_end, chunk_text) in enumerate(paragraph_chunks(text, chunk_chars, overlap_chars)):
        chunks.append(
            Chunk(
                doc_id=row["doc_id"],
                local_path=row["local_path"],
                party_slug=row["party_slug"],
                party_name=row["party_name"],
                year=row["year"],
                title=row["title"],
                chunk_id=f"{row['doc_id']}-{idx:03d}",
                chunk_index=idx,
                char_start=char_start,
                char_end=char_end,
                chunk_text=chunk_text,
            )
        )
    return chunks


def parse_json_object(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output did not contain a JSON object")
    return json.loads(text[start:end + 1])


def cache_key(*parts: str) -> str:
    payload = "\n\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".tmp.",
        delete=False,
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def sleep_with_backoff(
    attempt: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> float:
    capped = min(backoff_max_seconds, backoff_base_seconds * (2 ** max(0, attempt - 1)))
    delay = capped * (0.5 + random.random())
    time.sleep(delay)
    return round(delay, 2)


def create_chat_completion_with_retries(
    client: OpenAI,
    *,
    model: str,
    temperature: float,
    max_output_tokens: int,
    response_format: dict,
    messages: list[dict],
    max_api_retries: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
):
    last_exc = None
    for attempt in range(1, max_api_retries + 2):
        try:
            return client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_output_tokens,
                response_format=response_format,
                messages=messages,
            )
        except (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError) as exc:
            last_exc = exc
            if attempt > max_api_retries:
                break
            delay = sleep_with_backoff(attempt, backoff_base_seconds, backoff_max_seconds)
            print(
                f"retrying after {exc.__class__.__name__} in {delay}s "
                f"(attempt {attempt}/{max_api_retries})",
                flush=True,
            )
    assert last_exc is not None
    raise last_exc


def repair_json(
    client: OpenAI,
    model: str,
    broken_text: str,
    max_output_tokens: int,
    max_api_retries: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> dict:
    key = cache_key("repair_json", model, str(max_output_tokens), broken_text)
    cache_path = CACHE_DIR / f"{key}.json"
    cached = read_cache(cache_path)
    if cached is not None:
        return cached["parsed"]
    last_exc = None
    repair_attempts = max(1, min(3, max_api_retries + 1))
    for repair_attempt in range(1, repair_attempts + 1):
        response = create_chat_completion_with_retries(
            client,
            model=model,
            temperature=0,
            max_output_tokens=max_output_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JSON_REPAIR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Repair this into valid JSON only:\n\n" + broken_text,
                },
            ],
            max_api_retries=max_api_retries,
            backoff_base_seconds=backoff_base_seconds,
            backoff_max_seconds=backoff_max_seconds,
        )
        content = response.choices[0].message.content or "{}"
        try:
            parsed = parse_json_object(content)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if repair_attempt >= repair_attempts:
                break
            delay = sleep_with_backoff(repair_attempt, backoff_base_seconds, backoff_max_seconds)
            print(
                f"retrying malformed JSON repair output in {delay}s "
                f"(attempt {repair_attempt}/{repair_attempts})",
                flush=True,
            )
            continue
        write_cache(
            cache_path,
            {
                "kind": "repair_json",
                "model": model,
                "max_output_tokens": max_output_tokens,
                "raw_response": content,
                "parsed": parsed,
            },
        )
        return parsed
    assert last_exc is not None
    raise ValueError(f"JSON repair failed after {repair_attempts} attempts: {last_exc}")


def locate_quote(chunk_text: str, quote: str) -> tuple[int | None, int | None]:
    if not quote:
        return None, None
    direct = chunk_text.find(quote)
    if direct != -1:
        return direct, direct + len(quote)
    # Fallback: ignore whitespace, punctuation normalization, and common PDF extraction artifacts.
    needle = normalize_for_match(quote)
    hay = normalize_for_match(chunk_text)
    if needle and needle in hay:
        return -1, -1
    return None, None


def seems_truncated(quote: str) -> bool:
    trimmed = quote.strip()
    if not trimmed:
        return True
    if re.search(r"\b(of|to|for|with|by|and|or|the|a|an)$", trimmed, re.I):
        return True
    if trimmed[-1].isalnum():
        return False
    return False


def dedupe_key(text: str) -> str:
    return normalize_for_match(text)


def result_quotes(result: dict) -> list[str]:
    quotes = result.get("quotes", [])
    if not isinstance(quotes, list):
        return []
    return quotes


def extract_chunk(
    client: OpenAI,
    model: str,
    chunk: Chunk,
    temperature: float,
    max_pledges: int,
    max_output_tokens: int,
    max_api_retries: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> dict:
    user_prompt = USER_TEMPLATE.format(
        party_name=chunk.party_name,
        year=chunk.year,
        title=chunk.title,
        chunk_id=chunk.chunk_id,
        max_pledges=max_pledges,
        chunk_text=chunk.chunk_text,
    )
    key = cache_key(
        "extract_chunk",
        model,
        str(temperature),
        str(max_pledges),
        str(max_output_tokens),
        SYSTEM_PROMPT,
        user_prompt,
    )
    cache_path = CACHE_DIR / f"{key}.json"
    cached = read_cache(cache_path)
    if cached is not None:
        return cached["parsed"]
    response = create_chat_completion_with_retries(
        client,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_api_retries=max_api_retries,
        backoff_base_seconds=backoff_base_seconds,
        backoff_max_seconds=backoff_max_seconds,
    )
    content = response.choices[0].message.content or "{}"
    try:
        parsed = parse_json_object(content)
    except (json.JSONDecodeError, ValueError):
        parsed = repair_json(
            client,
            model,
            content,
            max_output_tokens,
            max_api_retries=max_api_retries,
            backoff_base_seconds=backoff_base_seconds,
            backoff_max_seconds=backoff_max_seconds,
        )
    write_cache(
        cache_path,
        {
            "kind": "extract_chunk",
            "model": model,
            "temperature": temperature,
            "max_pledges": max_pledges,
            "max_output_tokens": max_output_tokens,
            "chunk_id": chunk.chunk_id,
            "raw_response": content,
            "parsed": parsed,
        },
    )
    return parsed


def write_csv(rows: list[dict], path: Path) -> None:
    fieldnames = [
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
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DOCUMENTS_CSV))
    parser.add_argument("--output-csv", default=str(OUTPUT_CSV))
    parser.add_argument("--output-jsonl", default=str(OUTPUT_JSONL))
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--limit-docs", type=int, default=0)
    parser.add_argument("--limit-chunks", type=int, default=0)
    parser.add_argument("--chunk-chars", type=int, default=9000)
    parser.add_argument("--overlap-chars", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-pledges-per-chunk", type=int, default=12)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--max-api-retries", type=int, default=6)
    parser.add_argument("--backoff-base-seconds", type=float, default=1.0)
    parser.add_argument("--backoff-max-seconds", type=float, default=30.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    csv.field_size_limit(sys.maxsize)

    input_path = Path(args.input)
    output_csv = Path(args.output_csv)
    output_jsonl = Path(args.output_jsonl)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if args.limit_docs:
        rows = rows[: args.limit_docs]

    chunks: list[Chunk] = []
    for row in rows:
        chunks.extend(build_chunks(row, args.chunk_chars, args.overlap_chars))

    if args.limit_chunks:
        chunks = chunks[: args.limit_chunks]

    if args.dry_run:
        print(f"documents={len(rows)} chunks={len(chunks)}")
        for chunk in chunks[:10]:
            print(chunk.chunk_id, chunk.local_path, len(chunk.chunk_text))
        return

    load_dotenv(ENV_PATH)

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    client = OpenAI()
    csv_rows = []
    seen_quotes: set[tuple[str, str]] = set()
    failed_chunks = 0
    with output_jsonl.open("w", encoding="utf-8") as raw_out:
        for chunk in chunks:
            print(f"chunk {chunk.chunk_id} {chunk.local_path}", flush=True)
            try:
                result = extract_chunk(
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
                raw_quotes = result_quotes(result)
                accepted_rows = []
                cap_truncated = False
                accepted_count = 0
                raw_quote_count = len(raw_quotes)
                for idx, quote in enumerate(raw_quotes):
                    if accepted_count >= args.max_pledges_per_chunk:
                        cap_truncated = True
                        break
                    quote = (quote or "").strip()
                    if not quote:
                        continue
                    if seems_truncated(quote):
                        continue
                    key = (chunk.doc_id, dedupe_key(quote))
                    if key in seen_quotes:
                        continue
                    start, end = locate_quote(chunk.chunk_text, quote)
                    validation_status = "exact_quote_match" if start is not None else "needs_review"
                    if start == -1 and end == -1:
                        validation_status = "normalized_quote_match"
                    pledge_text = normalize_whitespace(quote)
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
                            "chunk_id": chunk.chunk_id,
                            "chunk_index": chunk.chunk_index,
                            "chunk_char_start": chunk.char_start,
                            "chunk_char_end": chunk.char_end,
                            "commitment_text": pledge_text,
                            "supporting_quote": quote,
                            "quote_char_start": "" if start in (None, -1) else chunk.char_start + start,
                            "quote_char_end": "" if end in (None, -1) else chunk.char_start + end,
                            "validation_status": validation_status,
                            "extraction_mode": "verbatim_quote_only",
                        }
                    )
                    accepted_count += 1
                record = {
                    "chunk_id": chunk.chunk_id,
                    "local_path": chunk.local_path,
                    "result": result,
                    "raw_quote_count": raw_quote_count,
                    "accepted_quote_count": len(accepted_rows),
                    "requested_max_pledges_per_chunk": args.max_pledges_per_chunk,
                    "cap_truncated": cap_truncated,
                }
                csv_rows.extend(accepted_rows)
            except Exception as exc:
                failed_chunks += 1
                print(f"chunk failed {chunk.chunk_id}: {exc}", flush=True)
                record = {
                    "chunk_id": chunk.chunk_id,
                    "local_path": chunk.local_path,
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

    write_csv(csv_rows, output_csv)
    print(f"wrote {len(csv_rows)} pledge candidates to {output_csv}")
    print(f"wrote raw responses to {output_jsonl}")
    if failed_chunks:
        print(f"completed with {failed_chunks} chunk failures", flush=True)


if __name__ == "__main__":
    main()
