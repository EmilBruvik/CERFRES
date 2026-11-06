"""Correction-factor status values and the historical fallback.

The fallback for a month without usable ENTSO-E data is a recency-weighted mean of the
*observed* factors of the same area, technology and calendar month. The inputs come from
one fixed, complete factor set, so the result does not depend on the order in which
months are simulated or on which other files happen to be on disk.

This module only depends on numpy and pandas so it can be imported and tested without
the weather and power-model stack.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

STATUS_OBSERVED = "observed"
STATUS_HISTORICAL_FALLBACK = "historical_fallback"
STATUS_NO_OBSERVATION = "no_observation"
STATUS_NO_MODELLED_FLEET = "no_modelled_fleet"
STATUS_INVALID_OBSERVATION = "invalid_observation"
ALL_STATUSES = (
    STATUS_OBSERVED,
    STATUS_HISTORICAL_FALLBACK,
    STATUS_NO_OBSERVATION,
    STATUS_NO_MODELLED_FLEET,
    STATUS_INVALID_OBSERVATION,
)

# technology -> (factor column, status column) in the factor files
TECHNOLOGY_COLUMNS = {
    "PV": ("PV_Factor", "PV_Status"),
    "Wind": ("Wind_Factor", "Wind_Status"),
}
FACTOR_FILE_COLUMNS = ["Area", "PV_Factor", "Wind_Factor", "PV_Status", "Wind_Status"]

FIRST_OBSERVED_MONTH = (2015, 1)
LAST_OBSERVED_MONTH = (2025, 12)
# ENTSO-E stopped publishing per-type generation for Great Britain after May 2021.
LAST_OBSERVED_MONTH_BY_AREA = {"United Kingdom (UK)": (2021, 5)}

# Placeholder returned when an area has no observed factor for a calendar month.
NO_HISTORY_FACTOR = 1.0

_FACTOR_FILE_NAME = re.compile(r"^(\d{2})_(\d{4})_pv_wind_country_factors\.csv$")


@dataclass(frozen=True)
class InvalidObservation:
    """A period where ENTSO-E exists but does not describe the area's generation."""

    area: str
    technology: str
    first_month: tuple[int, int]
    last_month: tuple[int, int]
    reason: str


# Evidence for each entry is in CHANGELOG.md and in the factor QA table.
INVALID_OBSERVATIONS: tuple[InvalidObservation, ...] = (
    InvalidObservation(
        "Netherlands (NL)", "PV", (2018, 10), (2025, 12),
        "ENTSO-E reports about 0.5 TWh per year on up to 29 GW of its own installed capacity (0.1-0.4 %).",
    ),
    InvalidObservation(
        "Switzerland (CH)", "PV", (2015, 1), (2019, 12),
        "ENTSO-E generation rises 5.7 times from 2019 to 2020, starting in January 2020.",
    ),
    InvalidObservation(
        "Austria (AT)", "PV", (2019, 1), (2023, 12),
        "ENTSO-E generation halves in 2019 on flat capacity (4.5-6.9 % in 2019-2022) and steps up in "
        "April 2023 and January 2024.",
    ),
)


class IncompleteFactorSetError(RuntimeError):
    """The factor set cannot be used because files, areas or status columns are missing."""


@dataclass(frozen=True)
class FallbackFactor:
    value: float
    status: str


def last_observed_month(area: str) -> tuple[int, int]:
    return LAST_OBSERVED_MONTH_BY_AREA.get(area, LAST_OBSERVED_MONTH)


def requires_fallback(area: str, year: int, month: int) -> bool:
    """True when a month must use the fallback instead of ENTSO-E.

    Months after December 2025 are not fallback months by default: they can be calibrated
    directly once ENTSO-E data exist. The fallback window itself stays fixed.
    """
    if (year, month) < FIRST_OBSERVED_MONTH:
        return True
    cutoff = LAST_OBSERVED_MONTH_BY_AREA.get(area)
    return cutoff is not None and (year, month) > cutoff


def is_invalid_observation(area: str, technology: str, year: int, month: int) -> bool:
    return any(
        entry.area == area
        and entry.technology == technology
        and entry.first_month <= (year, month) <= entry.last_month
        for entry in INVALID_OBSERVATIONS
    )


def resolve_status(
    area: str,
    technology: str,
    year: int,
    month: int,
    factor: float,
    modelled_energy: float,
    fallback_status: str | None = None,
) -> str:
    """Status of one factor. `modelled_energy` refers to the as-built fleet.

    A fallback month keeps `historical_fallback` even when the as-built fleet of that year
    is empty, because the value still describes the area's later fleet. The exact value 1.0
    only arises as a placeholder in the factor calculation, so it marks a missing observation.
    """
    no_fleet = not modelled_energy > 0.0
    if requires_fallback(area, year, month):
        if fallback_status == STATUS_HISTORICAL_FALLBACK:
            return STATUS_HISTORICAL_FALLBACK
        return STATUS_NO_MODELLED_FLEET if no_fleet else STATUS_NO_OBSERVATION
    if no_fleet:
        return STATUS_NO_MODELLED_FLEET
    if is_invalid_observation(area, technology, year, month):
        return STATUS_INVALID_OBSERVATION
    if factor == NO_HISTORY_FACTOR:
        return STATUS_NO_OBSERVATION
    return STATUS_OBSERVED


