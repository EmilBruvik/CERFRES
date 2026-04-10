#!/usr/bin/env python3
"""
Validation tests for scripts/weather_energy_monthly.py.
Checks syntax and verifies key implementation patterns without running the full pipeline.
"""

import ast
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "scripts" / "weather_energy_monthly.py"


def test_syntax():
    """Test that the script has valid Python syntax."""
    with open(SCRIPT) as f:
        code = f.read()
    try:
        ast.parse(code)
        print("✓ Syntax check passed")
        return True
    except SyntaxError as e:
        print(f"✗ Syntax error: {e}")
        return False


def test_core_features():
    """Test that key implementation patterns are present."""
    with open(SCRIPT) as f:
        code = f.read()

    ok = True

    # Per-farm data collection
    if "return_farm_data" in code:
        print("✓ return_farm_data parameter found")
    else:
        print("✗ return_farm_data parameter not found")
        ok = False

    # h5netcdf engine
    if 'engine="h5netcdf"' in code:
        print("✓ h5netcdf engine usage found")
    else:
        print("✗ h5netcdf engine usage not found")
        ok = False

    # tempfile for atomic writes
    if "import tempfile" in code or "from tempfile import" in code:
        print("✓ tempfile import found for atomic writes")
    else:
        print("✗ tempfile import not found")
        ok = False

    # config import
    if "import config" in code:
        print("✓ config module imported")
    else:
        print("✗ config module not imported")
        ok = False

    return ok


def test_safe_start_year_handling():
    """Test that start_year is handled safely (no unsafe NaN casting)."""
    with open(SCRIPT) as f:
        code = f.read()

    ok = True

    if 'pd.to_numeric(df_country["Start year"], errors="coerce").to_numpy()' in code:
        print("✓ Safe start_year parsing found")
    else:
        print("✗ Safe start_year parsing not found")
        ok = False

    if "asbuilt_mask = np.isfinite(start_year)" in code:
        print("✓ asbuilt_mask computed on float values")
    else:
        print("✗ asbuilt_mask not computed on float values")
        ok = False

    return ok


if __name__ == "__main__":
    print("Testing weather_energy_monthly.py...\n")

    results = [
        test_syntax(),
        test_core_features(),
        test_safe_start_year_handling(),
    ]

    print("\n" + "=" * 50)
    if all(results):
        print("All tests passed!")
        sys.exit(0)
    else:
        print("Some tests failed!")
        sys.exit(1)
