# NLP Figures

Illustrative charts generated from [analysis/nlp/manifesto_nlp_profiles.csv](../../../analysis/nlp/manifesto_nlp_profiles.csv).

Files:

- `nlp_trends_by_decade.png`: historical trend in the composite headline score and long-term versus short-term language density
- `nlp_by_manifesto_year_labour_conservative_government_background.png`: manifesto-by-manifesto version on a year axis rather than decade averages, with governing-party background bands
- `nlp_labour_component_scores_by_manifesto_year.png`: Labour-only view of the six component scores over time
- `nlp_conservative_component_scores_by_manifesto_year.png`: Conservative-only view of the six component scores over time
- `nlp_party_ranking.png`: party averages for the composite headline score
- `nlp_2024_scorecard.png`: heatmap of the six component scores for the 2024 manifestos

Regenerate with:

```bash
python3 scripts/nlp/plot_manifestos_nlp.py
```
