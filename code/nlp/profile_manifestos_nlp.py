#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
ANALYSIS_DIR = ROOT / "analysis"
DOCUMENTS_CSV = ANALYSIS_DIR / "documents.csv"
OUTPUT_DIR = ANALYSIS_DIR / "nlp"
DEFAULT_OUTPUT_CSV = OUTPUT_DIR / "manifesto_nlp_profiles.csv"
DEFAULT_CHUNK_TSV = OUTPUT_DIR / "manifesto_nlp_chunks.tsv"
DEFAULT_SKIPPED_CSV = OUTPUT_DIR / "manifesto_nlp_skipped.csv"


# These patterns are intentionally conservative. The workbook annexes include
# some very broad words such as "plan", "reform", and "risk" that are likely to
# overcount unless they are interpreted in context.
LONG_TERM_PATTERNS = [
    r"\bfuture(?:\s+proof(?:ing)?)?\b",
    r"\blong[\s-]?term\b",
    r"\blonger[\s-]?term\b",
    r"\blong[\s-]?run\b",
    r"\bdecade(?:s)?\b",
    r"\bgeneration(?:s)?\b",
    r"\bintergenerational\b",
    r"\blegacy\b",
    r"\benduring\b",
    r"\bdurable\b",
    r"\blasting\b",
    r"\bpermanent(?:ly)?\b",
    r"\bsustainable\b",
    r"\bstewardship\b",
    r"\bthrift\b",
    r"\bprevention\b",
    r"\bpreventative\b",
    r"\broad\s*map\b",
    r"\bpathway(?:s)?\b",
    r"\bmulti[\s-]?year\b",
    r"\bnational\s+plan\b",
    r"\breconstruction\b",
    r"\boverhaul\b",
    r"\bresilience\b",
    r"\btransition\b",
    r"\btrajectory\b",
    r"\bchildren\b",
    r"\bgrandchildren\b",
    r"\binheritance\b",
    r"\bfoundation(?:s)?\b",
]

SHORT_TERM_PATTERNS = [
    r"\bday\s+one\b",
    r"\bimmediate(?:ly)?\b",
    r"\burgent\b",
    r"\bright\s+now\b",
    r"\bat\s+once\b",
    r"\bstraight\s+away\b",
    r"\bfirst\s+opportunity\b",
    r"\bprompt(?:ly)?\b",
    r"\bspeedily\b",
    r"\bthis\s+year\b",
    r"\bshort[\s-]?term\b",
    r"\bshort[\s-]?run\b",
    r"\btemporary\b",
    r"\binterim\b",
    r"\bone[\s-]?off\b",
    r"\bstop[\s-]?gap\b",
    r"\bstop[\s-]?go\b",
    r"\bcrisis\b",
    r"\bemergency\b",
    r"\bfast\b",
    r"\brapid(?:ly)?\b",
    r"\bquick(?:ly)?\b",
    r"\bnow\b",
]

DEFINITE_COMMITMENT_PATTERNS = [
    r"\bwe\s+will\b",
    r"\bwill\s+deliver\b",
    r"\bwill\s+build\b",
    r"\bwill\s+create\b",
    r"\bwill\s+fund\b",
    r"\bwill\s+legislate\b",
    r"\bwill\s+establish\b",
    r"\bcommit(?:ted|ment)?\s+to\b",
    r"\bguarantee(?:d|s)?\b",
]

ASPIRATIONAL_PATTERNS = [
    r"\baim(?:s|ed|ing)?\s+to\b",
    r"\bseek(?:s|ing)?\s+to\b",
    r"\bwork(?:ing)?\s+towards?\b",
    r"\bwork(?:ing)?\s+to\b",
    r"\baspire(?:s|d|ing)?\s+to\b",
    r"\bambition\b",
    r"\bhope(?:s|d)?\s+to\b",
    r"\bwould\b",
    r"\bcould\b",
    r"\bmay\b",
]

PREVENTION_PATTERNS = [
    r"\bprevent(?:s|ed|ing|ion)?\b",
    r"\bpreventive\b",
    r"\bearly\s+intervention\b",
    r"\broot\s+cause(?:s)?\b",
    r"\bupstream\b",
    r"\bpublic\s+health\b",
    r"\bcrime\s+prevention\b",
]