def recency_weighted_factor(dates: Sequence[pd.Timestamp], values: Sequence[float]) -> float:
    """Weight each value by days since the earliest record, plus one."""
    if len(dates) != len(values):
        raise ValueError("dates and values must have the same length")
    if len(values) == 0:
        raise ValueError("at least one record is required")
    order = np.argsort(pd.to_datetime(list(dates)).to_numpy())
    when = pd.to_datetime(list(dates))[order]
    vals = np.asarray(values, dtype=np.float64)[order]
    weights = (when - when.min()).days.to_numpy(dtype=np.float64) + 1.0
    return float(np.dot(vals, weights) / weights.sum())


def observed_months() -> list[tuple[int, int]]:
    first_year, first_month = FIRST_OBSERVED_MONTH
    last_year, last_month = LAST_OBSERVED_MONTH
    months = []
    for year in range(first_year, last_year + 1):
        for month in range(1, 13):
            if (first_year, first_month) <= (year, month) <= (last_year, last_month):
                months.append((year, month))
    return months


def factor_file_path(root: Path, year: int, month: int) -> Path:
    return Path(root) / str(year) / f"{month:02d}_{year}_pv_wind_country_factors.csv"


class FactorHistory:
    """Observed factors of one complete factor set."""

    def __init__(self, table: pd.DataFrame):
        """`table` has columns Area, Technology, Year, Month, Factor, Status."""
        required = {"Area", "Technology", "Year", "Month", "Factor", "Status"}
        missing = required - set(table.columns)
        if missing:
            raise IncompleteFactorSetError(f"Factor table lacks columns: {sorted(missing)}")
        unknown = set(table["Status"]) - set(ALL_STATUSES)
        if unknown:
            raise IncompleteFactorSetError(f"Unknown status values: {sorted(unknown)}")
        self._usable = self._select_usable_rows(table)
        self._cache: dict[tuple[str, str, int], FallbackFactor] = {}

    @staticmethod
    def _select_usable_rows(table: pd.DataFrame) -> pd.DataFrame:
        """Only observed rows inside each area's own observation window are usable."""
        usable = table[table["Status"] == STATUS_OBSERVED]
        usable = usable[np.isfinite(pd.to_numeric(usable["Factor"], errors="coerce"))]
        keep = [
            FIRST_OBSERVED_MONTH <= (year, month) <= last_observed_month(area)
            for area, year, month in zip(usable["Area"], usable["Year"], usable["Month"])
        ]
        return usable[np.asarray(keep, dtype=bool)].copy()

    @classmethod
    def from_files(cls, paths: Iterable[Path], areas: Sequence[str]) -> "FactorHistory":
        """Build from explicit monthly factor files. Raises if the set is not complete."""
        seen: dict[tuple[int, int], Path] = {}
        for raw_path in paths:
            path = Path(raw_path)
            match = _FACTOR_FILE_NAME.match(path.name)
            if match is None:
                raise IncompleteFactorSetError(f"Unexpected factor file name: {path}")
            key = (int(match.group(2)), int(match.group(1)))
            if key in seen:
                raise IncompleteFactorSetError(f"Duplicate factor files for {key}: {seen[key]}, {path}")
            seen[key] = path

        missing_months = [key for key in observed_months() if key not in seen]
        if missing_months:
            raise IncompleteFactorSetError(
                f"Factor set lacks {len(missing_months)} months, first: {missing_months[:5]}"
            )

        frames = []
        for (year, month) in observed_months():
            path = seen[(year, month)]
            frame = pd.read_csv(path)
            absent_columns = set(FACTOR_FILE_COLUMNS) - set(frame.columns)
            if absent_columns:
                raise IncompleteFactorSetError(f"{path} lacks columns {sorted(absent_columns)}")
            absent_areas = set(areas) - set(frame["Area"])
            if absent_areas:
                raise IncompleteFactorSetError(f"{path} lacks areas {sorted(absent_areas)}")
            for technology, (factor_col, status_col) in TECHNOLOGY_COLUMNS.items():
                frames.append(
                    pd.DataFrame(
                        {
                            "Area": frame["Area"],
                            "Technology": technology,
                            "Year": year,
                            "Month": month,
                            "Factor": frame[factor_col],
                            "Status": frame[status_col],
                        }
                    )
                )
        return cls(pd.concat(frames, ignore_index=True))

    @classmethod
    def from_directory(cls, root: Path, areas: Sequence[str]) -> "FactorHistory":
        """Read {root}/{year}/{mm}_{year}_pv_wind_country_factors.csv, for 2015 onward only."""
        root = Path(root)
        if not root.is_dir():
            raise IncompleteFactorSetError(f"Factor set folder does not exist: {root}")
        paths = [factor_file_path(root, year, month) for (year, month) in observed_months()]
        absent = [path for path in paths if not path.is_file()]
        if absent:
            raise IncompleteFactorSetError(
                f"Factor set {root} lacks {len(absent)} files, first: {absent[0]}"
            )
        return cls.from_files(paths, areas)

    def fallback(self, area: str, technology: str, month: int) -> FallbackFactor:
        key = (area, technology, month)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        rows = self._usable[
            (self._usable["Area"] == area)
            & (self._usable["Technology"] == technology)
            & (self._usable["Month"] == month)
        ]
        if rows.empty:
            result = FallbackFactor(NO_HISTORY_FACTOR, STATUS_NO_OBSERVATION)
        else:
            dates = pd.to_datetime(dict(year=rows["Year"], month=rows["Month"], day=1))
            result = FallbackFactor(
                recency_weighted_factor(list(dates), rows["Factor"].to_numpy(dtype=np.float64)),
                STATUS_HISTORICAL_FALLBACK,
            )
        self._cache[key] = result
        return result
