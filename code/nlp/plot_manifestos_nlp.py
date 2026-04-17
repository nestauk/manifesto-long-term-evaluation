#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

SCRATCH_DIR = Path(__file__).resolve().parents[2] / "_local" / "scratch"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
MPLCONFIGDIR = SCRATCH_DIR / "mplconfig"
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIGDIR))
os.environ.setdefault("XDG_CACHE_HOME", str(SCRATCH_DIR / "xdg-cache"))

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, Normalize


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = ROOT / "analysis" / "nlp" / "manifesto_nlp_profiles.csv"
DOCUMENTS_INPUT = ROOT / "analysis" / "documents.csv"
DEFAULT_OUTPUT_DIR = ROOT / "results" / "figures" / "nlp"
DEFAULT_GOVERNMENT_PERIODS = ROOT / "results" / "tables" / "uk_governing_periods_since_1945.tsv"

SCORE_COLUMNS = [
    "temporal_orientation_score",
    "commitment_strength_score",
    "investment_stewardship_score",
    "risk_resilience_score",
    "intergenerational_reference_score",
    "institutional_commitment_score",
    "headline_long_termism_score",
]

SCORE_LABELS = {
    "temporal_orientation_score": "Temporal",
    "commitment_strength_score": "Commitment",
    "investment_stewardship_score": "Investment",
    "risk_resilience_score": "Risk",
    "intergenerational_reference_score": "Intergen",
    "institutional_commitment_score": "Institutional",
    "headline_long_termism_score": "Headline",
}

PARTY_LABELS = {
    "alliance": "Alliance",
    "brexit": "Brexit",
    "conservative": "Conservative",
    "dup": "DUP",
    "green": "Green",
    "labour": "Labour",
    "libdem": "Lib Dem",
    "liberal": "Liberal",
    "plaid": "Plaid Cymru",
    "reform": "Reform",
    "sdlp": "SDLP",
    "sinn-fein": "Sinn Fein",
    "snp": "SNP",
    "tuv": "TUV",
    "uup": "UUP",
    "ukip": "UKIP",
}

PARTY_COLORS = {
    "labour": "#c65a46",
    "conservative": "#2b5c88",
}

PARTY_BACKGROUND_COLORS = {
    "labour": "#efd1cb",
    "conservative": "#d4e2f1",
}

COMPONENT_SERIES = [
    ("temporal_orientation_score", "Temporal"),
    ("commitment_strength_score", "Commitment"),
    ("investment_stewardship_score", "Investment"),
    ("risk_resilience_score", "Risk"),
    ("intergenerational_reference_score", "Intergenerational"),
    ("institutional_commitment_score", "Institutional"),
]

COMPONENT_COLORS = {
    "temporal_orientation_score": "#2a9d8f",
    "commitment_strength_score": "#c8553d",
    "investment_stewardship_score": "#4d7c0f",
    "risk_resilience_score": "#7c6ea6",
    "intergenerational_reference_score": "#b7791f",
    "institutional_commitment_score": "#3b82b1",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create illustrative charts from manifesto NLP profiles.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--government-periods-tsv", type=Path, default=DEFAULT_GOVERNMENT_PERIODS)
    return parser.parse_args()


def apply_style() -> None:
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.facecolor": "#f7f4ec",
            "axes.facecolor": "#f7f4ec",
            "savefig.facecolor": "#f7f4ec",
            "axes.edgecolor": "#3e4c59",
            "axes.labelcolor": "#22303c",
            "axes.titlecolor": "#14212b",
            "xtick.color": "#34424f",
            "ytick.color": "#34424f",
            "text.color": "#14212b",
            "font.size": 10,
            "axes.titlesize": 14,
            "axes.labelsize": 10,
            "figure.titlesize": 18,
            "legend.fontsize": 9,
        }
    )


