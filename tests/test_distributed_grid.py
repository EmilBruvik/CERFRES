"""The two PV grids must describe the fixed 2025 fleet, in every year."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pvlib")
pytest.importorskip("turbine_models")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import regenerate_distributed_grid as rdg
import weather_energy_monthly as wem


def area(scale: float, cells: list[tuple[int, int]] | None, weights: list[float] | None, source="population"):
    if cells is None:
        return rdg.AreaGeometry("X", scale, np.array([0]), np.array([0]), None, None, None, "none")
    y = np.array([c[0] for c in cells])
    x = np.array([c[1] for c in cells])
    return rdg.AreaGeometry("X", scale, y, x, y, x, np.array(weights, dtype=np.float64), source)


def test_residual_is_fleet_minus_farms_and_never_negative():
    assert wem.distributed_pv_residual(np.array([10.0, 2.0]), np.array([4.0, 3.0])).tolist() == [6.0, 0.0]


def test_residual_does_not_depend_on_asbuilt_fleet():
    """The 2025 fleet gives the same distributed output for a year with a small as-built fleet."""
    fleet_total = np.array([100.0])
    farms = fleet_total / 2.0
    residual = wem.distributed_pv_residual(fleet_total, farms)
    assert residual[0] == pytest.approx(50.0)


def test_grid_closes_on_fleet_total_per_area_and_hour():
    geometry = {
        "A": area(2.0, [(0, 0), (0, 1)], [0.25, 0.75]),
        "B": area(1.25, [(1, 1)], [1.0]),
    }
    fleet = np.array([[8.0, 5.0], [0.0, 10.0], [4.0, 0.0]])
    grid, dropped = rdg.build_distributed_grid(["A", "B"], fleet, geometry, (3, 2, 2))
    assert dropped == {}
    expected_a = fleet[:, 0] - fleet[:, 0] / 2.0
    expected_b = fleet[:, 1] - fleet[:, 1] / 1.25
    np.testing.assert_allclose(grid[:, 0, 0] + grid[:, 0, 1], expected_a, rtol=1e-6)
    np.testing.assert_allclose(grid[:, 1, 1], expected_b, rtol=1e-6)


def test_scale_of_one_gives_no_distributed_output():
    """A country missing from the distributed tracker, such as Belgium, has a scale of 1."""
    geometry = {"BE": area(1.0, [(0, 0)], [1.0], "farm_capacity")}
    fleet = np.array([[5.0], [7.0]])
    grid, dropped = rdg.build_distributed_grid(["BE"], fleet, geometry, (2, 1, 1))
    assert grid.sum() == 0.0
    assert dropped == {}


def test_area_without_weights_reports_dropped_energy():
    geometry = {"A": area(2.0, None, None)}
    grid, dropped = rdg.build_distributed_grid(["A"], np.array([[4.0]]), geometry, (1, 1, 1))
    assert grid.sum() == 0.0
    assert dropped == {"A": pytest.approx(2.0)}


def test_zones_sharing_cells_add_up():
    geometry = {
        "SE1": area(2.0, [(0, 0), (0, 1)], [0.5, 0.5]),
        "SE2": area(4.0, [(0, 0), (0, 1)], [0.5, 0.5]),
    }
    grid, _ = rdg.build_distributed_grid(["SE1", "SE2"], np.array([[4.0, 4.0]]), geometry, (1, 1, 2))
    assert grid.sum() == pytest.approx((4.0 - 2.0) + (4.0 - 1.0))


def test_select_pv_fleet_has_no_distributed_scale_for_a_missing_row():
    import pandas as pd

    main = pd.DataFrame(
        {
            "Country/Area": ["Belgium", "Germany"],
            "Status": ["operating", "operating"],
            "Latitude": [50.0, 52.0],
            "Longitude": [4.0, 10.0],
            "Capacity (MW)": [100.0, 100.0],
        }
    )
    distributed = pd.DataFrame(
        {"Country/Area": ["Germany"], "Status": ["operating"], "Capacity (MW)": [300.0]}
    )
    fleet, scale = wem.select_pv_fleet(main, distributed, "Belgium", "Belgium (BE)")
    assert len(fleet) == 1
    assert scale == 1.0
    _, scale_de = wem.select_pv_fleet(main, distributed, "Germany", "Germany (DE)")
    assert scale_de == pytest.approx(4.0)
