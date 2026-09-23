# Analysis Pipeline

This document describes the end-to-end pipeline used to turn a corpus of UK party manifestos into a scored dataset of policy commitments.

## Overview

We convert a heterogeneous corpus of manifesto documents into a structured dataset of policy commitments. We first normalise the source texts, extract commitments with linked source evidence, recover missed items in dense sections, and then clean, screen, deduplicate, and contextualise those commitments. We score the analysis-ready subset against a policy typology, while preserving explicit uncertainty flags and routing borderline cases into human review.

## Stages

### 1. Corpus assembly

We collect manifesto documents from official party websites, public archives, and the Wayback Machine. Each document is catalogued with provenance metadata (source URL, retrieval method, source quality rating) in a single `catalog.csv` that serves as the reproducibility anchor for the corpus.

### 2. Text normalisation

Source files arrive in mixed formats  -  PDF, HTML, and plain text. We convert each into a consistent clean-text representation:

- **PDF**: extracted with `pdftotext`
- **HTML**: extracted with BeautifulSoup
- **Plain text**: UTF-8 normalised

The output is one row per document in a structured table (`documents.csv`) containing metadata and full extracted text.

### 3. Commitment extraction

We use an LLM (via the OpenAI API) to identify atomic policy commitments from each document. The model receives document chunks along with metadata (party, year, title) and a system prompt that defines what counts as a commitment.

Key extraction rules:

- Extract only distinct, forward-looking policy commitments
- Exclude rhetoric, retrospective claims, values statements, and aspirational framing
- Prefer commitments with concrete policy signals (action verbs, numbers, funding mechanisms, timelines, targets)
- Return exact quotes from the source text  -  no paraphrasing or summarising
- Split compound commitments into atomic units

The extractor uses deterministic caching so that re-runs on the same input produce the same output without redundant API calls.

### 4. Saturated-section recovery

Where a chunk appears to contain more commitments than were initially captured (dense policy lists, for example), we rerun extraction on smaller sub-units so that long lists are not under-captured.

### 5. Cleaning and standardisation

We merge outputs from the initial extraction and the recovery pass into a single commitment-level dataset, standardising fields needed for downstream analysis.

### 6. Screening

We apply rule-based filters to flag rows that look like noise: status claims, vague rhetoric, formatting artefacts, or other non-commitments.

### 7. Deduplication

We collapse obvious duplicates so the scoring set contains one row per substantively distinct commitment.

### 8. Policy-context reconstruction

For each retained commitment, we reconstruct a local source-text window containing the commitment and surrounding material needed to interpret it properly. This context window is passed to the scoring stage alongside the commitment text.

### 9. Analysis-readiness gating

We identify which documents and rows are ready for scoring and which should be reviewed, rerun, or held back. Each commitment also gets a trust tier (high, medium or low) and an ambiguity flag. These are kept as columns rather than used to filter rows, so readers can apply their own threshold.

### 10. Scoring

We score every commitment that survives screening and deduplication, from all 108 documents, against the policy typology using a versioned LLM prompt. The document readiness status from the previous stage is kept as a column (`doc_status`) rather than used as a filter. Each commitment is scored with its supporting quote and reconstructed policy context as input. The scorer records the prompt version in its output for reproducibility.

The published `data/commitments.csv` was scored with `gpt-5-mini` (temperature 0) using the rubric in `methods/prompts/discovery/system_prompt_v11.txt`. The scoring script, including the per-commitment message template, is `code/scoring/score_policies_llm.py`. Its input, one row per published commitment with the reconstructed policy context, is `data/scoring_input.csv`:

```bash
uv run code/scoring/score_policies_llm.py --input data/scoring_input.csv
```

Two groups of commitments are not in the published data. 4,630 commitments whose extracted quote could not be matched to the source text were not scored. 758 commitments failed the scorer's validation checks on every retry and have no score. That leaves 23,026 of the 28,414 commitments that survived screening and deduplication.

Scores are accompanied by confidence, ambiguity, and trust signals. Ambiguous rows are retained in the data but also separated into review outputs for human checking.

When summarising scores into the per-manifesto rubric figures, we treat a dimension as a central feature of a commitment when it scores 3 or 4 (out of 4), and report the share of a manifesto's commitments that clear that bar on each dimension. We exclude any manifesto with fewer than 25 scored commitments from those figures, since a handful of commitments gives an unstable share (this drops, for example, Sinn Féin's 6-commitment 2019 manifesto).

### 11. Quality assurance

We generate targeted review subsets and QA packs so that uncertain, unusual, and high-leverage rows can be audited systematically.

## LLM vs deterministic stages

| Stage | Method |
|---|---|
| Text normalisation | Deterministic |
| Commitment extraction | LLM |
| Saturated-section reruns | LLM |
| Table assembly & merging | Deterministic |
| Screening rules | Deterministic |
| Deduplication | Deterministic |
| Policy-context reconstruction | Deterministic |
| Readiness gating | Deterministic |
| Commitment scoring | LLM |
| Sharding & QA pack generation | Deterministic |

The LLM is used for the judgement-heavy tasks; the rest of the pipeline is structured data processing and rule-based filtering.

## Prompt versioning

The extraction system prompt is in `methods/prompts/extraction/`, and the code for stages 3-9 is in `code/pipeline/`. The scoring prompt is stored as a versioned text file under `methods/prompts/`. The scorer loads a specific prompt version at runtime and records it in its outputs. `discovery/system_prompt_v11.txt` is the version behind the published data.

# NLP profiling

Separately from the extraction and scoring pipeline, we run a deterministic word-count analysis across the full corpus. Each manifesto is profiled against ten manually curated word groups relevant to long-term policy orientation:

- **Long-term / short-term**  -  e.g. "long-term", "future generations" vs "immediately", "this year"
- **Definite commitment / aspirational**  -  "we will", "guarantee" vs "aim to", "would", "may"
- **Investment / immediate relief**  -  "infrastructure", "R&D" vs "boost", "cut taxes"
- **Prevention and resilience**  -  "early intervention", "safeguard", "preparedness"
- **Intergenerational**  -  "children", "future generations", "legacy"
- **Institutional**  -  "statutory", "binding", "independent commission", "targets"

The method is deliberately simple and transparent: case-insensitive whole-word matching, with each group reported as a raw hit count and as mentions per 1,000 words. Page furniture is stripped first: any line that recurs four or more times in a document (running headers, slogans, bullet glyphs left by PDF/HTML extraction) is counted once. There are no weights or composite scores, and no LLM is involved. The word lists were reviewed against 1950s-60s manifestos so older phrasing ("stop-go", "reconstruction", "national plan") is credited.



## Current scale

- Corpus: 108 manifestos, 1945 to 2024. Manifestos we could not source are listed in `data/catalog-missing.csv`
- Scored commitments (`data/commitments.csv`): 23,026 across all 108 manifestos
- Trust tiers: 16,786 high, 4,686 medium, 1,554 low; 1,533 commitments are flagged ambiguous
- The per-manifesto rubric figures use all scored commitments, without filtering by trust tier or ambiguity