def load_profiles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    numeric_columns = [
        "year",
        "word_count",
        "long_term_hits",
        "short_term_hits",
        *SCORE_COLUMNS,
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    df["decade"] = (df["year"] // 10) * 10
    df["long_term_density_per_1000_words"] = df["long_term_hits"] * 1000.0 / df["word_count"]
    df["short_term_density_per_1000_words"] = df["short_term_hits"] * 1000.0 / df["word_count"]
    return df


def load_documents(path: Path = DOCUMENTS_INPUT) -> pd.DataFrame:
    return pd.read_csv(path, usecols=["doc_id", "party_slug", "year", "variant", "title"])


def load_government_periods(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, sep="\t")


def party_label(slug: str) -> str:
    return PARTY_LABELS.get(slug, slug.replace("-", " ").title())


def save_figure(fig: plt.Figure, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    plt.close(fig)


def add_figure_header(fig: plt.Figure, title: str, subtitle: str, left: float = 0.08) -> None:
    fig.text(left, 0.965, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(left, 0.93, subtitle, ha="left", va="top", fontsize=9.5, color="#5d6c7a")


def add_figure_footer(fig: plt.Figure, text: str, left: float = 0.08) -> None:
    fig.text(left, 0.045, text, ha="left", va="bottom", fontsize=8.5, color="#5d6c7a")


def date_to_year_fraction(value: str) -> float:
    parsed = date.fromisoformat(value)
    year_start = date(parsed.year, 1, 1)
    next_year_start = date(parsed.year + 1, 1, 1)
    return parsed.year + (parsed.toordinal() - year_start.toordinal()) / (
        next_year_start.toordinal() - year_start.toordinal()
    )


def add_government_background(ax: plt.Axes, government_periods: pd.DataFrame) -> None:
    if government_periods.empty:
        return
    for _, row in government_periods.iterrows():
        party = row["governing_party"]
        start = date_to_year_fraction(row["start_date"])
        end = (
            date_to_year_fraction(row["end_date_exclusive"])
            if pd.notna(row["end_date_exclusive"]) and str(row["end_date_exclusive"]).strip()
            else 2025.0
        )
        ax.axvspan(
            start,
            end,
            facecolor=PARTY_BACKGROUND_COLORS.get(party, "#e6dfd1"),
            alpha=0.42 if row.get("government_type", "") == "coalition" else 0.32,
            zorder=0,
            linewidth=0,
        )


def spread_label_positions(label_targets: list[tuple[str, float]], lower: float, upper: float, min_gap: float) -> dict[str, float]:
    ordered = sorted(label_targets, key=lambda item: item[1])
    adjusted: list[tuple[str, float]] = []
    for key, value in ordered:
        if not adjusted:
            adjusted.append((key, max(value, lower)))
            continue
        adjusted.append((key, max(value, adjusted[-1][1] + min_gap)))

    overflow = adjusted[-1][1] - upper if adjusted else 0.0
    if overflow > 0:
        adjusted = [(key, value - overflow) for key, value in adjusted]

    for index in range(len(adjusted) - 2, -1, -1):
        next_key, next_value = adjusted[index + 1]
        key, value = adjusted[index]
        adjusted[index] = (key, min(value, next_value - min_gap))

    return {key: min(max(value, lower), upper) for key, value in adjusted}


def build_labour_conservative_grouped(df: pd.DataFrame) -> pd.DataFrame:
    compare_parties = ["labour", "conservative"]
    filtered = df.loc[df["party_slug"].isin(compare_parties)].copy()
    return (
        filtered.groupby(["party_slug", "decade"], as_index=False)
        .agg(
            manifesto_count=("doc_id", "count"),
            headline_long_termism_score=("headline_long_termism_score", "mean"),
            long_term_density_per_1000_words=("long_term_density_per_1000_words", "mean"),
            short_term_density_per_1000_words=("short_term_density_per_1000_words", "mean"),
        )
        .sort_values(["party_slug", "decade"])
    )


def build_labour_conservative_manifesto_year_points(profile_df: pd.DataFrame) -> pd.DataFrame:
    documents_df = load_documents()
    merged = profile_df.merge(
        documents_df[["doc_id", "variant", "title"]],
        on="doc_id",
        how="left",
        suffixes=("", "_doc"),
    )
    filtered = merged.loc[merged["party_slug"].isin(["labour", "conservative"])].copy()
    filtered["year"] = filtered["year"].astype(int)
    filtered["variant"] = filtered["variant"].fillna("")
    variant_order = {"feb": 0, "": 1, "oct": 2}
    filtered["variant_order"] = filtered["variant"].map(lambda value: variant_order.get(str(value).lower(), 1))
    return filtered.sort_values(["party_slug", "year", "variant_order", "title"])


def render_labour_conservative_chart(
    grouped: pd.DataFrame,
    output_path: Path,
    title: str,
    subtitle: str,
    footer: str,
    government_periods: pd.DataFrame | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(9.6, 5.8))
    fig.subplots_adjust(left=0.1, right=0.96, top=0.82, bottom=0.18)
    add_figure_header(fig, title, subtitle)

    if government_periods is not None and not government_periods.empty:
        add_government_background(ax, government_periods)

    label_offsets = {"labour": 0.6, "conservative": -0.8}
    all_values: list[float] = []
    for party in ["labour", "conservative"]:
        party_df = grouped.loc[grouped["party_slug"] == party].sort_values("decade")
        color = PARTY_COLORS[party]
        label = party_label(party)
        all_values.extend(party_df["headline_long_termism_score"].tolist())
        ax.plot(
            party_df["decade"],
            party_df["headline_long_termism_score"],
            color=color,
            linewidth=3,
            marker="o",
            markersize=7,
            zorder=3,
        )
        last_row = party_df.iloc[-1]
        ax.text(
            last_row["decade"] + 0.9,
            last_row["headline_long_termism_score"] + label_offsets[party],
            label,
            color=color,
            fontsize=10.5,
            fontweight="semibold",
            va="center",
        )

    ax.set_xlabel("Decade")
    ax.set_ylabel("Average heuristic score")
    ax.set_xlim(1936, 2026)
    ax.set_ylim(min(all_values) - 4, max(all_values) + 4)
    ax.set_xticks(sorted(grouped["decade"].unique()))
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)

    add_figure_footer(fig, footer)
    save_figure(fig, output_path)


def chart_labour_conservative_manifesto_year(
    df: pd.DataFrame,
    output_dir: Path,
    government_periods: pd.DataFrame,
) -> None:
    points = build_labour_conservative_manifesto_year_points(df)
    fig, ax = plt.subplots(figsize=(10.4, 5.9))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.82, bottom=0.18)
    add_figure_header(
        fig,
        "Labour And Conservative NLP Language Score By Manifesto Year",
        "Each point is one manifesto, placed by year. The score is based on the balance of long-term versus short-term wording in the manifesto, adjusted for length.",
    )

    add_government_background(ax, government_periods)

    all_values: list[float] = []
    for party in ["labour", "conservative"]:
        party_df = points.loc[points["party_slug"] == party].sort_values(["year", "variant_order"])
        color = PARTY_COLORS[party]
        label = party_label(party)
        all_values.extend(party_df["headline_long_termism_score"].tolist())
        ax.plot(
            party_df["year"],
            party_df["headline_long_termism_score"],
            color=color,
            linewidth=2.4,
            marker="o",
            markersize=6.5,
            zorder=3,
        )
        last_row = party_df.iloc[-1]
        ax.text(
            last_row["year"] + 0.8,
            last_row["headline_long_termism_score"] + (0.4 if party == "labour" else -0.7),
            label,
            color=color,
            fontsize=10.5,
            fontweight="semibold",
            va="center",
        )

    ax.set_xlabel("Manifesto year")
    ax.set_ylabel("Average heuristic score")
    ax.set_xlim(1944, 2025.5)
    ax.set_ylim(min(all_values) - 4, max(all_values) + 4)
    ax.set_xticks(list(range(1945, 2026, 5)))
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)

    add_figure_footer(
        fig,
        "Background shows governing-party periods. 1974 appears twice because there were February and October general elections with separate manifestos.",
    )
    save_figure(fig, output_dir / "nlp_by_manifesto_year_labour_conservative_government_background.svg")


def chart_party_component_trends(df: pd.DataFrame, party_slug: str, output_dir: Path) -> None:
    points = build_labour_conservative_manifesto_year_points(df)
    party_df = points.loc[points["party_slug"] == party_slug].sort_values(["year", "variant_order"])
    party_name = party_label(party_slug)

    fig, ax = plt.subplots(figsize=(10.4, 6.0))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.82, bottom=0.18)
    add_figure_header(
        fig,
        f"{party_name} NLP Component Scores By Manifesto Year",
        "These six lines are the building blocks of the aggregate heuristic score. Higher lines mean more of that kind of language in the manifesto text.",
    )

    end_targets: list[tuple[str, float]] = []
    last_year = int(party_df["year"].max())
    for score_key, label in COMPONENT_SERIES:
        color = COMPONENT_COLORS[score_key]
        ax.plot(
            party_df["year"],
            party_df[score_key],
            color=color,
            linewidth=2.2,
            marker="o",
            markersize=5.6,
            zorder=3,
        )
        end_targets.append((score_key, float(party_df.iloc[-1][score_key])))

    adjusted_positions = spread_label_positions(end_targets, lower=6.0, upper=94.0, min_gap=4.0)
    for score_key, label in COMPONENT_SERIES:
        final_value = float(party_df.iloc[-1][score_key])
        label_y = adjusted_positions[score_key]
        color = COMPONENT_COLORS[score_key]
        ax.plot([last_year, last_year + 0.7], [final_value, label_y], color=color, linewidth=1.1, alpha=0.9)
        ax.text(
            last_year + 0.95,
            label_y,
            label,
            color=color,
            fontsize=10,
            fontweight="semibold",
            va="center",
        )

    ax.set_xlabel("Manifesto year")
    ax.set_ylabel("Component score")
    ax.set_xlim(1944, 2032)
    ax.set_ylim(0, 100)
    ax.set_xticks(list(range(1945, 2026, 5)))
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)

    add_figure_footer(
        fig,
        "1974 appears twice because there were February and October general elections with separate manifestos. These remain simple language-based heuristic component scores.",
    )
    save_figure(fig, output_dir / f"nlp_{party_slug}_component_scores_by_manifesto_year.svg")


