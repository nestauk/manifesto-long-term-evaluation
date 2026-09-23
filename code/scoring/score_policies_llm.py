#!/usr/bin/env python3
"""Score policy commitments against the policy typology with an LLM.

The published data/commitments.csv was produced with --prompt-version v11
and --model gpt-5-mini (temperature 0). Needs OPENAI_API_KEY in the
environment or in a .env file at the repo root.

Usage:
    uv run code/scoring/score_policies_llm.py --input data/scoring_input.csv --output-prefix <name>

The input CSV needs commitment_id, party_name, year, title, commitment_text,
supporting_quote and policy_context columns. Outputs go to outputs/scores/.
"""

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
from datetime import datetime, timezone
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

ROOT = Path(__file__).resolve().parents[2]
SCORES_DIR = ROOT / "outputs" / "scores"
ENV_PATH = ROOT / ".env"
CACHE_DIR = ROOT / ".cache" / "llm" / "score_policies"
PROMPTS_DIR = ROOT / "methods" / "prompts" / "discovery"
DEFAULT_PROMPT_VERSION = "v11"
DEFAULT_REVIEW_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_TRUST_HIGH_CONFIDENCE = 0.75
DEFAULT_TRUST_MEDIUM_CONFIDENCE = 0.6

JSON_REPAIR_SYSTEM_PROMPT = """You repair malformed JSON.

Return only valid JSON.
Do not add commentary.
Preserve the original structure and content as closely as possible.
"""

USER_TEMPLATE = """Policy commitment to score:

Document metadata:
- party: {party_name}
- year: {year}
- title: {title}
- commitment_id: {commitment_id}

Commitment text:
\"\"\"
{commitment_text}
\"\"\"

Supporting quote:
\"\"\"
{supporting_quote}
\"\"\"

Policy context:
\"\"\"
{policy_context}
\"\"\"
"""


def load_system_prompt(version: str) -> str:
    prompt_path = PROMPTS_DIR / f"system_prompt_{version}.txt"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise SystemExit(f"missing Discovery prompt version: {prompt_path}") from exc


SCORE_FIELDS = [
    "prevention",
    "tangible_investment",
    "intangible_investment",
    "risk_resilience",
    "current_consumption",
    "constitutional_change",
]
TEXT_FIELDS = ["commitment_text", "supporting_quote", "policy_context"]

PHYSICAL_ASSET_TERMS = {
    "asset",
    "assets",
    "building",
    "buildings",
    "premises",
    "facility",
    "facilities",
    "infrastructure",
    "equipment",
    "grid",
    "plant",
    "rail",
    "road",
    "roads",
    "bridge",
    "bridges",
    "hospital",
    "hospitals",
    "school",
    "schools",
    "housing",
    "homes",
    "house",
    "houses",
    "factory",
    "factories",
    "port",
    "ports",
    "site",
    "sites",
    "venue",
    "venues",
    "power",
    "scanner",
    "scanners",
    "project",
    "projects",
    "capital",
}

HIGH_TANGIBLE_PLANNING_TERMS = {
    "plan",
    "plans",
    "planning",
    "prioritise",
    "prioritize",
    "prioritisation",
    "prioritization",
    "review",
    "reviews",
    "feasibility",
    "strategy",
    "strategies",
}

HIGH_TANGIBLE_GENERIC_SPEND_TERMS = {
    "would require",
    "require additional annual expenditure",
    "additional annual expenditure",
    "annual expenditure",
    "funding to develop plans",
    "develop plans",
    "cost estimate",
    "cost estimates",
    "estimate that",
}

HIGH_TANGIBLE_CAPITAL_WORK_TERMS = {
    "build",
    "construct",
    "construction",
    "upgrade",
    "upgrades",
    "repair",
    "repairs",
    "install",
    "installation",
    "refurbish",
    "refurbishment",
    "rebuild",
    "replacement",
    "replace",
    "roll out",
    "rollout",
    "deploy",
    "deployment",
    "open",
}


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


