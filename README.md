# Manifesto Long-Term Evaluation

How much do UK party manifestos talk about the long term? This repository contains the data, methods, and results from Nesta's analysis of 108 UK party manifestos spanning 1945 to 2024.

The project has two parts. First, we count words and phrases associated with long-term (and short-term) thinking in each manifesto, reported as mentions per 1,000 words. Second, we use a large language model to pull out individual policy commitments from each manifesto and classify them against a policy typology. The full methodology is described in [`methods/pipeline.md`](methods/pipeline.md).

## Key outputs

- **[`data/commitments.csv`](data/commitments.csv)** - 23,026 individual policy commitments extracted from the corpus, each scored across six policy dimensions (prevention, physical investment, knowledge investment, risk/resilience, current consumption, constitutional change) with the reasons for each score and confidence signals. Each commitment's place in its manifesto is given as a PDF page (`pdf_page`, for PDF sources; it can be a page or two out) and as how far through the document it appears (`position_pct`), so it can be looked up in the source listed in `data/catalog.csv`.
- **[`data/nlp_profiles.csv`](data/nlp_profiles.csv)** - word-count language profiles for each manifesto: hits and mentions per 1,000 words across ten curated word groups.
- **[`figures/`](figures/)** - charts covering party rankings, historical trends, and a 2024 manifesto scorecard.

## Manifesto texts

This repository publishes our methods and results, not the manifestos themselves: by agreement with the Manifesto Project, the manifesto texts and quotes from them are not included. Every manifesto we used is listed in [`data/catalog.csv`](data/catalog.csv) with its source, so the corpus can be rebuilt to reproduce our results (see [Reproducing the outputs](#reproducing-the-outputs)).

## Repository layout

```
data/
  commitments.csv       scored policy commitments (headline dataset)
  scoring_input.csv     the commitments sent to the LLM scorer, with their pipeline metadata
  nlp_profiles.csv      word-count language profiles (per-1,000-word densities)
  documents.csv         per-document metadata (length, extraction method, checksum)
  catalog.csv           corpus provenance (source URLs, retrieval method, quality)
  catalog-missing.csv   manifestos listed in the Manifesto Project database that we could not source
figures/          charts (PNG)
tables/           supporting tables (TSV)
methods/
  pipeline.md     end-to-end methodology
  prompts/        LLM system prompts used for extraction and scoring
code/             the commitments pipeline as used (code/pipeline/), the scorer (code/scoring/), and the NLP profiles
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

First rebuild the corpus. Download each manifesto in `data/catalog.csv` from its `source_url` (or `archive_url`), convert it to plain text, and save it as `text/<party_slug>/<file name>.txt`, where the file name is the one in the catalog's `local_path` without its extension. `data/documents.csv` records how we extracted each text (`extraction_method`) and its length, so you can check your copy against ours.

| Output | Command | Notes |
|---|---|---|
| Word-count profiles | `uv run code/nlp/profile_manifestos_nlp.py` | Reads `data/documents.csv` and `text/`, writes to `outputs/nlp/`. With the same texts, the profile table has the same counts as `data/nlp_profiles.csv` (it also has an example passage per word group, which is not published here) |
| Figures | `uv run code/nlp/plot_manifestos_nlp.py` | Overwrites `figures/nlp/` by default. Use `--output-dir <dir>` to write elsewhere |
| Commitment scores | `uv run code/scoring/score_policies_llm.py --input <file> --output-prefix <name>` | Needs `OPENAI_API_KEY`. Writes to `outputs/scores/`. Calls the API once per commitment (23,026 rows), so add `--max-rows 20` to try it first |

The scorer reads each commitment with its supporting quote and the surrounding policy context, both taken from the manifesto text, so its input file is not published here. `data/scoring_input.csv` lists the commitments that were scored. The quote and context for each one come from the pipeline in [`code/pipeline/`](code/pipeline/) (the context from [`add_policy_context.py`](code/pipeline/add_policy_context.py)); add them as `supporting_quote` and `policy_context` columns to make the scorer's input file.

The scorer's defaults are the settings behind the published data: prompt v11, `gpt-5-mini`, temperature 0. `data/scoring_input.csv` holds the 23,026 published commitments. Commitments whose quote could not be matched to the source text were not scored in the published run (the scorer's `--only-valid` option has the same effect), and they are already left out of this file.

The earlier stages of the commitments pipeline (stages 3-9 in [`methods/pipeline.md`](methods/pipeline.md)) are in [`code/pipeline/`](code/pipeline/). They are published exactly as used, so the extraction and filtering rules can be read, but they do not run from this repo: their paths point at the working folder they were written in. `data/scoring_input.csv` is their output, less the rows described in the scoring section of `methods/pipeline.md`.

## Data sources

The list of UK manifestos, and the party codes, dates and titles in the `mp_*` columns of `data/catalog.csv` and `data/documents.csv`, come from the Manifesto Project (document list from the [Manifesto Corpus](https://manifesto-project.wzb.eu/information/documents/corpus), version 2025-1, downloaded March 2026). Please cite:

> Lehmann, Pola / Franzmann, Simon / Al-Gaddooa, Denise / Burst, Tobias / Ivanusch, Christoph / Regel, Sven / Riethmüller, Felicia / Volkens, Andrea / Weßels, Bernhard / Zehnter, Lisa (2025): The Manifesto Data Collection. Manifesto Project (MRG/CMP/MARPOR). Version 2025a. Berlin: Wissenschaftszentrum Berlin für Sozialforschung (WZB) / Göttingen: Institut für Demokratieforschung (IfDem). https://doi.org/10.25522/manifesto.mpds.2025a

The manifesto files themselves were not obtained from the Manifesto Project. They were collected from party websites and public archives, chiefly Political Science Resources (copies saved by the Internet Archive between 2010 and 2015; the website has since changed owner), [CAIN](https://cain.ulster.ac.uk/) at Ulster University, [Lexical Analysis Software](https://lexically.net/) and [UCREL](https://ucrel.lancs.ac.uk/) at Lancaster University. The source of each file is recorded in `data/catalog.csv` (`source_url`, `archive_url`, `source_type`).

## Licence

Code and derived data are released under the [MIT Licence](LICENSE). The manifestos themselves remain the copyright of the parties that published them.
