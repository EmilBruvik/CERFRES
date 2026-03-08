#!/usr/bin/env python3
# coding: utf-8

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import os

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import functions

env_bin = os.path.join(sys.prefix, "bin")
if env_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = env_bin + os.pathsep + os.environ.get("PATH", "")

# Add TinyTeX to PATH for LaTeX rendering (text.usetex: True)
tinytex_bin = os.path.expanduser("~/.TinyTeX/bin/x86_64-linux")
if os.path.isdir(tinytex_bin) and tinytex_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = tinytex_bin + os.pathsep + os.environ.get("PATH", "")

#parent directory to path to import functions
sys.path.append(os.path.abspath('..'))

style_path = Path('custom_latex_style.mplstyle')
if style_path.exists():
    plt.style.use(str(style_path))


def read_tracker_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8", "latin1", "cp1252"):
        try:
            return pd.read_csv(path, sep=";", decimal=",", encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(
        path,
        sep=";",
        decimal=",",
        encoding="latin1",
        encoding_errors="replace",
        low_memory=False,
    )


def load_wind_farms(main_path: Path, below_threshold_path: Path) -> pd.DataFrame:
    main_df = read_tracker_csv(main_path)
    below_df = read_tracker_csv(below_threshold_path)
    return pd.concat([main_df, below_df], ignore_index=True)


def map_turbine_models(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Start year"] = pd.to_numeric(out.get("Start year"), errors="coerce")
    out["Installation Type"] = out.get("Installation Type", "Unknown")

    valid = out["Start year"].notna()
    out = out.loc[valid].copy()
    out["Start year"] = out["Start year"].astype(int)

    mapped = out.apply(
        lambda row: functions.map_turbine_model(
            int(row["Start year"]),
            row["Installation Type"],
        ),
        axis=1,
    )

    out["Mapped_Turbine_Model"] = mapped.apply(lambda x: x[0])
    out["Mapped_Hub_Height_m"] = mapped.apply(lambda x: x[1])
    out["Mapped_Turbine_Label"] = out.apply(
        lambda row: f"{row['Mapped_Turbine_Model']} ({row['Mapped_Hub_Height_m']:.0f} m)",
        axis=1,
    )
    return out


def plot_turbine_type_histogram(df: pd.DataFrame, top_n: int, out_path: Path) -> None:
    counts = df["Mapped_Turbine_Label"].value_counts().head(top_n)

    plt.figure(figsize=(12, 7))
    ax = counts.sort_values().plot(kind="barh", color="#1f77b4", edgecolor="black")
    plt.xlabel("Number of farms")
    ax.set_ylabel("")
    # plt.title(f"Top {len(counts)} most common mapped turbine models")
    plt.grid(axis="x", linestyle=":", alpha=0.5)
    plt.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close() 


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a histogram-style plot of most common mapped wind turbine types."
    )
    parser.add_argument(
        "--main-csv",
        type=Path,
        default=Path("/Data/gfi/vindenergi/nab015/Wind_data/Global-Wind-Power-Tracker-February-2026.csv"),
    )
    parser.add_argument(
        "--below-threshold-csv",
        type=Path,
        default=Path("/Data/gfi/vindenergi/nab015/Wind_data/Global-Wind-Power-Tracker-February-2026-Below_Threshold.csv"),
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of most common mapped turbine models to show.",
    )
    parser.add_argument(
        "--output-figure",
        type=Path,
        default=Path("/Data/gfi/vindenergi/nab015/figures/turbine_type_histogram.pdf"),
    )
    parser.add_argument(
        "--output-table",
        type=Path,
        default=Path("/Data/gfi/vindenergi/nab015/figures/turbine_type_counts.csv"),
        help="Optional CSV export of all mapped turbine model counts.",
    )
    args = parser.parse_args()

    farms = load_wind_farms(args.main_csv, args.below_threshold_csv)
    mapped = map_turbine_models(farms)

    model_counts = (
        mapped["Mapped_Turbine_Label"]
        .value_counts()
        .rename_axis("Mapped_Turbine_Label")
        .reset_index(name="Count")
    )
    args.output_table.parent.mkdir(parents=True, exist_ok=True)
    model_counts.to_csv(args.output_table, index=False)

    plot_turbine_type_histogram(mapped, args.top_n, args.output_figure)

    print(f"Saved figure: {args.output_figure}")
    print(f"Saved table: {args.output_table}")


if __name__ == "__main__":
    main()
