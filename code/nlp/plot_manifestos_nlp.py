#!/usr/bin/env python3
"""Generate NLP figures from the word-count density profiles.

Every chart plots mentions per 1,000 words from manifesto_nlp_profiles.csv.
There are no composite scores or weights anywhere: the only transformation of
the underlying counts is division by document length, and decade or party
averaging where labelled.
"""
from __future__ import annotations

import argparse
from pathlib import Path

SCRATCH_DIR = Path(__file__).resolve().parents[2] / "_local" / "scratch"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
MPLCONFIGDIR = SCRATCH_DIR / "mplconfig"
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
import os

os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIGDIR))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = ROOT / "data" / "nlp_profiles.csv"
DEFAULT_OUTPUT_DIR = ROOT / "figures" / "nlp"
DEFAULT_GOVERNMENT_PERIODS = ROOT / "tables" / "uk_governing_periods_since_1945.tsv"

GROUPS = [
    ("long_term", "Long-term"),
    ("short_term", "Short-term"),
    ("definite_commitment", "Definite commitment"),
    ("investment", "Investment"),
    ("resilience", "Resilience"),
    ("institutional", "Institutional"),
]

PARTY_LABELS = {
    "labour": "Labour",
    "conservative": "Conservative",
    "libdem": "Lib Dem",
    "liberal": "Liberal",
    "snp": "SNP",
    "plaid": "Plaid Cymru",
    "green": "Green",
    "dup": "DUP",
    "uup": "UUP",
    "sdlp": "SDLP",
    "sinn-fein": "Sinn Féin",
    "alliance": "Alliance",
    "ukip": "UKIP",
    "brexit": "Brexit Party",
    "reform": "Reform",
    "tuv": "TUV",
}

LABOUR_COLOUR = "#c14f4f"
CONSERVATIVE_COLOUR = "#3a5d8f"
TEAL = "#1f6f78"
ORANGE = "#c8742a"
GROUP_COLOURS = {
    "long_term": "#1f6f78",
    "short_term": "#c8742a",
    "definite_commitment": "#7a4f9d",
    "investment": "#4a7a3a",
    "resilience": "#a3403f",
    "institutional": "#3a5d8f",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--government-periods", type=Path, default=DEFAULT_GOVERNMENT_PERIODS
    )
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
            "axes.titlesize": 13,
            "legend.fontsize": 9,
        }
    )


def load_profiles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    df["decade"] = (df["year"] // 10) * 10
    return df


def add_header(fig: plt.Figure, title: str, subtitle: str) -> None:
    fig.text(0.05, 0.955, title, fontsize=16, fontweight="bold")
    fig.text(0.05, 0.915, subtitle, fontsize=9.5, color="#5d6c7a")


def add_footer(fig: plt.Figure, text: str) -> None:
    fig.text(0.05, 0.025, text, fontsize=8, color="#5d6c7a")


def save_figure(fig: plt.Figure, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def method_footer(df: pd.DataFrame) -> str:
    return (
        "Method: case-insensitive whole-word lexicon counts divided by document length. "
        f"Word counts only, no weights, no composite scores. {len(df)} manifestos."
    )


def chart_decade_trends(df: pd.DataFrame, output_dir: Path) -> None:
    grouped = df.groupby("decade")[
        [
            "long_term_per_1000_words",
            "short_term_per_1000_words",
            "definite_commitment_per_1000_words",
            "aspirational_per_1000_words",
        ]
    ].mean()
    counts = df.groupby("decade").size()

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.0))
    fig.subplots_adjust(left=0.06, right=0.97, top=0.82, bottom=0.16, wspace=0.18)
    add_header(
        fig,
        "Manifesto Language Over Time",
        "Average mentions per 1,000 words, by decade, across the full corpus.",
    )

    ax = axes[0]
    ax.plot(grouped.index, grouped["long_term_per_1000_words"], color=TEAL,
            linewidth=3, marker="o", markersize=6, label="Long-term markers")
    ax.plot(grouped.index, grouped["short_term_per_1000_words"], color=ORANGE,
            linewidth=3, marker="o", markersize=6, label="Short-term markers")
    ax.set_title("Long-term versus short-term language", loc="left", pad=12)
    for decade, count in counts.items():
        ax.annotate(f"n={count}", (decade, grouped.loc[decade, "long_term_per_1000_words"]),
                    textcoords="offset points", xytext=(0, 8), ha="center",
                    fontsize=7.5, color="#5d6c7a")
    ax.legend(frameon=False, loc="upper left")

    ax = axes[1]
    ax.plot(grouped.index, grouped["definite_commitment_per_1000_words"],
            color=GROUP_COLOURS["definite_commitment"], linewidth=3, marker="o",
            markersize=6, label="Definite pledges (“we will …”)")
    ax.plot(grouped.index, grouped["aspirational_per_1000_words"], color="#8a8157",
            linewidth=3, marker="o", markersize=6, label="Aspirational wording")
    ax.set_title("Definite versus aspirational wording", loc="left", pad=12)
    ax.legend(frameon=False, loc="upper left")

    for ax in axes:
        ax.set_xlabel("Decade")
        ax.set_ylabel("Mentions per 1,000 words")
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)

    add_footer(fig, method_footer(df))
    save_figure(fig, output_dir / "nlp_trends_by_decade.png")