def parse_json_object(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output did not contain a JSON object")
    return json.loads(text[start : end + 1])


def normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def normalized_label(value: str) -> str:
    return str(value or "").strip().lower()


def contains_term(text: str, term: str) -> bool:
    return re.search(r"\b" + re.escape(term) + r"\b", text) is not None


def contains_any_term(text: str, terms: set[str]) -> bool:
    return any(contains_term(text, term) for term in terms)


def should_keep_verdict(row: dict, field: str, keep: set[str], drop: set[str]) -> bool:
    verdict = normalized_label(row.get(field, ""))
    if not verdict:
        return True
    if drop and verdict in drop:
        return False
    if keep:
        return verdict in keep
    return True


def has_text_artifact(row: dict) -> bool:
    return any("\x00" in str(row.get(field, "")) for field in TEXT_FIELDS)


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


def completion_token_kwargs(model: str, max_output_tokens: int) -> dict:
    if model.startswith("gpt-5"):
        return {"max_completion_tokens": max_output_tokens}
    return {"max_tokens": max_output_tokens}


def completion_request_kwargs(model: str, temperature: float, max_output_tokens: int) -> dict:
    kwargs = completion_token_kwargs(model, max_output_tokens)
    if not model.startswith("gpt-5"):
        kwargs["temperature"] = temperature
    return kwargs


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
    response_format: dict,
    max_api_retries: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
    **kwargs,
):
    last_exc = None
    for attempt in range(1, max_api_retries + 2):
        try:
            return client.chat.completions.create(
                model=model,
                response_format=response_format,
                **kwargs,
            )
        except (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError) as exc:
            last_exc = exc
            if attempt > max_api_retries:
                break
            delay = sleep_with_backoff(attempt, backoff_base_seconds, backoff_max_seconds)
            print(
                f"retrying after {exc.__class__.__name__} in {delay}s (attempt {attempt}/{max_api_retries})",
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
            response_format={"type": "json_object"},
            max_api_retries=max_api_retries,
            backoff_base_seconds=backoff_base_seconds,
            backoff_max_seconds=backoff_max_seconds,
            **completion_request_kwargs(model, 0, max_output_tokens),
            messages=[
                {"role": "system", "content": JSON_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": "Repair this into valid JSON only:\n\n" + broken_text},
            ],
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
                f"retrying malformed JSON repair output in {delay}s (attempt {repair_attempt}/{repair_attempts})",
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


def build_user_prompt(row: dict) -> str:
    return USER_TEMPLATE.format(
        party_name=row.get("party_name", ""),
        year=row.get("year", ""),
        title=row.get("title", ""),
        commitment_id=row.get("commitment_id", ""),
        commitment_text=(row.get("commitment_text") or "").strip(),
        supporting_quote=(row.get("supporting_quote") or "").strip(),
        policy_context=(row.get("policy_context") or "").strip(),
    )


def score_commitment(
    client: OpenAI,
    model: str,
    system_prompt: str,
    row: dict,
    temperature: float,
    max_output_tokens: int,
    max_api_retries: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> dict:
    user_prompt = build_user_prompt(row)
    key = cache_key(
        "score_commitment",
        model,
        str(temperature),
        str(max_output_tokens),
        system_prompt,
        user_prompt,
    )
    cache_path = CACHE_DIR / f"{key}.json"
    cached = read_cache(cache_path)
    if cached is not None:
        return cached["parsed"]

    retry_note = ""
    last_error: ValueError | None = None
    last_content = "{}"

    for _attempt in range(3):
        messages = [{"role": "system", "content": system_prompt}]
        if retry_note:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Your previous output failed validation. "
                        "Re-score the same commitment and return valid JSON only. "
                        f"Validation issue: {retry_note}"
                    ),
                }
            )
        messages.append({"role": "user", "content": user_prompt})

        response = create_chat_completion_with_retries(
            client,
            model=model,
            response_format={"type": "json_object"},
            max_api_retries=max_api_retries,
            backoff_base_seconds=backoff_base_seconds,
            backoff_max_seconds=backoff_max_seconds,
            **completion_request_kwargs(model, temperature, max_output_tokens),
            messages=messages,
        )
        content = response.choices[0].message.content or "{}"
        last_content = content
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

        try:
            validate_response(parsed, row["commitment_id"], row=row)
        except ValueError as exc:
            last_error = exc
            retry_note = str(exc)
            continue

        write_cache(
            cache_path,
            {
                "kind": "score_commitment",
                "model": model,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "commitment_id": row["commitment_id"],
                "raw_response": content,
                "parsed": parsed,
            },
        )
        return parsed

    if last_error is not None:
        raise last_error
    raise ValueError(f"score_commitment failed without a parsed response: {last_content[:200]}")