INVESTMENT_PATTERNS = [
    r"\binvest(?:ment|ing|s)?\b",
    r"\binfrastructure\b",
    r"\bresearch\s+and\s+development\b",
    r"\bR&D\b",
    r"\bscience\b",
    r"\binnovation\b",
    r"\bskills\b",
    r"\btraining\b",
    r"\bretraining\b",
    r"\beducation\b",
    r"\bhousing\b",
    r"\bhome(?:s)?\b",
    r"\bgrid\b",
    r"\btransport\b",
    r"\bcapital\b",
]

RESILIENCE_PATTERNS = [
    r"\bresilien(?:ce|t)\b",
    r"\bsecurity\b",
    r"\bsecure\b",
    r"\bsafeguard(?:s|ed|ing)?\b",
    r"\bprepared(?:ness)?\b",
    r"\bmitigat(?:e|es|ed|ion)\b",
    r"\badapt(?:ation|ive)?\b",
    r"\bshock(?:s)?\b",
    r"\brisk(?:s)?\b",
    r"\bstability\b",
]

RELIEF_PATTERNS = [
    r"\bcut\s+tax(?:es)?\b",
    r"\bfreeze\b",
    r"\brelief\b",
    r"\bboost\b",
    r"\bextra\b",
    r"\bmore\b",
    r"\bappointments\b",
    r"\bpolice\b",
    r"\bstaff\b",
    r"\bpayments?\b",
    r"\bbills?\b",
    r"\bcost[\s-]?of[\s-]?living\b",
    r"\bwaiting\s+times?\b",
]

INTERGENERATIONAL_PATTERNS = [
    r"\bchildren\b",
    r"\byoung\s+people\b",
    r"\bfuture\s+generations?\b",
    r"\bgrandchildren\b",
    r"\blegacy\b",
    r"\binheritance\b",
]

INSTITUTIONAL_PATTERNS = [
    r"\bindependent\s+commission\b",
    r"\bindependent\s+body\b",
    r"\bstatutory\b",
    r"\bbinding\b",
    r"\bnational\s+plan\b",
    r"\btarget(?:s)?\b",
    r"\bmilestone(?:s)?\b",
    r"\breview\s+mechanism(?:s)?\b",
    r"\bsunset\s+clause(?:s)?\b",
    r"\bframework(?:s)?\b",
    r"\bcommission(?:s)?\b",
    r"\bpathway(?:s)?\b",
    r"\broad\s*map\b",
]

FUTURE_TENSE_PATTERNS = [
    r"\bwe\s+will\b",
    r"\bwill\b",
    r"\bgoing\s+to\b",
]

PRESENT_URGENCY_PATTERNS = [
    r"\bnow\b",
    r"\btoday\b",
    r"\bimmediate(?:ly)?\b",
    r"\bday\s+one\b",
]


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


COMPILED_PATTERNS = {
    "long_term": compile_patterns(LONG_TERM_PATTERNS),
    "short_term": compile_patterns(SHORT_TERM_PATTERNS),
    "definite_commitment": compile_patterns(DEFINITE_COMMITMENT_PATTERNS),
    "aspirational": compile_patterns(ASPIRATIONAL_PATTERNS),
    "prevention": compile_patterns(PREVENTION_PATTERNS),
    "investment": compile_patterns(INVESTMENT_PATTERNS),
    "resilience": compile_patterns(RESILIENCE_PATTERNS),
    "relief": compile_patterns(RELIEF_PATTERNS),
    "intergenerational": compile_patterns(INTERGENERATIONAL_PATTERNS),
    "institutional": compile_patterns(INSTITUTIONAL_PATTERNS),
    "future_tense": compile_patterns(FUTURE_TENSE_PATTERNS),
    "present_urgency": compile_patterns(PRESENT_URGENCY_PATTERNS),
}

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
WHITESPACE_RE = re.compile(r"\s+")
PAGE_NUMBER_RE = re.compile(r"^\d+$")
DOT_LEADER_RE = re.compile(r"\.{4,}")
WAYBACK_WRAPPER_MARKERS = (
    "wayback machine",
    "ask the publishers to restore access to 500,000+ books",
    "hamburger icon",
)