def load_government_periods(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    periods = pd.read_csv(path, sep="\t")
    periods["start"] = pd.to_datetime(periods["start_date"]).dt.year
    periods["end"] = pd.to_datetime(periods["end_date_exclusive"]).dt.year
    return periods


def draw_government_bands(ax: plt.Axes, periods: pd.DataFrame) -> None:
    band_colours = {"labour": "#c14f4f", "conservative": "#3a5d8f"}
    for _, period in periods.iterrows():
        colour = band_colours.get(str(period["governing_party"]).strip())
        if colour is None:
            continue
        ax.axvspan(period["start"], period["end"], color=colour, alpha=0.07, zorder=0)


def chart_two_party_year(df: pd.DataFrame, periods: pd.DataFrame, output_dir: Path) -> None:
    sub = (
        df[df["party_slug"].isin(["labour", "conservative"])]
        .groupby(["party_slug", "year"], as_index=False)["long_term_per_1000_words"]
        .mean()
    )
    fig, ax = plt.subplots(figsize=(12.5, 6.2))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.82, bottom=0.14)
    add_header(
        fig,
        "Long-Term Language By Manifesto Year",
        "Long-term mentions per 1,000 words per manifesto. Background bands show the governing party.\n"
        "February and October 1974 averaged.",
    )
    draw_government_bands(ax, periods)
    for party, colour in [("labour", LABOUR_COLOUR), ("conservative", CONSERVATIVE_COLOUR)]:
        p = sub[sub["party_slug"] == party].sort_values("year")
        ax.plot(p["year"], p["long_term_per_1000_words"], color=colour, linewidth=2.5,
                marker="o", markersize=4.5, label=PARTY_LABELS[party])
    ax.set_xlabel("Manifesto year")
    ax.set_ylabel("Long-term mentions per 1,000 words")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    add_footer(fig, method_footer(df))
    save_figure(
        fig,
        output_dir / "nlp_by_manifesto_year_labour_conservative_government_background.png",
    )


def chart_party_components(df: pd.DataFrame, party_slug: str, output_dir: Path) -> None:
    sub = (
        df[df["party_slug"] == party_slug]
        .groupby("year", as_index=False)[
            [f"{group}_per_1000_words" for group, _ in GROUPS]
        ]
        .mean()
        .sort_values("year")
    )
    fig, ax = plt.subplots(figsize=(12.5, 6.4))
    fig.subplots_adjust(left=0.07, right=0.86, top=0.82, bottom=0.14)
    add_header(
        fig,
        f"{PARTY_LABELS[party_slug]} Language By Manifesto Year",
        "Mentions per 1,000 words for each word group, per manifesto. February and October 1974 averaged.",
    )
    for group, label in GROUPS:
        column = f"{group}_per_1000_words"
        ax.plot(sub["year"], sub[column], color=GROUP_COLOURS[group], linewidth=2.2,
                marker="o", markersize=3.5)
        ax.annotate(label, (sub["year"].iloc[-1], sub[column].iloc[-1]),
                    textcoords="offset points", xytext=(8, 0), fontsize=8.5,
                    color=GROUP_COLOURS[group], va="center",
                    annotation_clip=False)
    ax.set_xlabel("Manifesto year")
    ax.set_ylabel("Mentions per 1,000 words")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    add_footer(fig, method_footer(df))
    save_figure(
        fig, output_dir / f"nlp_{party_slug}_component_scores_by_manifesto_year.png"
    )