def validate_response(obj: dict, commitment_id: str, row: dict | None = None) -> None:
    if not obj.get("commitment_id"):
        obj["commitment_id"] = commitment_id
    if obj.get("commitment_id") != commitment_id:
        raise ValueError(f"commitment_id mismatch: expected {commitment_id!r}, got {obj.get('commitment_id')!r}")

    scores = obj.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("scores must be an object")
    for field in SCORE_FIELDS:
        value = scores.get(field)
        if not isinstance(value, int) or not 0 <= value <= 4:
            raise ValueError(f"invalid score for {field}: {value!r}")

    rationales = obj.get("rationales")
    if not isinstance(rationales, dict):
        raise ValueError("rationales must be an object")
    for field in SCORE_FIELDS:
        value = rationales.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing rationale for {field}")

    tangible_score = scores.get("tangible_investment", 0)
    tangible_rationale = (rationales.get("tangible_investment") or "").lower()
    if tangible_score > 0 and not any(term in tangible_rationale for term in PHYSICAL_ASSET_TERMS):
        raise ValueError(
            "tangible_investment rationale must identify physical assets, "
            "infrastructure, equipment, or physical capital"
        )
    if row is not None and tangible_score >= 3:
        commitment_text = normalize_text(row.get("commitment_text", ""))
        has_explicit_asset = contains_any_term(commitment_text, PHYSICAL_ASSET_TERMS)
        has_capital_work = contains_any_term(commitment_text, HIGH_TANGIBLE_CAPITAL_WORK_TERMS)
        has_planning = contains_any_term(commitment_text, HIGH_TANGIBLE_PLANNING_TERMS)
        has_generic_spend = contains_any_term(commitment_text, HIGH_TANGIBLE_GENERIC_SPEND_TERMS)
        if has_planning and not has_capital_work:
            raise ValueError(
                "tangible_investment >=3 cannot rely mainly on planning, prioritisation, "
                "review, or similar pre-build language"
            )
        if has_generic_spend and not has_explicit_asset and not has_capital_work:
            raise ValueError(
                "tangible_investment >=3 cannot rely mainly on generic expenditure or estimated funding language"
            )
        if not has_explicit_asset and not has_capital_work:
            raise ValueError(
                "tangible_investment >=3 requires explicit physical asset or capital-work language in commitment_text"
            )

    confidence = obj.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError(f"invalid confidence: {confidence!r}")

    ambiguous = obj.get("ambiguous")
    if not isinstance(ambiguous, bool):
        raise ValueError(f"ambiguous must be boolean: {ambiguous!r}")

    ambiguity_note = obj.get("ambiguity_note")
    if not isinstance(ambiguity_note, str):
        raise ValueError("ambiguity_note must be a string")
    if ambiguous and not ambiguity_note.strip():
        raise ValueError("ambiguity_note required when ambiguous is true")


def should_score(row: dict, only_valid: bool) -> bool:
    text = (row.get("commitment_text") or "").strip()
    if not text:
        return False
    if has_text_artifact(row):
        return False
    if not only_valid:
        return True

    status = (row.get("validation_status") or "").strip().lower()
    if not status:
        return True
    return status in {
        "approved",
        "keep",
        "valid",
        "reviewed",
        "exact_quote_match",
        "normalized_quote_match",
    }


def should_keep_semantic(row: dict, semantic_keep: set[str], semantic_drop: set[str]) -> bool:
    verdict = (row.get("semantic_verdict") or "").strip().lower()
    if semantic_drop and verdict in semantic_drop:
        return False
    if semantic_keep:
        return verdict in semantic_keep
    return True


def classify_trust(row: dict, confidence: float, ambiguous: bool) -> tuple[str, str]:
    reasons = []
    status = normalized_label(row.get("validation_status", ""))
    review_priority = normalized_label(row.get("review_priority", ""))
    screen_verdict = normalized_label(row.get("screen_verdict", ""))
    global_duplicate_verdict = normalized_label(row.get("global_duplicate_verdict", ""))

    if screen_verdict in {"review", "drop"}:
        reasons.append(f"screen_{screen_verdict}")
    if global_duplicate_verdict in {"review", "drop_duplicate"}:
        reasons.append(f"global_duplicate_{global_duplicate_verdict}")
    if status == "needs_review":
        reasons.append("validation_needs_review")
    if review_priority == "high":
        reasons.append("heuristic_high_priority")
    if ambiguous:
        reasons.append("ambiguous")
    if confidence < DEFAULT_TRUST_MEDIUM_CONFIDENCE:
        reasons.append("confidence_below_0.6")

    if reasons:
        return "low", ";".join(reasons)

    medium_reasons = []
    if status == "normalized_quote_match":
        medium_reasons.append("normalized_quote_match")
    elif status and status != "exact_quote_match":
        medium_reasons.append(status)
    if confidence < DEFAULT_TRUST_HIGH_CONFIDENCE:
        medium_reasons.append("confidence_below_0.75")

    if medium_reasons:
        return "medium", ";".join(medium_reasons)

    return "high", "exact_quote_match;confidence_ge_0.75"