def chart_decade_trends(df: pd.DataFrame, output_dir: Path) -> None:
    grouped = (
        df.groupby("decade", as_index=False)
        .agg(
            manifesto_count=("doc_id", "count"),
            headline_long_termism_score=("headline_long_termism_score", "mean"),
            long_term_density_per_1000_words=("long_term_density_per_1000_words", "mean"),
            short_term_density_per_1000_words=("short_term_density_per_1000_words", "mean"),
        )
        .sort_values("decade")
    )

    decades = grouped["decade"].tolist()
    counts = grouped["manifesto_count"].tolist()
    headline = grouped["headline_long_termism_score"].tolist()
    long_term_density = grouped["long_term_density_per_1000_words"].tolist()
    short_term_density = grouped["short_term_density_per_1000_words"].tolist()

    fig, axes = plt.subplots(1, 2, figsize=(14.2, 6.2), gridspec_kw={"width_ratios": [1.1, 1]})
    fig.subplots_adjust(left=0.08, right=0.98, top=0.84, bottom=0.16, wspace=0.2)
    add_figure_header(
        fig,
        "Manifesto NLP Trends Over Time",
        "Long-term language rises over the decades, while short-term language stays flatter and more cyclical.",
    )

    ax = axes[0]
    ax.plot(decades, headline, color="#1f6f78", linewidth=3, marker="o", markersize=7)
    ax.set_title("Composite headline score by decade", loc="left", pad=14, fontsize=13)
    ax.set_ylabel("Average score")
    ax.set_xlabel("Decade")
    ax.set_ylim(0, 70)
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    for x, y, count in zip(decades, headline, counts):
        ax.text(x, y + 1.6, f"n={count}", ha="center", va="bottom", fontsize=8, color="#5d6c7a")

    ax = axes[1]
    ax.plot(
        decades,
        long_term_density,
        color="#2f855a",
        linewidth=2.8,
        marker="o",
        markersize=6,
        label="Long-term markers",
    )
    ax.plot(
        decades,
        short_term_density,
        color="#c05621",
        linewidth=2.8,
        marker="o",
        markersize=6,
        label="Short-term markers",
    )
    ax.fill_between(decades, long_term_density, short_term_density, color="#e6dfd1", alpha=0.45)
    ax.set_title("Long-term versus short-term language density", loc="left", pad=14, fontsize=13)
    ax.set_ylabel("Average mentions per 1,000 words")
    ax.set_xlabel("Decade")
    ax.set_ylim(0, max(long_term_density + short_term_density) + 1.2)
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.legend(frameon=False, loc="upper left")

    add_figure_footer(
        fig,
        "Source: manifestos/analysis/nlp/manifesto_nlp_profiles.csv. Decade averages across 109 manifestos.",
    )
    save_figure(fig, output_dir / "nlp_trends_by_decade.svg")