def chart_party_ranking(df: pd.DataFrame, output_dir: Path) -> None:
    grouped = df.groupby("party_slug").agg(
        n=("doc_id", "count"),
        long_term=("long_term_per_1000_words", "mean"),
        short_term=("short_term_per_1000_words", "mean"),
    )
    grouped = grouped[grouped["n"] >= 4].sort_values("long_term")

    fig, ax = plt.subplots(figsize=(11, 7))
    fig.subplots_adjust(left=0.14, right=0.96, top=0.84, bottom=0.12)
    add_header(
        fig,
        "Long-Term Language By Party",
        "Average long-term mentions per 1,000 words across each party's manifestos.\n"
        "Orange dots show the party's average short-term mentions for comparison.",
    )
    labels = [PARTY_LABELS.get(p, p) for p in grouped.index]
    ax.barh(labels, grouped["long_term"], color=TEAL, height=0.62)
    ax.scatter(grouped["short_term"], labels, color=ORANGE, s=55, zorder=3,
               label="Short-term mentions")
    for i, (_, row) in enumerate(grouped.iterrows()):
        ax.text(row["long_term"] + 0.08, i, f"n={int(row['n'])}", va="center",
                fontsize=8, color="#5d6c7a")
    ax.set_xlabel("Mentions per 1,000 words")
    ax.grid(axis="x", color="#d7d2c8", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    add_footer(fig, method_footer(df) + "\nParties with at least four manifestos.")
    save_figure(fig, output_dir / "nlp_party_ranking.png")


def chart_2024_scorecard(df: pd.DataFrame, output_dir: Path) -> None:
    sub = df[df["year"] == 2024].copy()
    if sub.empty:
        return
    columns = [f"{group}_per_1000_words" for group, _ in GROUPS]
    sub = sub.sort_values("long_term_per_1000_words", ascending=False)
    values = sub[columns].to_numpy()
    # shade each column by standing among the 2024 manifestos so groups with
    # very different base rates remain comparable; print the density itself
    ranks = pd.DataFrame(values).rank(ascending=True).to_numpy()
    shading = (ranks - 1) / (len(sub) - 1)

    fig, ax = plt.subplots(figsize=(10.5, 7.4))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.82, bottom=0.10)
    add_header(
        fig,
        "2024 Manifesto Language Profile",
        "Cells show mentions per 1,000 words. Shading compares parties within each column\n"
        "(darker = more of that language than other 2024 manifestos). Rows ordered by long-term mentions.",
    )
    ax.imshow(shading, cmap="BuGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(GROUPS)))
    ax.set_xticklabels([label for _, label in GROUPS], fontsize=9)
    ax.set_yticks(range(len(sub)))
    ax.set_yticklabels([PARTY_LABELS.get(p, p) for p in sub["party_slug"]], fontsize=9.5)
    for i in range(len(sub)):
        for j in range(len(GROUPS)):
            dark = shading[i, j] > 0.65
            ax.text(j, i, f"{values[i, j]:.1f}", ha="center", va="center",
                    fontsize=8, color="white" if dark else "#34424f")
    ax.set_xticks(np.arange(-0.5, len(GROUPS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(sub), 1), minor=True)
    ax.grid(which="minor", color="#f7f4ec", linewidth=2)
    ax.tick_params(which="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    add_footer(fig, method_footer(df))
    save_figure(fig, output_dir / "nlp_2024_scorecard.png")


def main() -> None:
    args = parse_args()
    apply_style()
    df = load_profiles(args.input_csv)
    periods = load_government_periods(args.government_periods)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    chart_decade_trends(df, args.output_dir)
    chart_two_party_year(df, periods, args.output_dir)
    chart_party_components(df, "labour", args.output_dir)
    chart_party_components(df, "conservative", args.output_dir)
    chart_party_ranking(df, args.output_dir)
    chart_2024_scorecard(df, args.output_dir)
    print(f"wrote figures to {args.output_dir}")


if __name__ == "__main__":
    main()
