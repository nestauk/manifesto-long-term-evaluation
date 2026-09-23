#!/usr/bin/env python3
"""Generate NLP figures from the word-count density profiles.

Every chart plots mentions per 1,000 words from manifesto_nlp_profiles.csv.
There are no composite scores or weights anywhere: the only transformation of
the underlying counts is division by document length, and decade or party
averaging where labelled.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[2] / "outputs" / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MPLCONFIGDIR = CACHE_DIR / "mplconfig"
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIGDIR))

# matplotlib reads MPLCONFIGDIR at import time, so these imports come after it is set.
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = ROOT / "data" / "nlp_profiles.csv"
DEFAULT_COMMITMENTS = ROOT / "data" / "commitments.csv"
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
    parser.add_argument("--commitments-csv", type=Path, default=DEFAULT_COMMITMENTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--government-periods", type=Path, default=DEFAULT_GOVERNMENT_PERIODS)
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
    ax.plot(
        grouped.index,
        grouped["long_term_per_1000_words"],
        color=TEAL,
        linewidth=3,
        marker="o",
        markersize=6,
        label="Long-term markers",
    )
    ax.plot(
        grouped.index,
        grouped["short_term_per_1000_words"],
        color=ORANGE,
        linewidth=3,
        marker="o",
        markersize=6,
        label="Short-term markers",
    )
    ax.set_title("Long-term versus short-term language", loc="left", pad=12)
    for decade, count in counts.items():
        ax.annotate(
            f"n={count}",
            (decade, grouped.loc[decade, "long_term_per_1000_words"]),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7.5,
            color="#5d6c7a",
        )
    ax.legend(frameon=False, loc="upper left")

    ax = axes[1]
    ax.plot(
        grouped.index,
        grouped["definite_commitment_per_1000_words"],
        color=GROUP_COLOURS["definite_commitment"],
        linewidth=3,
        marker="o",
        markersize=6,
        label="Definite pledges (“we will …”)",
    )
    ax.plot(
        grouped.index,
        grouped["aspirational_per_1000_words"],
        color="#8a8157",
        linewidth=3,
        marker="o",
        markersize=6,
        label="Aspirational wording",
    )
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
        ax.plot(
            p["year"],
            p["long_term_per_1000_words"],
            color=colour,
            linewidth=2.5,
            marker="o",
            markersize=4.5,
            label=PARTY_LABELS[party],
        )
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
        .groupby("year", as_index=False)[[f"{group}_per_1000_words" for group, _ in GROUPS]]
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
        ax.plot(sub["year"], sub[column], color=GROUP_COLOURS[group], linewidth=2.2, marker="o", markersize=3.5)
        ax.annotate(
            label,
            (sub["year"].iloc[-1], sub[column].iloc[-1]),
            textcoords="offset points",
            xytext=(8, 0),
            fontsize=8.5,
            color=GROUP_COLOURS[group],
            va="center",
            annotation_clip=False,
        )
    ax.set_xlabel("Manifesto year")
    ax.set_ylabel("Mentions per 1,000 words")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#d7d2c8", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    add_footer(fig, method_footer(df))
    save_figure(fig, output_dir / f"nlp_{party_slug}_component_scores_by_manifesto_year.png")


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
    ax.scatter(grouped["short_term"], labels, color=ORANGE, s=55, zorder=3, label="Short-term mentions")
    for i, (_, row) in enumerate(grouped.iterrows()):
        ax.text(row["long_term"] + 0.08, i, f"n={int(row['n'])}", va="center", fontsize=8, color="#5d6c7a")
    ax.set_xlabel("Mentions per 1,000 words")
    ax.grid(axis="x", color="#d7d2c8", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    add_footer(fig, method_footer(df) + "\nParties with at least four manifestos.")
    save_figure(fig, output_dir / "nlp_party_ranking.png")


def chart_year_scorecard(df: pd.DataFrame, year: int, output_dir: Path) -> None:
    sub = df[df["year"] == year].copy()
    if sub.empty:
        return
    columns = [f"{group}_per_1000_words" for group, _ in GROUPS]
    sub = sub.sort_values("long_term_per_1000_words", ascending=False)
    values = sub[columns].to_numpy()
    # shade each column by standing among that year's manifestos so groups with
    # very different base rates remain comparable; print the density itself
    ranks = pd.DataFrame(values).rank(ascending=True).to_numpy()
    shading = (ranks - 1) / (len(sub) - 1)

    fig, ax = plt.subplots(figsize=(10.5, 7.4))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.82, bottom=0.10)
    add_header(
        fig,
        f"{year} Manifesto Language Profile",
        "Cells show mentions per 1,000 words. Shading compares parties within each column\n"
        f"(darker = more of that language than other {year} manifestos). Rows ordered by long-term mentions.",
    )
    ax.imshow(shading, cmap="BuGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(GROUPS)))
    ax.set_xticklabels([label for _, label in GROUPS], fontsize=9)
    ax.set_yticks(range(len(sub)))
    ax.set_yticklabels([PARTY_LABELS.get(p, p) for p in sub["party_slug"]], fontsize=9.5)
    for i in range(len(sub)):
        for j in range(len(GROUPS)):
            dark = shading[i, j] > 0.65
            ax.text(
                j, i, f"{values[i, j]:.1f}", ha="center", va="center", fontsize=8, color="white" if dark else "#34424f"
            )
    ax.set_xticks(np.arange(-0.5, len(GROUPS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(sub), 1), minor=True)
    ax.grid(which="minor", color="#f7f4ec", linewidth=2)
    ax.tick_params(which="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    add_footer(fig, method_footer(df))
    save_figure(fig, output_dir / f"nlp_{year}_scorecard.png")


RUBRIC_DIMENSIONS = [
    ("prevention", "Prevention"),
    ("tangible_investment", "Physical\ninvestment"),
    ("intangible_investment", "Knowledge\ninvestment"),
    ("risk_resilience", "Risk &\nresilience"),
    ("current_consumption", "Current\nconsumption"),
    ("constitutional_change", "Constitutional\nchange"),
]

# Short, plain-language descriptions of what each rubric dimension captures,
# used as the faded watermark behind each panel (the analogue of the word
# lists shown behind the word-count panels).
RUBRIC_DESCRIPTIONS = {
    "prevention": (
        "Acting early to stop future harm: early\n"
        "intervention, safeguarding, preparedness,\n"
        "mitigating risks before they land."
    ),
    "tangible_investment": (
        "Building durable physical assets: infrastructure,\n"
        "construction, buildings, networks, capital\n"
        "projects that outlast the spending."
    ),
    "intangible_investment": (
        "Building non-physical capacity: skills, training,\n"
        "research and development, education,\n"
        "institutional capability and know-how."
    ),
    "risk_resilience": (
        "Standing up to shocks: resilience, security,\n"
        "flood and coastal defence, energy security,\n"
        "adaptation and stability."
    ),
    "current_consumption": (
        "Near-term benefit: immediate transfers,\n"
        "service delivery, relief and consumption felt\n"
        "now rather than built for later."
    ),
    "constitutional_change": (
        "Lasting change to the constitutional order:\n"
        "franchise, devolution, treaty membership,\n"
        "the machinery and rules of the state."
    ),
}

# Nesta house style (matches manifestos/scripts/plot_fig2_nesta.py).
NESTA_BLUE = "#0000FF"
NESTA_RED = "#EB003B"
NESTA_PANEL_BG = "#E9EDF3"
NESTA_GRID = "#FFFFFF"
NESTA_AXIS_TEXT = "#646363"
NESTA_TITLE_TEXT = "#1F2333"
NESTA_BAR = "#2C4BD4"
NESTA_WATERMARK = "#B7C0D0"


def load_commitment_scores(commitments_path: Path, profiles: pd.DataFrame) -> pd.DataFrame:
    """Join LLM-scored commitments to their party and year via doc_id."""
    commitments = pd.read_csv(commitments_path)
    lookup = profiles[["doc_id", "party_slug", "year"]].drop_duplicates()
    return commitments.merge(lookup, on="doc_id", how="inner")


RUBRIC_MIN_COMMITMENTS = 25


def chart_year_rubric_scorecard(commitments: pd.DataFrame, year: int, output_dir: Path) -> None:
    columns = [dim for dim, _ in RUBRIC_DIMENSIONS]
    sub = commitments[commitments["year"] == year]
    if sub.empty:
        return
    # share of a manifesto's commitments that score 3 or 4 on each dimension,
    # i.e. how often the dimension is a central feature rather than incidental.
    high = sub[columns] >= 3
    grouped = high.groupby(sub["party_slug"]).mean() * 100
    grouped["n"] = sub.groupby("party_slug").size()
    # drop manifestos with too few scored commitments to compare fairly (this
    # removes Sinn Féin's 6-commitment 2019 manifesto).
    grouped = grouped[grouped["n"] >= RUBRIC_MIN_COMMITMENTS]
    grouped["overall"] = grouped[columns].mean(axis=1)
    grouped = grouped.sort_values("overall", ascending=False)
    values = grouped[columns].to_numpy()
    # absolute colour scale: 0% to the highest cell, so a given share reads the
    # same shade in any column and across charts.
    vmax = float(np.ceil(values.max() / 5) * 5)

    fig, ax = plt.subplots(figsize=(11, 7.0))
    fig.subplots_adjust(left=0.18, right=0.97, top=0.80, bottom=0.12)
    add_header(
        fig,
        f"{year} Manifesto Policy-Typology Profile",
        "Share of each manifesto's commitments scoring 3 or 4 (out of 4) on each policy dimension.\n"
        "Absolute colour scale; darker = a larger share. Rows ordered by the mean share across dimensions.",
    )
    ax.imshow(values, cmap="BuPu", vmin=0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(RUBRIC_DIMENSIONS)))
    ax.set_xticklabels([label for _, label in RUBRIC_DIMENSIONS], fontsize=8.5)
    ax.set_yticks(range(len(grouped)))
    ax.set_yticklabels(
        [
            f"{PARTY_LABELS.get(p, p)}  (n={int(row.n)})"
            for p, row in zip(grouped.index, grouped.itertuples(), strict=True)
        ],
        fontsize=9.5,
    )
    for i in range(len(grouped)):
        for j in range(len(RUBRIC_DIMENSIONS)):
            dark = values[i, j] > 0.65 * vmax
            ax.text(
                j, i, f"{values[i, j]:.0f}%", ha="center", va="center", fontsize=8, color="white" if dark else "#34424f"
            )
    ax.set_xticks(np.arange(-0.5, len(RUBRIC_DIMENSIONS), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(grouped), 1), minor=True)
    ax.grid(which="minor", color="#f7f4ec", linewidth=2)
    ax.tick_params(which="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    add_footer(
        fig,
        "Method: an LLM scores each policy commitment 0–4 on six policy-typology dimensions; "
        "cells are the share scoring 3 or 4.\n"
        f"n = commitments scored per manifesto. Manifestos with fewer than {RUBRIC_MIN_COMMITMENTS} "
        f"scored commitments are excluded. {len(sub)} commitments in {year}.",
    )
    save_figure(fig, output_dir / f"rubric_{year}_scorecard.png")


def _rubric_shares(commitments: pd.DataFrame, year: int) -> pd.DataFrame:
    """Per-manifesto share (%) of commitments scoring 3 or 4 on each dimension."""
    columns = [dim for dim, _ in RUBRIC_DIMENSIONS]
    sub = commitments[commitments["year"] == year]
    if sub.empty:
        return sub
    high = sub[columns] >= 3
    shares = high.groupby(sub["party_slug"]).mean() * 100
    shares["n"] = sub.groupby("party_slug").size()
    shares = shares[shares["n"] >= RUBRIC_MIN_COMMITMENTS]
    shares["overall"] = shares[columns].mean(axis=1)
    return shares.sort_values("overall", ascending=False)


def chart_year_rubric_panels(commitments: pd.DataFrame, year: int, output_dir: Path) -> None:
    """Small-multiples in Nesta house style: one panel per policy dimension,
    a horizontal bar per party. Mirrors the word-count components figure."""
    shares = _rubric_shares(commitments, year)
    if shares.empty:
        return
    columns = [dim for dim, _ in RUBRIC_DIMENSIONS]
    parties = list(shares.index)
    party_labels = [PARTY_LABELS.get(p, p) for p in parties]
    y = np.arange(len(parties))
    vmax = float(np.ceil(shares[columns].to_numpy().max() / 5) * 5)
    n_commitments = int(shares["n"].sum())

    rc = {
        "figure.facecolor": NESTA_PANEL_BG,
        "axes.facecolor": NESTA_PANEL_BG,
        "savefig.facecolor": NESTA_PANEL_BG,
        "font.family": "sans-serif",
        "font.sans-serif": ["Averta", "Helvetica", "Helvetica Neue", "Arial"],
        "text.color": NESTA_TITLE_TEXT,
        "axes.labelcolor": NESTA_AXIS_TEXT,
        "xtick.color": NESTA_AXIS_TEXT,
        "ytick.color": NESTA_TITLE_TEXT,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.spines.bottom": False,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
    }
    with plt.rc_context(rc):
        fig, axes = plt.subplots(2, 3, figsize=(13, 7.8), sharex=True, sharey=True)
        fig.subplots_adjust(left=0.13, right=0.97, top=0.80, bottom=0.13, wspace=0.12, hspace=0.42)
        for ax, (dim, label) in zip(axes.flat, RUBRIC_DIMENSIONS, strict=True):
            ax.text(
                0.97,
                0.5,
                RUBRIC_DESCRIPTIONS[dim],
                transform=ax.transAxes,
                ha="right",
                va="center",
                fontsize=7.2,
                color=NESTA_WATERMARK,
                zorder=0,
                linespacing=1.5,
            )
            ax.barh(y, shares[dim].to_numpy(), color=NESTA_BAR, height=0.66, zorder=3)
            ax.set_title(label.replace("\n", " "), loc="left", color=NESTA_TITLE_TEXT, fontsize=12, pad=8)
            ax.set_xlim(0, vmax)
            ax.set_ylim(-0.7, len(parties) - 0.3)
            ax.invert_yaxis()
            ax.grid(axis="x", color=NESTA_GRID, linewidth=1.2, zorder=1)
            ax.set_axisbelow(True)
            ax.tick_params(labelbottom=True)
        for ax in axes[:, 0]:
            ax.set_yticks(y)
            ax.set_yticklabels(party_labels, fontsize=9)
        for ax in axes[1, :]:
            ax.set_xlabel("% of commitments scoring 3 or 4")

        fig.suptitle(
            f"How {year} manifestos score against the policy typology",
            x=0.012,
            y=0.965,
            ha="left",
            fontsize=18,
            fontweight="bold",
            color=NESTA_TITLE_TEXT,
        )
        fig.text(
            0.012,
            0.895,
            "Share of each manifesto's commitments scoring 3 or 4 (out of 4) on each policy dimension. "
            "The faded text\nbehind each panel describes what that dimension captures.",
            fontsize=10.5,
            color=NESTA_AXIS_TEXT,
        )
        fig.text(
            0.86,
            0.952,
            "LLM scored",
            fontsize=11,
            fontweight="bold",
            color=NESTA_BLUE,
            ha="center",
            va="center",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#D6E0F5", edgecolor="none"),
        )
        fig.text(
            0.012,
            0.02,
            "Source: UK manifesto corpus, LLM policy-typology scorer. An LLM scores each policy commitment 0-4 on six "
            "dimensions; bars show the share scoring 3 or 4.\n"
            f"General election {year}. "
            f"Manifestos with fewer than {RUBRIC_MIN_COMMITMENTS} scored commitments excluded. "
            f"{n_commitments} commitments across {len(parties)} manifestos.",
            fontsize=7.5,
            color=NESTA_AXIS_TEXT,
            va="bottom",
        )
        save_figure(fig, output_dir / f"rubric_{year}_panels.png")


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
    chart_year_scorecard(df, 2019, args.output_dir)
    chart_year_scorecard(df, 2024, args.output_dir)

    if args.commitments_csv.exists():
        commitments = load_commitment_scores(args.commitments_csv, df)
        chart_year_rubric_scorecard(commitments, 2019, args.output_dir)
        chart_year_rubric_panels(commitments, 2019, args.output_dir)
    print(f"wrote figures to {args.output_dir}")


if __name__ == "__main__":
    main()
