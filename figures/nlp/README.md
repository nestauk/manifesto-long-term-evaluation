# NLP Figures

Illustrative charts generated from [data/nlp_profiles.csv](../../data/nlp_profiles.csv).

Files:

- `nlp_trends_by_decade.png`: decade trends in long-term vs short-term language and definite vs aspirational wording
- `nlp_by_manifesto_year_labour_conservative_government_background.png`: long-term language density per manifesto for Labour and Conservative, with governing-party background bands
- `nlp_labour_component_scores_by_manifesto_year.png`: Labour-only view of six word-group densities over time
- `nlp_conservative_component_scores_by_manifesto_year.png`: Conservative-only view of six word-group densities over time
- `nlp_party_ranking.png`: party averages for long-term language density
- `nlp_2024_scorecard.png`: word-group densities for the 2024 manifestos, shaded by relative standing

Regenerate with:

```bash
python3 code/nlp/plot_manifestos_nlp.py --input-csv data/nlp_profiles.csv --output-dir figures/nlp
```
