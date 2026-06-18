# NLP Figures

Word-count charts are generated from [data/nlp_profiles.csv](../../data/nlp_profiles.csv).
The policy-typology (rubric) charts are generated from [data/commitments.csv](../../data/commitments.csv).

Files:

- `nlp_trends_by_decade.png`: decade trends in long-term vs short-term language and definite vs aspirational wording
- `nlp_by_manifesto_year_labour_conservative_government_background.png`: long-term language density per manifesto for Labour and Conservative, with governing-party background bands
- `nlp_labour_component_scores_by_manifesto_year.png`: Labour-only view of six word-group densities over time
- `nlp_conservative_component_scores_by_manifesto_year.png`: Conservative-only view of six word-group densities over time
- `nlp_party_ranking.png`: party averages for long-term language density
- `nlp_2019_scorecard.png`: word-group densities for the 2019 manifestos, shaded by relative standing
- `nlp_2024_scorecard.png`: word-group densities for the 2024 manifestos, shaded by relative standing
- `rubric_2019_scorecard.png`: share of each 2019 manifesto's commitments scoring 3 or 4 on each policy-typology dimension (heatmap)
- `rubric_2019_panels.png`: the same 2019 rubric shares as small-multiple bar panels in Nesta house style

Regenerate with:

```bash
python3 code/nlp/plot_manifestos_nlp.py \
  --input-csv data/nlp_profiles.csv \
  --commitments-csv data/commitments.csv \
  --output-dir figures/nlp
```
