# Commitments pipeline (stages 3-9)

These are the scripts that turned `data/documents.csv` into the commitments that were sent to the scorer. They are published as they were used, for transparency. They are not packaged to run from this repo: their default paths point at the working folder they were written in (`analysis/`, `.cache/`, `.env`), and several of them load `extract_pledges_llm.py` or `preflight_commitments.py` from the same folder at runtime.

Stage numbers match [`methods/pipeline.md`](../../methods/pipeline.md).

| Stage | Script | What it does | LLM |
|---|---|---|---|
| 3 | `build_document_shards.py` | Splits `documents.csv` into shards for parallel extraction | |
| 3 | `extract_pledges_llm.py` | Extracts verbatim commitment quotes from each document chunk | Yes |
| 3 | `merge_extraction_shards.py` | Combines the per-shard extraction outputs | |
| 4 | `rerun_saturated_chunks.py` | Re-extracts chunks that hit the per-chunk quote cap, using smaller overlapping sub-chunks, and merges the results with the base extraction | Yes |
| 5-9 | `postprocess_commitments.py` | Runs the next scripts in order on the merged extraction. Its optional adversarial LLM review step was not used for the published data, so that script is not included | |
| 5 | `annotate_commitment_review.py` | Adds heuristic flags and a review priority to each row | |
| 6 | `screen_commitments.py` | Sets a keep or review verdict for each row from the heuristic flags. Rows marked review are not scored | |
| 7 | `dedupe_commitments_global.py` | Marks near-duplicate commitments within each document. Only one row per group is scored | |
| 8 | `add_policy_context.py` | Reconstructs the surrounding source text for each commitment | |
| 9 | `preflight_commitments.py` | Audits each document (cap hits, review rates, context coverage) and sets its readiness status | |
| 9 | `select_scoring_input.py` | Selects the rows eligible for scoring and adds the document status columns | |

The extraction system prompt is also saved as text in [`methods/prompts/extraction/`](../../methods/prompts/extraction/). The copy inside `extract_pledges_llm.py` is the one that ran.

Scoring (stage 10) is in [`code/scoring/`](../scoring/). `data/scoring_input.csv` contains the commitments that received a valid score from the published scoring run.

These files are excluded from the repo's formatting and lint hooks so they stay identical to the versions that produced the data.
