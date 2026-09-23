#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
ANNOTATE_PATH = SCRIPTS_DIR / "annotate_commitment_review.py"
ADVERSARIAL_PATH = SCRIPTS_DIR / "adversarial_commitment_review.py"
SCREEN_PATH = SCRIPTS_DIR / "screen_commitments.py"
GLOBAL_DEDUP_PATH = SCRIPTS_DIR / "dedupe_commitments_global.py"
CONTEXT_PATH = SCRIPTS_DIR / "add_policy_context.py"
PREFLIGHT_PATH = SCRIPTS_DIR / "preflight_commitments.py"


def run_python(script_path: Path, args: list[str]) -> float:
    start = time.time()
    command = [sys.executable, str(script_path), *args]
    subprocess.run(command, cwd=ROOT, check=True)
    return round(time.time() - start, 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Extraction CSV to postprocess.")
    parser.add_argument("--output-dir", required=True, help="Directory for derived outputs.")
    parser.add_argument("--extract-cap", type=int, required=True)
    parser.add_argument("--audit-sample-size", type=int, default=120)
    parser.add_argument("--audit-max-per-doc", type=int, default=2)
    parser.add_argument("--adversarial-review-all", action="store_true")
    parser.add_argument("--adversarial-model", default="gpt-4.1-mini")
    parser.add_argument("--use-adversarial-screening", action="store_true")
    parser.add_argument("--without-context", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    annotated_csv = output_dir / "commitments-annotated.csv"
    flagged_csv = output_dir / "commitments-flagged.csv"
    adversarial_csv = output_dir / "commitments-adversarial-reviewed.csv"
    screened_csv = output_dir / "commitments-screened.csv"
    screened_keep_csv = output_dir / "commitments-screened-keep.csv"
    screened_review_csv = output_dir / "commitments-screened-review.csv"
    screened_drop_csv = output_dir / "commitments-screened-drop.csv"
    dedup_csv = output_dir / "commitments-screened-global-dedup.csv"
    context_csv = output_dir / "commitments-screened-global-dedup-context.csv"
    summary_csv = output_dir / "preflight-summary.csv"
    audit_csv = output_dir / "preflight-audit.csv"
    chunk_rerun_csv = output_dir / "preflight-chunk-rerun.csv"

    total_start = time.time()

    annotate_seconds = run_python(
        ANNOTATE_PATH,
        [
            str(input_path),
            "--output-csv",
            str(annotated_csv),
            "--flagged-csv",
            str(flagged_csv),
        ],
    )

    adversarial_seconds = 0.0
    reviewed_csv_arg: list[str] = []
    if args.adversarial_review_all:
        adversarial_seconds = run_python(
            ADVERSARIAL_PATH,
            [
                str(annotated_csv),
                "--output-csv",
                str(adversarial_csv),
                "--model",
                args.adversarial_model,
            ],
        )
    if args.use_adversarial_screening:
        if not args.adversarial_review_all:
            raise SystemExit("--use-adversarial-screening requires --adversarial-review-all")
        reviewed_csv_arg = ["--reviewed-csv", str(adversarial_csv)]

    screen_seconds = run_python(
        SCREEN_PATH,
        [
            str(annotated_csv),
            *reviewed_csv_arg,
            "--output-csv",
            str(screened_csv),
            "--keep-csv",
            str(screened_keep_csv),
            "--review-csv",
            str(screened_review_csv),
            "--drop-csv",
            str(screened_drop_csv),
        ],
    )

    dedup_seconds = run_python(
        GLOBAL_DEDUP_PATH,
        [
            str(screened_csv),
            "--output-csv",
            str(dedup_csv),
        ],
    )

    preflight_input = dedup_csv
    context_seconds = 0.0
    if not args.without_context:
        context_seconds = run_python(
            CONTEXT_PATH,
            [
                "--input",
                str(dedup_csv),
                "--output",
                str(context_csv),
            ],
        )
        preflight_input = context_csv

    preflight_args = [
        "--input",
        str(preflight_input),
        "--summary-csv",
        str(summary_csv),
        "--audit-csv",
        str(audit_csv),
        "--chunk-rerun-csv",
        str(chunk_rerun_csv),
        "--audit-sample-size",
        str(args.audit_sample_size),
        "--audit-max-per-doc",
        str(args.audit_max_per_doc),
        "--extract-cap",
        str(args.extract_cap),
    ]
    if args.without_context:
        preflight_args.extend(["--context-nonempty-rate-threshold", "0.0"])
    preflight_seconds = run_python(PREFLIGHT_PATH, preflight_args)

    total_seconds = round(time.time() - total_start, 2)

    print(f"annotate_seconds={annotate_seconds}")
    print(f"adversarial_seconds={adversarial_seconds}")
    print(f"screen_seconds={screen_seconds}")
    print(f"dedup_seconds={dedup_seconds}")
    print(f"context_seconds={context_seconds}")
    print(f"preflight_seconds={preflight_seconds}")
    print(f"total_seconds={total_seconds}")
    print(summary_csv)
    print(audit_csv)
    print(chunk_rerun_csv)


if __name__ == "__main__":
    main()