def chart_party_ranking(df: pd.DataFrame, output_dir: Path) -> None:
    party_df = (
        df.groupby("party_slug", as_index=False)
        .agg(
            manifesto_count=("doc_id", "count"),
            headline_long_termism_score=("headline_long_termism_score", "mean"),
            institutional_commitment_score=("institutional_commitment_score", "mean"),
        )
        .query("manifesto_count >= 4")
        .sort_values("headline_long_termism_score", ascending=True)
    )

    y_positions = list(range(len(party_df)))
    labels = [party_label(slug) for slug in party_df["party_slug"]]
    headline = party_df["headline_long_termism_score"].tolist()
    institutional = party_df["institutional_commitment_score"].tolist()
    counts = party_df["manifesto_count"].tolist()

    fig, ax = plt.subplots(figsize=(10.8, 7.0))
    fig.subplots_adjust(left=0.14, right=0.98, top=0.87, bottom=0.13)
    add_figure_header(
        fig,
        "Average Headline Long-Termism By Party",
        "Bars show the composite heuristic score averaged across all manifestos for each party.",
        left=0.14,
    )
    ax.barh(y_positions, headline, color="#1f6f78", alpha=0.88, height=0.62)

    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Average score")
    ax.set_xlim(0, max(headline) + 10)
    ax.grid(axis="x", color="#d7d2c8", linewidth=0.8)

    for y, x, count in zip(y_positions, headline, counts):
        ax.text(x + 1.0, y, f"n={count}", va="center", ha="left", fontsize=8, color="#5d6c7a")

    add_figure_footer(fig, "Parties with at least four manifestos in the corpus.", left=0.14)
    save_figure(fig, output_dir / "nlp_party_ranking.svg")


