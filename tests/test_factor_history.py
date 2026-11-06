"""The historical fallback must depend only on the observed rows of one complete factor set."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import factor_history as fh

AREAS = ["Germany (DE)", "United Kingdom (UK)"]
UK = "United Kingdom (UK)"
DE = "Germany (DE)"


def observed_value(area: str, technology: str, year: int, month: int) -> float:
    base = 0.5 if area == UK else 1.5
    return base + 0.01 * (year - 2015) + 0.001 * month + (0.1 if technology == "Wind" else 0.0)


def row_status(area: str, year: int, month: int) -> str:
    return fh.STATUS_HISTORICAL_FALLBACK if fh.requires_fallback(area, year, month) else fh.STATUS_OBSERVED


def row_factor(area: str, technology: str, year: int, month: int) -> float:
    # A fallback row carries a value far outside the observed range, so any use of it is visible.
    if fh.requires_fallback(area, year, month):
        return 99.0
    return observed_value(area, technology, year, month)


def write_factor_set(root: Path, years=range(2015, 2026)) -> list[Path]:
    paths = []
    for year in years:
        for month in range(1, 13):
            frame = pd.DataFrame(
                {
                    "Area": AREAS,
                    "PV_Factor": [row_factor(a, "PV", year, month) for a in AREAS],
                    "Wind_Factor": [row_factor(a, "Wind", year, month) for a in AREAS],
                    "PV_Status": [row_status(a, year, month) for a in AREAS],
                    "Wind_Status": [row_status(a, year, month) for a in AREAS],
                }
            )
            path = fh.factor_file_path(root, year, month)
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            paths.append(path)
    return paths


def expected_mean(area: str, technology: str, month: int) -> float:
    last_year, last_month = fh.last_observed_month(area)
    dates, values = [], []
    for year in range(2015, 2026):
        if (year, month) <= (last_year, last_month):
            dates.append(pd.Timestamp(year=year, month=month, day=1))
            values.append(observed_value(area, technology, year, month))
    days = np.array([(date - dates[0]).days for date in dates], dtype=float) + 1.0
    return float(np.dot(values, days) / days.sum())


@pytest.fixture()
def factor_set(tmp_path):
    paths = write_factor_set(tmp_path)
    return tmp_path, paths


def test_fallback_does_not_depend_on_read_order(factor_set):
    _, paths = factor_set
    reference = fh.FactorHistory.from_files(sorted(paths), AREAS)
    for seed in range(5):
        shuffled = list(paths)
        random.Random(seed).shuffle(shuffled)
        history = fh.FactorHistory.from_files(shuffled, AREAS)
        for area in AREAS:
            for technology in ("PV", "Wind"):
                for month in range(1, 13):
                    assert history.fallback(area, technology, month) == reference.fallback(area, technology, month)


def test_recency_weights_do_not_depend_on_record_order():
    dates = [pd.Timestamp(2015, 1, 1), pd.Timestamp(2016, 1, 1), pd.Timestamp(2017, 1, 1)]
    values = [1.0, 2.0, 4.0]
    assert fh.recency_weighted_factor(dates, values) == fh.recency_weighted_factor(dates[::-1], values[::-1])


def test_fallback_matches_weighting_formula(factor_set):
    root, _ = factor_set
    history = fh.FactorHistory.from_directory(root, AREAS)
    for area in AREAS:
        assert history.fallback(area, "Wind", 3).value == pytest.approx(expected_mean(area, "Wind", 3), rel=1e-12)
        assert history.fallback(area, "Wind", 3).status == fh.STATUS_HISTORICAL_FALLBACK


def test_pre_2015_rows_are_never_used_as_inputs(factor_set):
    root, _ = factor_set
    reference = fh.FactorHistory.from_directory(root, AREAS).fallback(DE, "PV", 1)

    # Observed-looking pre-2015 records with an extreme value must not change the result.
    table_rows = []
    for year in range(1995, 2026):
        for month in range(1, 13):
            pre_2015 = year < 2015
            table_rows.append(
                {
                    "Area": DE,
                    "Technology": "PV",
                    "Year": year,
                    "Month": month,
                    "Factor": 1000.0 if pre_2015 else observed_value(DE, "PV", year, month),
                    "Status": fh.STATUS_OBSERVED,
                }
            )
    history = fh.FactorHistory(pd.DataFrame(table_rows))
    assert history.fallback(DE, "PV", 1).value == pytest.approx(reference.value, rel=1e-12)


def test_files_before_2015_are_not_read(factor_set):
    root, _ = factor_set
    reference = fh.FactorHistory.from_directory(root, AREAS).fallback(DE, "PV", 1)
    stale = fh.factor_file_path(root, 2010, 1)
    stale.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "Area": AREAS,
            "PV_Factor": [1000.0, 1000.0],
            "Wind_Factor": [1000.0, 1000.0],
            "PV_Status": [fh.STATUS_OBSERVED] * 2,
            "Wind_Status": [fh.STATUS_OBSERVED] * 2,
        }
    ).to_csv(stale, index=False)
    assert fh.FactorHistory.from_directory(root, AREAS).fallback(DE, "PV", 1) == reference


def test_fallback_rows_are_excluded_from_inputs(factor_set):
    root, _ = factor_set
    # write_factor_set gives UK rows after May 2021 a value of 99.
    result = fh.FactorHistory.from_directory(root, AREAS).fallback(UK, "Wind", 6)
    assert result.value < 2.0


def test_invalid_and_placeholder_rows_are_excluded_from_inputs():
    rows = []
    for year, factor, status in (
        (2015, 2.0, fh.STATUS_OBSERVED),
        (2016, 500.0, fh.STATUS_INVALID_OBSERVATION),
        (2017, 1.0, fh.STATUS_NO_OBSERVATION),
        (2018, 0.0, fh.STATUS_NO_MODELLED_FLEET),
    ):
        rows.append({"Area": DE, "Technology": "PV", "Year": year, "Month": 1, "Factor": factor, "Status": status})
    result = fh.FactorHistory(pd.DataFrame(rows)).fallback(DE, "PV", 1)
    assert result == fh.FallbackFactor(2.0, fh.STATUS_HISTORICAL_FALLBACK)


def test_each_area_uses_its_own_window():
    rows = []
    for year, month, factor in ((2021, 5, 1.0), (2021, 6, 50.0), (2025, 12, 50.0)):
        for area in AREAS:
            rows.append(
                {"Area": area, "Technology": "Wind", "Year": year, "Month": month, "Factor": factor, "Status": fh.STATUS_OBSERVED}
            )
    history = fh.FactorHistory(pd.DataFrame(rows))
    assert history.fallback(UK, "Wind", 6).status == fh.STATUS_NO_OBSERVATION
    assert history.fallback(UK, "Wind", 5).value == 1.0
    assert history.fallback(DE, "Wind", 6).value == 50.0
    assert history.fallback(DE, "Wind", 12).value == 50.0


def test_no_history_is_reported_with_a_status():
    rows = [{"Area": DE, "Technology": "PV", "Year": 2020, "Month": 1, "Factor": 2.0, "Status": fh.STATUS_OBSERVED}]
    result = fh.FactorHistory(pd.DataFrame(rows)).fallback(DE, "PV", 2)
    assert result == fh.FallbackFactor(fh.NO_HISTORY_FACTOR, fh.STATUS_NO_OBSERVATION)


def test_missing_file_raises(factor_set):
    root, paths = factor_set
    paths[17].unlink()
    with pytest.raises(fh.IncompleteFactorSetError):
        fh.FactorHistory.from_directory(root, AREAS)


def test_missing_folder_raises(tmp_path):
    with pytest.raises(fh.IncompleteFactorSetError):
        fh.FactorHistory.from_directory(tmp_path / "absent", AREAS)


def test_missing_area_raises(factor_set):
    root, _ = factor_set
    with pytest.raises(fh.IncompleteFactorSetError):
        fh.FactorHistory.from_directory(root, [*AREAS, "Atlantis (AT)"])


def test_missing_status_columns_raise(factor_set):
    root, paths = factor_set
    frame = pd.read_csv(paths[0])
    frame.drop(columns=["PV_Status", "Wind_Status"]).to_csv(paths[0], index=False)
    with pytest.raises(fh.IncompleteFactorSetError):
        fh.FactorHistory.from_directory(root, AREAS)


def test_nested_files_elsewhere_are_ignored(factor_set, tmp_path):
    root, _ = factor_set
    reference = fh.FactorHistory.from_directory(root, AREAS).fallback(DE, "PV", 1)
    stray = root / "2020" / "correction_factors" / "01_2020_pv_wind_country_factors.csv"
    stray.parent.mkdir(parents=True)
    pd.DataFrame({"Area": AREAS, "PV_Factor": [1000.0, 1000.0], "Wind_Factor": [1000.0, 1000.0]}).to_csv(stray, index=False)
    assert fh.FactorHistory.from_directory(root, AREAS).fallback(DE, "PV", 1) == reference


@pytest.mark.parametrize(
    "area,year,month,expected",
    [
        (DE, 2014, 12, True),
        (DE, 2015, 1, False),
        (DE, 2025, 12, False),
        (DE, 2026, 1, False),
        (UK, 2014, 12, True),
        (UK, 2021, 5, False),
        (UK, 2021, 6, True),
        (UK, 2025, 12, True),
    ],
)
def test_requires_fallback(area, year, month, expected):
    assert fh.requires_fallback(area, year, month) is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"area": DE, "year": 2020, "factor": 0.0, "modelled_energy": 0.0}, fh.STATUS_NO_MODELLED_FLEET),
        ({"area": DE, "year": 2020, "factor": 1.0, "modelled_energy": 0.0}, fh.STATUS_NO_MODELLED_FLEET),
        ({"area": DE, "year": 2020, "factor": 1.0, "modelled_energy": 10.0}, fh.STATUS_NO_OBSERVATION),
        ({"area": DE, "year": 2020, "factor": 1.00001, "modelled_energy": 10.0}, fh.STATUS_OBSERVED),
        (
            {"area": DE, "year": 2000, "factor": 0.8, "modelled_energy": 0.0, "fallback_status": fh.STATUS_HISTORICAL_FALLBACK},
            fh.STATUS_HISTORICAL_FALLBACK,
        ),
        (
            {"area": DE, "year": 2000, "factor": 1.0, "modelled_energy": 10.0, "fallback_status": fh.STATUS_NO_OBSERVATION},
            fh.STATUS_NO_OBSERVATION,
        ),
        (
            {"area": DE, "year": 2000, "factor": 1.0, "modelled_energy": 0.0, "fallback_status": fh.STATUS_NO_OBSERVATION},
            fh.STATUS_NO_MODELLED_FLEET,
        ),
    ],
)
def test_resolve_status(kwargs, expected):
    assert fh.resolve_status(technology="PV", month=1, **kwargs) == expected


def test_invalid_observation_period_is_applied(monkeypatch):
    entry = fh.InvalidObservation(DE, "PV", (2018, 10), (2019, 2), "test")
    monkeypatch.setattr(fh, "INVALID_OBSERVATIONS", (entry,))
    assert fh.resolve_status(DE, "PV", 2018, 10, 0.01, 10.0) == fh.STATUS_INVALID_OBSERVATION
    assert fh.resolve_status(DE, "PV", 2019, 3, 0.01, 10.0) == fh.STATUS_OBSERVED
    assert fh.resolve_status(DE, "Wind", 2018, 10, 0.01, 10.0) == fh.STATUS_OBSERVED


@pytest.mark.parametrize(
    "area,year,month,expected",
    [
        ("Netherlands (NL)", 2018, 9, False),
        ("Netherlands (NL)", 2018, 10, True),
        ("Netherlands (NL)", 2025, 12, True),
        ("Switzerland (CH)", 2019, 12, True),
        ("Switzerland (CH)", 2020, 1, False),
        ("Austria (AT)", 2018, 12, False),
        ("Austria (AT)", 2023, 12, True),
        ("Austria (AT)", 2024, 1, False),
        ("Belgium (BE)", 2015, 1, False),
    ],
)
def test_screened_pv_observations(area, year, month, expected):
    assert fh.is_invalid_observation(area, "PV", year, month) is expected
    assert fh.is_invalid_observation(area, "Wind", year, month) is False