def apply_review_reasons(rows: list[dict], confidence_threshold: float) -> list[dict]:
    updated = []
    for row in rows:
        out = dict(row)
        confidence = float(out.get("confidence", 0) or 0)
        ambiguous = normalized_label(out.get("ambiguous", "")) == "true"
        trust_tier = normalized_label(out.get("trust_tier", ""))
        reasons = []
        if confidence < confidence_threshold:
            reasons.append("low_confidence")
        if ambiguous:
            reasons.append("ambiguous")
        if trust_tier == "low":
            reasons.append("low_trust")
        out["review_reason"] = ",".join(reasons)
        updated.append(out)
    return updated


def refresh_flattened_row(flattened: dict, input_row: dict | None) -> dict:
    out = dict(flattened)
    if input_row is None:
        out.setdefault("screen_verdict", "")
        out.setdefault("screen_reason", "")
        out.setdefault("global_duplicate_verdict", "")
        out.setdefault("global_duplicate_group", "")
        out.setdefault("global_duplicate_of", "")
        out.setdefault("global_duplicate_reason", "")
        out["trust_tier"] = "low"
        out["trust_reason"] = "missing_input_row"
        return out

    source_row = input_row
    confidence = float(out.get("confidence", 0) or 0)
    ambiguous = normalized_label(out.get("ambiguous", "")) == "true"
    trust_tier, trust_reason = classify_trust(source_row, confidence, ambiguous)
    out["screen_verdict"] = source_row.get("screen_verdict", out.get("screen_verdict", ""))
    out["screen_reason"] = source_row.get("screen_reason", out.get("screen_reason", ""))
    out["global_duplicate_verdict"] = source_row.get(
        "global_duplicate_verdict", out.get("global_duplicate_verdict", "")
    )
    out["global_duplicate_group"] = source_row.get("global_duplicate_group", out.get("global_duplicate_group", ""))
    out["global_duplicate_of"] = source_row.get("global_duplicate_of", out.get("global_duplicate_of", ""))
    out["global_duplicate_reason"] = source_row.get("global_duplicate_reason", out.get("global_duplicate_reason", ""))
    out["trust_tier"] = trust_tier
    out["trust_reason"] = trust_reason
    return out


def load_existing_ids(path: Path) -> set[str]:
    scored = set()
    if not path.exists():
        return scored
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            commitment_id = record.get("commitment_id")
            result = record.get("result")
            if not isinstance(commitment_id, str) or not commitment_id or not isinstance(result, dict):
                continue
            try:
                validate_response(result, commitment_id)
            except ValueError:
                continue
            scored.add(commitment_id)
    return scored


def backfill_flattened_rows_from_jsonl(
    path: Path,
    input_rows_by_id: dict[str, dict],
    existing_flattened: list[dict],
    default_model: str,
    default_prompt_version: str,
) -> list[dict]:
    by_id = {}
    for row in existing_flattened:
        commitment_id = row.get("commitment_id", "")
        if not commitment_id or commitment_id not in input_rows_by_id:
            continue
        by_id[commitment_id] = refresh_flattened_row(row, input_rows_by_id.get(commitment_id))
    if not path.exists():
        return list(by_id.values())

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            commitment_id = record.get("commitment_id")
            result = record.get("result")
            if (
                not isinstance(commitment_id, str)
                or not commitment_id
                or commitment_id in by_id
                or commitment_id not in input_rows_by_id
                or not isinstance(result, dict)
            ):
                continue

            try:
                validate_response(result, commitment_id)
            except ValueError:
                continue

            by_id[commitment_id] = flatten_result(
                input_rows_by_id[commitment_id],
                result,
                str(record.get("model") or default_model),
                str(record.get("prompt_version") or default_prompt_version),
            )

    return list(by_id.values())