@dataclass
class ChunkResult:
    chunk_index: int
    text: str
    word_count: int
    is_salient: bool
    counts: dict[str, int]


def snippet(text: str, limit: int = 220) -> str:
    clean = WHITESPACE_RE.sub(" ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def normalize_chunk_text(text: str) -> str:
    text = text.replace("\x0c", "\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = " ".join(lines)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def detect_text_quality_flag(text: str) -> str:
    lowered = WHITESPACE_RE.sub(" ", text[:4000]).strip().lower()
    if all(marker in lowered for marker in WAYBACK_WRAPPER_MARKERS):
        return "archive_wrapper_page"
    return ""


def split_into_chunks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n\n")
    raw_chunks = re.split(r"\n\s*\n+", text)
    chunks: list[str] = []
    for raw in raw_chunks:
        chunk = normalize_chunk_text(raw)
        if not chunk:
            continue
        if PAGE_NUMBER_RE.fullmatch(chunk):
            continue
        if chunk.lower() == "contents":
            continue
        if DOT_LEADER_RE.search(chunk):
            continue
        words = chunk.split()
        if len(words) <= 8 and "manifesto" in chunk.lower() and YEAR_RE.search(chunk):
            continue
        chunks.append(chunk)
    return chunks


def is_salient_chunk(text: str) -> bool:
    word_count = len(text.split())
    if text.startswith("§"):
        return True
    if re.match(r"^\d+\.\s", text):
        return True
    if word_count <= 12 and text.count(".") <= 1 and text.count(",") <= 1:
        return True
    if word_count <= 10 and text == text.title():
        return True
    return False


def count_matches(text: str, patterns: list[re.Pattern[str]]) -> int:
    return sum(len(pattern.findall(text)) for pattern in patterns)


def analyze_chunk(text: str, chunk_index: int) -> ChunkResult:
    word_count = len(text.split())
    salient = is_salient_chunk(text)
    counts = {name: count_matches(text, patterns) for name, patterns in COMPILED_PATTERNS.items()}
    return ChunkResult(
        chunk_index=chunk_index,
        text=text,
        word_count=word_count,
        is_salient=salient,
        counts=counts,
    )


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def balance_score(positive: float, negative: float) -> float:
    total = positive + negative
    if total <= 0:
        return 50.0
    return round(100.0 * positive / total, 1)


def density_per_1000(count: float, word_count: int) -> float:
    if word_count <= 0:
        return 0.0
    return round(count * 1000.0 / word_count, 3)


def chunk_signal(
    chunk: ChunkResult,
    positive_keys: list[str],
    negative_keys: list[str] | None = None,
) -> float:
    negative_keys = negative_keys or []
    positive = sum(chunk.counts.get(key, 0) for key in positive_keys)
    negative = sum(chunk.counts.get(key, 0) for key in negative_keys)
    return positive - negative


def select_example(
    chunks: list[ChunkResult],
    positive_keys: list[str],
    negative_keys: list[str] | None = None,
    mode: str = "positive",
) -> str:
    best_chunk: ChunkResult | None = None
    best_score: float | None = None
    for chunk in chunks:
        score = chunk_signal(chunk, positive_keys, negative_keys)
        if mode == "positive":
            candidate_ok = score > 0
            comparable = score
        else:
            candidate_ok = score < 0
            comparable = -score
        if not candidate_ok:
            continue
        if best_score is None or comparable > best_score:
            best_score = comparable
            best_chunk = chunk
    if best_chunk is None:
        return ""
    return f"chunk {best_chunk.chunk_index}: {snippet(best_chunk.text)}"


def density_score(count: float, word_count: int, factor: float) -> float:
    if word_count <= 0:
        return 0.0
    return round(min(100.0, factor * count * 1000.0 / word_count), 1)


def aggregate_document(
    row: dict[str, str],
    text: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    chunks = split_into_chunks(text)

    chunk_results = [analyze_chunk(chunk, i) for i, chunk in enumerate(chunks, start=1)]
    word_count = sum(chunk.word_count for chunk in chunk_results)
    salient_chunk_count = sum(1 for chunk in chunk_results if chunk.is_salient)

    totals: dict[str, float] = {}
    for chunk in chunk_results:
        for key, value in chunk.counts.items():
            totals[key] = totals.get(key, 0.0) + value

    # Balance scores: 100 * positive / (positive + negative)
    temporal_score = balance_score(totals.get("long_term", 0.0), totals.get("short_term", 0.0))
    commitment_score = balance_score(totals.get("definite_commitment", 0.0), totals.get("aspirational", 0.0))
    investment_score = balance_score(totals.get("investment", 0.0), totals.get("relief", 0.0))

    # Density scores: min(100, factor * hits_per_1000_words)
    resilience_score = density_score(
        totals.get("prevention", 0.0) + totals.get("resilience", 0.0), word_count, 20,
    )
    intergenerational_score = density_score(totals.get("intergenerational", 0.0), word_count, 30)
    institutional_score = density_score(totals.get("institutional", 0.0), word_count, 40)

    headline_score = round(
        (temporal_score + commitment_score + investment_score
         + resilience_score + intergenerational_score + institutional_score) / 6.0,
        1,
    )

    profile = {
        "doc_id": row["doc_id"],
        "party_slug": row["party_slug"],
        "party_name": row["party_name"],
        "year": row["year"],
        "title": row["title"],
        "text_path": row["text_path"],
        "word_count": word_count,
        "chunk_count": len(chunk_results),
        "salient_chunk_count": salient_chunk_count,
        "salient_chunk_share": round(safe_ratio(salient_chunk_count, len(chunk_results)), 3),
        "long_term_hits": int(totals.get("long_term", 0.0)),
        "short_term_hits": int(totals.get("short_term", 0.0)),
        "definite_commitment_hits": int(totals.get("definite_commitment", 0.0)),
        "aspirational_hits": int(totals.get("aspirational", 0.0)),
        "future_tense_hits": int(totals.get("future_tense", 0.0)),
        "present_urgency_hits": int(totals.get("present_urgency", 0.0)),
        "prevention_hits": int(totals.get("prevention", 0.0)),
        "investment_hits": int(totals.get("investment", 0.0)),
        "resilience_hits": int(totals.get("resilience", 0.0)),
        "relief_hits": int(totals.get("relief", 0.0)),
        "intergenerational_hits": int(totals.get("intergenerational", 0.0)),
        "institutional_hits": int(totals.get("institutional", 0.0)),
        "temporal_orientation_score": temporal_score,
        "commitment_strength_score": commitment_score,
        "investment_stewardship_score": investment_score,
        "risk_resilience_score": resilience_score,
        "intergenerational_reference_score": intergenerational_score,
        "institutional_commitment_score": institutional_score,
        "headline_long_termism_score": headline_score,
        "temporal_positive_example": select_example(
            chunk_results,
            ["long_term"],
            negative_keys=["short_term"],
            mode="positive",
        ),
        "temporal_negative_example": select_example(
            chunk_results,
            ["long_term"],
            negative_keys=["short_term"],
            mode="negative",
        ),
        "commitment_positive_example": select_example(
            chunk_results,
            ["definite_commitment"],
            negative_keys=["aspirational"],
            mode="positive",
        ),
        "commitment_negative_example": select_example(
            chunk_results,
            ["definite_commitment"],
            negative_keys=["aspirational"],
            mode="negative",
        ),
        "investment_positive_example": select_example(
            chunk_results,
            ["investment"],
            negative_keys=["relief"],
            mode="positive",
        ),
        "investment_negative_example": select_example(
            chunk_results,
            ["investment"],
            negative_keys=["relief"],
            mode="negative",
        ),
        "resilience_positive_example": select_example(
            chunk_results,
            ["prevention", "resilience"],
            mode="positive",
        ),
        "resilience_negative_example": select_example(
            chunk_results,
            ["prevention", "resilience"],
            mode="negative",
        ),
        "institutional_positive_example": select_example(
            chunk_results,
            ["institutional"],
            mode="positive",
        ),
    }

    chunk_rows: list[dict[str, object]] = []
    for chunk in chunk_results:
        chunk_rows.append(
            {
                "doc_id": row["doc_id"],
                "party_slug": row["party_slug"],
                "year": row["year"],
                "chunk_index": chunk.chunk_index,
                "word_count": chunk.word_count,
                "is_salient": int(chunk.is_salient),
                "long_term_hits": chunk.counts.get("long_term", 0),
                "short_term_hits": chunk.counts.get("short_term", 0),
                "definite_commitment_hits": chunk.counts.get("definite_commitment", 0),
                "aspirational_hits": chunk.counts.get("aspirational", 0),
                "prevention_hits": chunk.counts.get("prevention", 0),
                "investment_hits": chunk.counts.get("investment", 0),
                "resilience_hits": chunk.counts.get("resilience", 0),
                "relief_hits": chunk.counts.get("relief", 0),
                "intergenerational_hits": chunk.counts.get("intergenerational", 0),
                "institutional_hits": chunk.counts.get("institutional", 0),
                "text": chunk.text,
            }
        )

    return profile, chunk_rows


def build_skipped_row(row: dict[str, str], text: str, text_quality_flag: str) -> dict[str, object]:
    return {
        "doc_id": row["doc_id"],
        "party_slug": row["party_slug"],
        "party_name": row["party_name"],
        "year": row["year"],
        "title": row["title"],
        "text_path": row["text_path"],
        "word_count": len(text.split()),
        "text_quality_flag": text_quality_flag,
        "snippet": snippet(text, limit=180),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile manifesto full text with document-level NLP heuristics."
    )
    parser.add_argument(
        "--documents-csv",
        type=Path,
        default=DOCUMENTS_CSV,
        help="Analysis documents table built by build_analysis.py",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="Where to write manifesto-level profile rows",
    )
    parser.add_argument(
        "--chunk-output",
        type=Path,
        default=DEFAULT_CHUNK_TSV,
        help="Where to write chunk-level diagnostics TSV",
    )
    parser.add_argument(
        "--skipped-output",
        type=Path,
        default=DEFAULT_SKIPPED_CSV,
        help="Where to write skipped-document diagnostics CSV",
    )
    parser.add_argument("--party", help="Optional party_slug filter")
    parser.add_argument("--year", help="Optional year filter")
    parser.add_argument("--limit", type=int, help="Optional row limit after filtering")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv.field_size_limit(sys.maxsize)
    with args.documents_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    filtered = rows
    if args.party:
        filtered = [row for row in filtered if row["party_slug"] == args.party]
    if args.year:
        filtered = [row for row in filtered if row["year"] == args.year]
    if args.limit is not None:
        filtered = filtered[: args.limit]

    if not filtered:
        raise SystemExit("no documents matched the requested filters")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.chunk_output.parent.mkdir(parents=True, exist_ok=True)
    args.skipped_output.parent.mkdir(parents=True, exist_ok=True)

    text_root = ROOT.parent
    profile_rows: list[dict[str, object]] = []
    chunk_rows: list[dict[str, object]] = []
    skipped_rows: list[dict[str, object]] = []

    for row in filtered:
        text_path = text_root / row["text_path"]
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        text_quality_flag = detect_text_quality_flag(text)
        if text_quality_flag:
            skipped_rows.append(build_skipped_row(row, text, text_quality_flag))
            continue
        profile, chunks = aggregate_document(row, text=text)
        profile_rows.append(profile)
        chunk_rows.extend(chunks)

    if not profile_rows:
        raise SystemExit("no valid documents remained after skipping invalid text")

    with args.output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(profile_rows[0].keys()))
        writer.writeheader()
        writer.writerows(profile_rows)

    with args.chunk_output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(chunk_rows[0].keys()), delimiter="\t")
        writer.writeheader()
        writer.writerows(chunk_rows)

    with args.skipped_output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(skipped_rows[0].keys()) if skipped_rows else [
            "doc_id",
            "party_slug",
            "party_name",
            "year",
            "title",
            "text_path",
            "word_count",
            "text_quality_flag",
            "snippet",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(skipped_rows)

    print(f"profiled {len(profile_rows)} manifestos")
    if skipped_rows:
        print(f"skipped {len(skipped_rows)} manifestos with invalid text")
    print(args.output_csv)
    print(args.chunk_output)
    print(args.skipped_output)


if __name__ == "__main__":
    main()