def chart_2024_heatmap(df: pd.DataFrame, output_dir: Path) -> None:
    score_columns = [
        "temporal_orientation_score",
        "commitment_strength_score",
        "investment_stewardship_score",
        "risk_resilience_score",
        "intergenerational_reference_score",
        "institutional_commitment_score",
    ]
    heatmap_df = (
        df.loc[df["year"] == 2024, ["party_slug", "headline_long_termism_score", *score_columns]]
        .sort_values("headline_long_termism_score", ascending=False)
        .reset_index(drop=True)
    )

    values = heatmap_df[score_columns].to_numpy(dtype=float)
    row_labels = [party_label(slug) for slug in heatmap_df["party_slug"]]
    col_labels = [SCORE_LABELS[column] for column in score_columns]
    cmap = LinearSegmentedColormap.from_list(
        "nesta_nlp",
        ["#f4e7d3", "#c7dfd3", "#1f6f78"],
    )

    fig, ax = plt.subplots(figsize=(10.8, 7.6))
    fig.subplots_adjust(left=0.14, right=0.94, top=0.88, bottom=0.11)
    add_figure_header(
        fig,
        "2024 Manifesto Scorecard",
        "Each cell is a 0-100 heuristic score; rows are ordered by the overall headline long-termism score.",
        left=0.14,
    )
    image = ax.imshow(values, cmap=cmap, norm=Normalize(vmin=0, vmax=100), aspect="auto")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels)
    ax.tick_params(top=False, bottom=True, labeltop=False, labelbottom=True)
    ax.set_xticks([x - 0.5 for x in range(1, values.shape[1])], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, values.shape[0])], minor=True)
    ax.grid(which="minor", color="#f7f4ec", linewidth=1.4)
    ax.tick_params(which="minor", bottom=False, left=False)

    for row_index in range(values.shape[0]):
        for col_index in range(values.shape[1]):
            value = values[row_index, col_index]
            text_color = "#102027" if value < 62 else "#f7f4ec"
            ax.text(
                col_index,
                row_index,
                f"{value:.0f}",
                ha="center",
                va="center",
                fontsize=8.5,
                color=text_color,
            )

    cbar = fig.colorbar(image, ax=ax, fraction=0.03, pad=0.03)
    cbar.set_label("Score")

    legend_lines = [
        "Temporal = long-term vs short-term language balance",
        "Commitment = definite commitments vs aspirational language",
        "Investment = investment, infrastructure, and prevention references",
        "Risk = resilience, security, and risk language",
        "Intergen = references to children, future generations, legacy",
        "Institutional = binding frameworks, targets, commissions",
    ]
    fig.text(
        0.14, 0.045,
        "    ".join(legend_lines[:3]),
        ha="left", va="bottom", fontsize=7.5, color="#5d6c7a",
    )
    fig.text(
        0.14, 0.02,
        "    ".join(legend_lines[3:]),
        ha="left", va="bottom", fontsize=7.5, color="#5d6c7a",
    )
    save_figure(fig, output_dir / "nlp_2024_scorecard.svg")