def flatten_result(row: dict, result: dict, model: str, prompt_version: str) -> dict:
    trust_tier, trust_reason = classify_trust(row, float(result["confidence"]), bool(result["ambiguous"]))
    flattened = {
        "commitment_id": row.get("commitment_id", ""),
        "doc_id": row.get("doc_id", ""),
        "local_path": row.get("local_path", ""),
        "party_slug": row.get("party_slug", ""),
        "party_name": row.get("party_name", ""),
        "year": row.get("year", ""),
        "title": row.get("title", ""),
        "chunk_id": row.get("chunk_id", ""),
        "chunk_index": row.get("chunk_index", ""),
        "commitment_text": row.get("commitment_text", ""),
        "supporting_quote": row.get("supporting_quote", ""),
        "validation_status": row.get("validation_status", ""),
        "review_priority": row.get("review_priority", ""),
        "screen_verdict": row.get("screen_verdict", ""),
        "screen_reason": row.get("screen_reason", ""),
        "global_duplicate_verdict": row.get("global_duplicate_verdict", ""),
        "global_duplicate_group": row.get("global_duplicate_group", ""),
        "global_duplicate_of": row.get("global_duplicate_of", ""),
        "global_duplicate_reason": row.get("global_duplicate_reason", ""),
        "model": model,
        "prompt_version": prompt_version,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "confidence": float(result["confidence"]),
        "ambiguous": result["ambiguous"],
        "ambiguity_note": result.get("ambiguity_note", ""),
        "trust_tier": trust_tier,
        "trust_reason": trust_reason,
        "review_reason": "",
    }
    for field in SCORE_FIELDS:
        flattened[field] = result["scores"][field]
    for field in SCORE_FIELDS:
        flattened[f"{field}_rationale"] = result["rationales"][field].strip()
    return flattened


