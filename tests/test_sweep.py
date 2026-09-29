"""Tests for the design-sweep logic. No solver needed: results are made up."""
import csv
from dataclasses import replace

import pytest

from panel_automation.config import PanelConfig
from panel_automation.pipeline import RF_BUCKLING_REQUIRED, PanelSummary
from panel_automation.sweep import SweepResult, lightest_passing, plot_trade_study, write_csv


def make_result(t: float, n: int, h: float, mass: float, rf_buckling: float,
                rf_strength: float = 3.0) -> SweepResult:
    cfg = replace(PanelConfig(), skin_thickness=t, n_stiffeners=n, stiffener_height=h)
    summary = PanelSummary(
        skin_thickness=t, n_stiffeners=n, stiffener_height=h, mass_kg=mass,
        max_displacement=0.0, max_skin_von_mises=50.0, max_stiffener_stress=50.0,
        rf_strength=rf_strength, rf_buckling=rf_buckling,
    )
    return SweepResult(cfg=cfg, summary=summary, name=f"t{t}_n{n}_h{h}")


@pytest.fixture
def results() -> list[SweepResult]:
    return [
        make_result(1.2, 2, 20.0, mass=0.80, rf_buckling=0.60),  # lightest, fails buckling
        make_result(1.2, 4, 20.0, mass=0.90, rf_buckling=1.30),  # lightest passing
        make_result(1.6, 3, 25.0, mass=1.10, rf_buckling=1.80),
        make_result(2.0, 3, 25.0, mass=1.30, rf_buckling=2.50),
        make_result(1.2, 5, 25.0, mass=0.85, rf_buckling=2.00, rf_strength=0.9),  # fails strength
    ]


# --- pass / fail rule ------------------------------------------------------------

def test_buckling_needs_margin_above_one():
    """RF just above 1.0 is inside the mesh error, so it must not count as a pass."""
    assert not make_result(1.2, 3, 25.0, 1.0, rf_buckling=1.02).summary.passes
    assert make_result(1.2, 3, 25.0, 1.0, rf_buckling=RF_BUCKLING_REQUIRED).summary.passes


def test_strength_failure_fails_the_design():
    assert not make_result(1.2, 3, 25.0, 1.0, rf_buckling=2.0, rf_strength=0.99).summary.passes


# --- lightest design -------------------------------------------------------------

def test_lightest_passing_ignores_lighter_failing_designs(results):
    best = lightest_passing(results)
    assert best is not None
    assert (best.cfg.skin_thickness, best.cfg.n_stiffeners, best.cfg.stiffener_height) == (1.2, 4, 20.0)


def test_lightest_passing_returns_none_when_nothing_passes():
    failing = [make_result(1.2, 2, 20.0, 0.8, 0.5), make_result(1.6, 2, 20.0, 1.0, 0.9)]
    assert lightest_passing(failing) is None


def test_lightest_passing_empty_list():
    assert lightest_passing([]) is None


# --- outputs ---------------------------------------------------------------------

def test_csv_has_one_row_per_design_with_inputs_and_verdict(tmp_path, results):
    path = tmp_path / "trade_study.csv"
    write_csv(results, path)
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(results)
    assert {"skin_thickness", "n_stiffeners", "stiffener_height", "mass_kg",
            "rf_buckling", "rf_strength", "passes"} <= set(rows[0])
    assert [row["passes"] for row in rows] == [str(r.summary.passes) for r in results]
    assert float(rows[1]["stiffener_height"]) == 20.0


def test_trade_study_plot_is_written(tmp_path, results):
    path = tmp_path / "trade_study.png"
    plot_trade_study(results, path)
    assert path.exists() and path.stat().st_size > 10_000


def test_plot_rejects_more_stiffener_counts_than_colours(tmp_path):
    too_many = [make_result(1.2, n, 20.0, 1.0, 1.5) for n in range(1, 7)]
    with pytest.raises(ValueError):
        plot_trade_study(too_many, tmp_path / "x.png")