def chart_labour_conservative_trends(df: pd.DataFrame, output_dir: Path) -> None:
    grouped = build_labour_conservative_grouped(df)
    render_labour_conservative_chart(
        grouped,
        output_dir / "nlp_trends_by_decade_labour_conservative.svg",
        "Labour And Conservative NLP Language Score By Decade",
        "Heuristic score from manifesto language patterns and word-count normalization; not a semantic or policy-quality assessment.",
        "Based on keyword and phrase counts, normalized by manifesto length. Decade averages from 22 Labour and 22 Conservative manifestos in the local corpus.",
    )


def chart_labour_conservative_trends_with_government(
    df: pd.DataFrame,
    output_dir: Path,
    government_periods: pd.DataFrame,
) -> None:
    grouped = build_labour_conservative_grouped(df)
    render_labour_conservative_chart(
        grouped,
        output_dir / "nlp_trends_by_decade_labour_conservative_government_background.svg",
        "Labour And Conservative NLP Language Score By Decade",
        "Shaded bands show which party was in government; the plotted score is still just a heuristic from manifesto language patterns and word-count normalization.",
        "Background shows governing-party periods from 26 July 1945 onward. The 2010-2015 band is Conservative-led because David Cameron headed a Conservative-Liberal Democrat coalition government.",
        government_periods=government_periods,
    )


def main() -> None:
    args = parse_args()
    apply_style()
    df = load_profiles(args.input_csv)
    government_periods = load_government_periods(args.government_periods_tsv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    chart_decade_trends(df, args.output_dir)
    chart_party_ranking(df, args.output_dir)
    chart_2024_heatmap(df, args.output_dir)
    chart_labour_conservative_trends_with_government(df, args.output_dir, government_periods)
    chart_labour_conservative_manifesto_year(df, args.output_dir, government_periods)
    chart_party_component_trends(df, "labour", args.output_dir)
    chart_party_component_trends(df, "conservative", args.output_dir)


if __name__ == "__main__":
    main()
