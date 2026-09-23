#!/usr/bin/env python3
import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DOCUMENTS_CSV = ROOT / "analysis" / "documents.csv"
EXTRACTOR_PATH = Path(__file__).resolve().parent / "extract_pledges_llm.py"
CACHE_DIR = ROOT / ".cache" / "llm" / "adversarial_review"

SYSTEM_PROMPT = """You are reviewing extracted manifesto commitments adversarially.

Your task is to challenge whether each extracted quote should be kept as a standalone commitment.

Return valid JSON with this shape:
{
  "verdict": "keep" | "drop" | "review",
  "reason": "one short sentence"
}

Use these standards:
- "keep": a concrete standalone policy commitment that should remain as its own row
- "drop": too vague, fragmentary, duplicative, retrospective, slogan-like, context-dependent, or better treated as a heading/label
- "review": ambiguous borderline case where context is not decisive

Important decision rule:
- Judge the quote mainly on whether it works as a standalone commitment row.
- Use the chunk context only to confirm interpretation, not to rescue a weak quote.
- If the quote only becomes concrete when combined with neighboring text, prefer "drop" or "review", not "keep".

Keep only when the quote itself clearly expresses a future-facing policy action, change, rule, funding commitment, institutional change, legal change, delivery commitment, or other concrete governmental or party action.

Prefer "drop" for any of these:
- retrospective or past-tense record claims, including money already allocated or actions already taken
- statements of support, solidarity, principle, preference, priority, aspiration, objective, or vision without a concrete operative action
- section headings, noun-phrase fragments, package titles, labels, or unfinished reform slogans
- generic process or role language such as "under review", "seek to ensure", "play a vital role", or similarly vague formulations
- outcomes without a clear policy instrument
- constitutional preferences or negotiating stances stated without a specific action
- lines that name a reform area but do not say what will actually be done

Use "review" only for genuinely borderline cases where the quote is close to a real commitment but still lacks enough standalone clarity.

Be skeptical. When in doubt between "keep" and "drop" for a vague or context-dependent quote, choose "drop".
Do not add commentary outside the JSON.
"""

USER_TEMPLATE = """Document:
- party: {party}
- year: {year}
- title: {title}
- chunk_id: {chunk_id}

Candidate quote:
{quote}

Judge whether this quote should survive as a standalone scored row.
Do not rescue weak quotes just because the surrounding section is policy-heavy.

Bad patterns to drop:
- section headings or noun-phrase labels
- "our preferred system is ..."
- "X will play a vital role ..."
- past-tense funding or allocation claims
- support/solidarity statements without a policy mechanism
- broad reform labels like "new and fairer methods of financing ..."

Chunk context:
\"\"\"
{chunk_text}
\"\"\"
"""


def load_module():
    spec = importlib.util.spec_from_file_location("extract_module", EXTRACTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def parse_json_object(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json object")
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    module = load_module()
    module.load_dotenv(ENV_PATH)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    csv.field_size_limit(sys.maxsize)
    with open(args.input_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    with open(DOCUMENTS_CSV, newline="", encoding="utf-8") as f:
        docs = {row["doc_id"]: row for row in csv.DictReader(f)}

    cleaned_text_cache = {
        doc_id: module.clean_text_for_extraction(doc["full_text"])
        for doc_id, doc in docs.items()
    }
    client_local = threading.local()

    def get_client() -> OpenAI:
        client = getattr(client_local, "client", None)
        if client is None:
            client = OpenAI()
            client_local.client = client
        return client

    def review_row(index: int, row: dict) -> tuple[int, dict]:
        doc = docs[row["doc_id"]]
        doc_cache_key = row["doc_id"]

        chunk_text = ""
        try:
            char_start = int(row.get("chunk_char_start", "") or 0)
            char_end = int(row.get("chunk_char_end", "") or 0)
        except ValueError:
            char_start = 0
            char_end = 0

        if char_end > char_start:
            cleaned_text = cleaned_text_cache[doc_cache_key]
            chunk_text = cleaned_text[char_start:char_end].strip()

        if not chunk_text:
            raise SystemExit(
                f"missing usable chunk_text for commitment_id={row.get('commitment_id', '')} "
                f"chunk_id={row.get('chunk_id', '')}; expected chunk_char_start/chunk_char_end"
            )

        prompt = USER_TEMPLATE.format(
            party=row["party_name"],
            year=row["year"],
            title=row["title"],
            chunk_id=row["chunk_id"],
            quote=row["commitment_text"],
            chunk_text=chunk_text,
        )
        key = cache_key("adversarial_review", args.model, SYSTEM_PROMPT, prompt)
        cache_path = CACHE_DIR / f"{key}.json"
        cached = read_cache(cache_path)
        if cached is not None:
            verdict = cached["parsed"]
        else:
            response = get_client().chat.completions.create(
                model=args.model,
                temperature=0,
                max_tokens=300,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or "{}"
            verdict = parse_json_object(content)
            write_cache(
                cache_path,
                {
                    "kind": "adversarial_review",
                    "model": args.model,
                    "raw_response": content,
                    "parsed": verdict,
                },
            )
        out = dict(row)
        out["adversarial_verdict"] = verdict.get("verdict", "")
        out["adversarial_reason"] = verdict.get("reason", "")
        return index, out

    out_rows: list[dict | None] = [None] * len(rows)
    reviewed = 0

    def handle_result(result: tuple[int, dict]) -> None:
        nonlocal reviewed
        index, out = result
        out_rows[index] = out
        reviewed += 1
        if args.progress_every and reviewed % args.progress_every == 0:
            print(f"reviewed={reviewed}/{len(rows)}", flush=True)

    if args.workers <= 1:
        for index, row in enumerate(rows):
            handle_result(review_row(index, row))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for result in executor.map(lambda pair: review_row(*pair), enumerate(rows)):
                handle_result(result)

    if reviewed != len(rows):
        raise SystemExit(f"expected {len(rows)} reviewed rows, got {reviewed}")

    finalized_rows = [row for row in out_rows if row is not None]

    fieldnames = list(finalized_rows[0].keys()) if finalized_rows else []
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(finalized_rows)

    print(f"reviewed_rows={len(finalized_rows)}")
    print(output_path)


if __name__ == "__main__":
    main()
