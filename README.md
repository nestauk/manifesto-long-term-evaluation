# Manifesto Long-Term Evaluation

How much do UK party manifestos talk about the long term? This repository contains the data, methods, and results from Nesta's analysis of 108 UK party manifestos spanning 1945 to 2024.

The project has two parts. First, we search each manifesto for words and phrases associated with long-term thinking and produce a set of scores for each document. Second, we use a large language model to pull out individual policy commitments from each manifesto and classify them against a policy typology. The full methodology is described in [`methods/pipeline.md`](methods/pipeline.md).

## Key outputs

- **[`data/commitments.csv`](data/commitments.csv)** - 23,026 individual policy commitments extracted from the corpus, each scored across six policy dimensions (prevention, tangible investment, intangible investment, risk/resilience, current consumption, constitutional change) with supporting quotes and confidence signals.
- **[`data/nlp_profiles.csv`](data/nlp_profiles.csv)** - a profile for each manifesto across six dimensions of long-term language.
- **[`figures/`](figures/)** - charts covering party rankings, historical trends, and a 2024 manifesto scorecard.
- **[`manifestos/`](manifestos/)** - the source corpus: 108 party manifestos as PDFs, HTML, and plain text.

## Repository layout

```
manifestos/       source corpus (PDF, HTML, txt)
data/
  commitments.csv       scored policy commitments (headline dataset)
  nlp_profiles.csv      long-term-language profiles (headline dataset)
  documents.csv         per-document metadata + extracted full text
  catalog.csv           corpus provenance (source URLs, retrieval method, quality)
  catalog-missing.csv   manifestos listed in the Manifesto Project database that we could not source
figures/          charts (PNG)
tables/           supporting tables (TSV)
methods/
  pipeline.md     end-to-end methodology
  prompts/        LLM system prompts used for extraction and scoring
code/             scripts used to generate the NLP profiles and review browser data
review_browser/   a self-contained web app for browsing commitments alongside the source text
```

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

## Regenerating the review browser data

The browser loads two generated artefacts. Rebuild them whenever the underlying CSVs change:

```bash
uv run code/build_review_browser_data.py     # commitments mode (review_browser/data.json)
uv run code/build_nlp_highlights.py          # long-term-language mode (review_browser/nlp_hits.json)
```

`data.json` is built from `data/commitments.csv` and `data/documents.csv`. `nlp_hits.json` reuses the regex patterns in `code/nlp/profile_manifestos_nlp.py` to precompute the character offset of every word-group match in each manifesto, so the browser highlights without re-running regex client-side.
