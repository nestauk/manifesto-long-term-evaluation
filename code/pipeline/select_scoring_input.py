#!/usr/bin/env python3
import argparse
import csv
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT_PATH = Path(__file__).resolve().parent / "preflight_commitments.py"


def load_preflight_module():
    spec = importlib.util.spec_from_file_location("preflight_module", PREFLIGHT_PATH)
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


def write_rows(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--doc-status", nargs="*", default=["ready"])
    parser.add_argument("--high-trust-only", action="store_true")
    parser.add_argument("--risk-band-keep", nargs="*", default=[])
    args = parser.parse_args()

    preflight = load_preflight_module()

    rows, fieldnames = read_rows(Path(args.input))
    summary_rows, _ = read_rows(Path(args.summary_csv))
    allowed_statuses = {str(value).strip() for value in args.doc_status if str(value).strip()}
    allowed_bands = {str(value).strip().lower() for value in args.risk_band_keep if str(value).strip()}

    summary_by_doc = {row["doc_id"]: row for row in summary_rows}
    selected = []
    output_fields = list(fieldnames)
    for extra in ["doc_status", "doc_status_reason", "audit_risk_band", "audit_reason", "selection_rule"]:
        if extra not in output_fields:
            output_fields.append(extra)

    for row in rows:
        summary = summary_by_doc.get(row.get("doc_id", ""))
        if summary is None:
            continue
        doc_status = summary.get("doc_status", "")
        if allowed_statuses and doc_status not in allowed_statuses:
            continue
        if not preflight.eligible_for_scoring(row):
            continue
        if args.high_trust_only and not preflight.high_trust_proxy(row):
            continue
        band, reason = preflight.risk_band(row)
        if allowed_bands and band not in allowed_bands:
            continue
        out = dict(row)
        out["doc_status"] = doc_status
        out["doc_status_reason"] = summary.get("doc_status_reason", "")
        out["audit_risk_band"] = band
        out["audit_reason"] = reason
        if args.high_trust_only:
            out["selection_rule"] = "high_trust_proxy"
        elif allowed_bands:
            out["selection_rule"] = "risk_band:" + ",".join(sorted(allowed_bands))
        else:
            out["selection_rule"] = "eligible_for_scoring"
        selected.append(out)

    selected.sort(key=lambda row: row.get("commitment_id", ""))
    write_rows(Path(args.output), selected, output_fields)

    print(f"input_rows={len(rows)}")
    print(f"selected_rows={len(selected)}")
    print(f"selected_docs={len({row['doc_id'] for row in selected})}")
    print(Path(args.output))


if __name__ == "__main__":
    main()