def csv_fieldnames() -> list[str]:
    return [
        "commitment_id",
        "doc_id",
        "local_path",
        "party_slug",
        "party_name",
        "year",
        "title",
        "chunk_id",
        "chunk_index",
        "commitment_text",
        "supporting_quote",
        "validation_status",
        "review_priority",
        "screen_verdict",
        "screen_reason",
        "global_duplicate_verdict",
        "global_duplicate_group",
        "global_duplicate_of",
        "global_duplicate_reason",
        "prompt_version",
        *SCORE_FIELDS,
        "confidence",
        "ambiguous",
        "ambiguity_note",
        "trust_tier",
        "trust_reason",
        "review_reason",
        *(f"{field}_rationale" for field in SCORE_FIELDS),
        "model",
        "scored_at",
    ]


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fieldnames())
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-prefix")
    parser.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-output-tokens", type=int, default=4000)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--max-api-retries", type=int, default=6)
    parser.add_argument("--backoff-base-seconds", type=float, default=1.0)
    parser.add_argument("--backoff-max-seconds", type=float, default=30.0)
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_REVIEW_CONFIDENCE_THRESHOLD)
    parser.add_argument("--only-valid", action="store_true")
    parser.add_argument(
        "--screen-keep",
        nargs="*",
        default=["keep"],
        help="Keep only these screen_verdict values when the column is present.",
    )
    parser.add_argument(
        "--screen-drop",
        nargs="*",
        default=["drop"],
        help="Drop these screen_verdict values when the column is present.",
    )
    parser.add_argument(
        "--global-duplicate-keep",
        nargs="*",
        default=["unique"],
        help="Keep only these global_duplicate_verdict values when the column is present.",
    )
    parser.add_argument(
        "--global-duplicate-drop",
        nargs="*",
        default=["drop_duplicate"],
        help="Drop these global_duplicate_verdict values when the column is present.",
    )
    parser.add_argument(
        "--semantic-keep",
        nargs="*",
        default=[],
        help="Keep only these semantic_verdict values (e.g. standalone child parent).",
    )
    parser.add_argument(
        "--semantic-drop",
        nargs="*",
        default=["drop_duplicate"],
        help="Drop these semantic_verdict values.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.output_prefix:
        args.output_prefix = f"scores-{args.prompt_version}"

    csv.field_size_limit(sys.maxsize)
    system_prompt = load_system_prompt(args.prompt_version)

    input_path = Path(args.input)
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    output_jsonl = SCORES_DIR / f"{args.output_prefix}.jsonl"
    output_csv = SCORES_DIR / f"{args.output_prefix}.csv"
    review_csv = SCORES_DIR / f"{args.output_prefix}-review.csv"

    semantic_keep = {value.strip().lower() for value in args.semantic_keep if value.strip()}
    semantic_drop = {value.strip().lower() for value in args.semantic_drop if value.strip()}
    screen_keep = {normalized_label(value) for value in args.screen_keep if normalized_label(value)}
    screen_drop = {normalized_label(value) for value in args.screen_drop if normalized_label(value)}
    duplicate_keep = {normalized_label(value) for value in args.global_duplicate_keep if normalized_label(value)}
    duplicate_drop = {normalized_label(value) for value in args.global_duplicate_drop if normalized_label(value)}

    with input_path.open(newline="", encoding="utf-8") as f:
        rows = [
            row
            for row in csv.DictReader(f)
            if should_score(row, args.only_valid)
            and should_keep_semantic(row, semantic_keep, semantic_drop)
            and should_keep_verdict(row, "screen_verdict", screen_keep, screen_drop)
            and should_keep_verdict(row, "global_duplicate_verdict", duplicate_keep, duplicate_drop)
        ]

    rows.sort(key=lambda row: row.get("commitment_id", ""))
    if args.max_rows:
        rows = rows[: args.max_rows]
    input_rows_by_id = {row["commitment_id"]: row for row in rows if row.get("commitment_id")}

    if args.dry_run:
        print(f"input={input_path}")
        print(f"rows={len(rows)}")
        print(f"prompt_version={args.prompt_version}")
        print(f"output_jsonl={output_jsonl}")
        print(f"output_csv={output_csv}")
        print(f"review_csv={review_csv}")
        return

    load_dotenv(ENV_PATH)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    client = OpenAI()
    existing_ids = load_existing_ids(output_jsonl)
    flattened_rows: list[dict] = []
    failed_rows = 0

    if output_csv.exists():
        with output_csv.open(newline="", encoding="utf-8") as f:
            flattened_rows.extend(csv.DictReader(f))

    flattened_rows = backfill_flattened_rows_from_jsonl(
        output_jsonl,
        input_rows_by_id,
        flattened_rows,
        args.model,
        args.prompt_version,
    )

    for row in rows:
        commitment_id = row["commitment_id"]
        if commitment_id in existing_ids:
            continue

        print(f"scoring {commitment_id}", flush=True)
        try:
            result = score_commitment(
                client=client,
                model=args.model,
                system_prompt=system_prompt,
                row=row,
                temperature=args.temperature,
                max_output_tokens=args.max_output_tokens,
                max_api_retries=args.max_api_retries,
                backoff_base_seconds=args.backoff_base_seconds,
                backoff_max_seconds=args.backoff_max_seconds,
            )
            record = {
                "commitment_id": commitment_id,
                "model": args.model,
                "prompt_version": args.prompt_version,
                "input_row": {
                    "party_name": row.get("party_name", ""),
                    "year": row.get("year", ""),
                    "title": row.get("title", ""),
                    "commitment_text": row.get("commitment_text", ""),
                    "supporting_quote": row.get("supporting_quote", ""),
                },
                "result": result,
            }
            write_jsonl(output_jsonl, record)
            flattened_rows.append(flatten_result(row, result, args.model, args.prompt_version))
        except Exception as exc:
            failed_rows += 1
            print(f"scoring failed {commitment_id}: {exc}", flush=True)
            write_jsonl(
                output_jsonl,
                {
                    "commitment_id": commitment_id,
                    "model": args.model,
                    "prompt_version": args.prompt_version,
                    "input_row": {
                        "party_name": row.get("party_name", ""),
                        "year": row.get("year", ""),
                        "title": row.get("title", ""),
                        "commitment_text": row.get("commitment_text", ""),
                        "supporting_quote": row.get("supporting_quote", ""),
                    },
                    "result": None,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            )
            continue

        if args.sleep_seconds:
            time.sleep(args.sleep_seconds)

    flattened_rows.sort(key=lambda row: row.get("commitment_id", ""))
    flattened_rows = apply_review_reasons(flattened_rows, args.confidence_threshold)
    write_csv(output_csv, flattened_rows)

    review_rows = []
    for row in flattened_rows:
        if row.get("review_reason"):
            review_rows.append(dict(row))
    write_csv(review_csv, review_rows)

    print(f"wrote raw responses to {output_jsonl}")
    print(f"wrote flattened scores to {output_csv}")
    print(f"wrote review subset to {review_csv}")
    if failed_rows:
        print(f"completed with {failed_rows} scoring failures", flush=True)


if __name__ == "__main__":
    main()
