# Manifesto Long-Term Evaluation

How much do UK party manifestos talk about the long term? This repository contains the data, methods, and results from Nesta's analysis of 108 UK party manifestos spanning 1945 to 2024.

The project has two parts. First, we count words and phrases associated with long-term (and short-term) thinking in each manifesto, reported as mentions per 1,000 words. Second, we use a large language model to pull out individual policy commitments from each manifesto and classify them against a policy typology. The full methodology is described in [`methods/pipeline.md`](methods/pipeline.md).

## Key outputs

- **[`data/commitments.csv`](data/commitments.csv)** - 23,026 individual policy commitments extracted from the corpus, each scored across six policy dimensions (prevention, physical investment, knowledge investment, risk/resilience, current consumption, constitutional change) with supporting quotes and confidence signals.
- **[`data/nlp_profiles.csv`](data/nlp_profiles.csv)** - word-count language profiles for each manifesto: hits and mentions per 1,000 words across ten curated word groups.
- **[`figures/`](figures/)** - charts covering party rankings, historical trends, and a 2024 manifesto scorecard.
- **[`manifestos/`](manifestos/)** - the source corpus: 108 party manifestos as PDFs, HTML, and plain text.

## Repository layout

```
manifestos/       source corpus (PDF, HTML, txt)
text/             cleaned plain text of each manifesto, used for the word counts
data/
  commitments.csv       scored policy commitments (headline dataset)
  scoring_input.csv     input to the LLM scorer (commitments with policy context)
  nlp_profiles.csv      word-count language profiles (per-1,000-word densities)
  documents.csv         per-document metadata + extracted full text
  catalog.csv           corpus provenance (source URLs, retrieval method, quality)
  catalog-missing.csv   manifestos listed in the Manifesto Project database that we could not source
figures/          charts (PNG)
tables/           supporting tables (TSV)
methods/
  pipeline.md     end-to-end methodology
  prompts/        LLM system prompts used for extraction and scoring
code/             the commitments pipeline as used (code/pipeline/), the scorer (code/scoring/), the NLP profiles, and the review browser data builders
review_browser/   a self-contained web app for browsing commitments alongside the source text
pyproject.toml    Python dependencies (locked in uv.lock)
```

## Setup

The scripts need Python 3.10+ and [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv sync
```

Re-running the LLM scorer also needs an OpenAI API key: copy `.env.example` to `.env` and fill it in. Nothing else needs a key.

If you plan to contribute, install the pre-commit hooks (formatting and linting with ruff), which also run on every pull request:

```bash
uv run pre-commit install
```

## Reproducing the outputs

Run these from the repo root after `uv sync`. Only the scorer needs an API key.

| Output | Command | Notes |
|---|---|---|
| Word-count profiles | `uv run code/nlp/profile_manifestos_nlp.py` | Reads `data/documents.csv` and `text/`, writes to `outputs/nlp/`. The profile table has the same values as `data/nlp_profiles.csv` |
| Figures | `uv run code/nlp/plot_manifestos_nlp.py` | Overwrites `figures/nlp/` by default. Use `--output-dir <dir>` to write elsewhere |
| Review browser data | `uv run code/build_review_browser_data.py`<br>`uv run code/build_nlp_highlights.py` | Rebuild `review_browser/data.json` and `review_browser/nlp_hits.json` from the CSVs in `data/` |
| Commitment scores | `uv run code/scoring/score_policies_llm.py --input data/scoring_input.csv --output-prefix <name>` | Needs `OPENAI_API_KEY`. Writes to `outputs/scores/`. Calls the API once per commitment (23,026 rows), so add `--max-rows 20` to try it first |

The scorer's defaults are the settings behind the published data: prompt v11, `gpt-5-mini`, temperature 0. `data/scoring_input.csv` holds the 23,026 published commitments. Commitments whose quote could not be matched to the source text were not scored in the published run (the scorer's `--only-valid` option has the same effect), and they are already left out of this file.

The earlier stages of the commitments pipeline (stages 3-9 in [`methods/pipeline.md`](methods/pipeline.md)) are in [`code/pipeline/`](code/pipeline/). They are published exactly as used, so the extraction and filtering rules can be read, but they do not run from this repo: their paths point at the working folder they were written in. `data/scoring_input.csv` is their output, less the rows described in the scoring section of `methods/pipeline.md`.

## Review browser

A small static web app with two modes:

- **Policy commitments** - click through each manifesto and inspect every scored commitment next to its supporting quote in the original document.
- **Long-term language** - toggle the ten word groups that drive `data/nlp_profiles.csv` and see every match highlighted in the source text. Multiple groups can be on at once, each in its own colour.

**Hosted**: <https://nestauk.github.io/manifesto-long-term-evaluation/review_browser/>

To run it locally instead:

```bash
python3 -m http.server 8000
# then open http://localhost:8000/review_browser/
```

## Data sources

The list of UK manifestos, and the party codes, dates and titles in the `mp_*` columns of `data/catalog.csv` and `data/documents.csv`, come from the Manifesto Project (document list from the [Manifesto Corpus](https://manifesto-project.wzb.eu/information/documents/corpus), version 2025-1, downloaded March 2026). Please cite:

> Lehmann, Pola / Franzmann, Simon / Al-Gaddooa, Denise / Burst, Tobias / Ivanusch, Christoph / Regel, Sven / Riethmüller, Felicia / Volkens, Andrea / Weßels, Bernhard / Zehnter, Lisa (2025): The Manifesto Data Collection. Manifesto Project (MRG/CMP/MARPOR). Version 2025a. Berlin: Wissenschaftszentrum Berlin für Sozialforschung (WZB) / Göttingen: Institut für Demokratieforschung (IfDem). https://doi.org/10.25522/manifesto.mpds.2025a

The manifesto files themselves were not obtained from the Manifesto Project. They were collected from party websites and public archives, chiefly Political Science Resources (copies saved by the Internet Archive between 2010 and 2015; the website has since changed owner), [CAIN](https://cain.ulster.ac.uk/) at Ulster University, [Lexical Analysis Software](https://lexically.net/) and [UCREL](https://ucrel.lancs.ac.uk/) at Lancaster University. The source of each file is recorded in `data/catalog.csv` (`source_url`, `archive_url`, `source_type`).

## Licence

Code and derived data are released under the [MIT Licence](LICENSE). The source manifestos in `manifestos/` and their cleaned text in `text/` remain the copyright of the parties that published them and are included for research use.
