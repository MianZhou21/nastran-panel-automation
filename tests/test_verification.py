"""Verification against closed-form solutions. Needs the MYSTRAN solver.

These check the answer, not just the input deck: if a modelling change breaks
the physics (loads, constraints, offsets, units), one of these fails.
"""
import math
from dataclasses import replace

import pytest

from panel_automation.config import PanelConfig
from panel_automation.model import build_buckling_model, build_static_model, write_deck
from panel_automation.pipeline import analyse_panel
from panel_automation.results import read_buckling_factors, read_static_results
from panel_automation.sections import blade_section
from panel_automation.solver import SolverError, run_solver

from conftest import requires_solver

pytestmark = requires_solver


def plate_buckling_stress(cfg: PanelConfig, k: float) -> float:
    """sigma_cr = k pi^2 E / (12 (1 - nu^2)) (t / b)^2 for a simply supported plate."""
    m = cfg.material
    return k * math.pi**2 * m.E / (12 * (1 - m.nu**2)) * (cfg.skin_thickness / cfg.width) ** 2


def test_square_plate_buckling_matches_theory(tmp_path):
    """Unstiffened square plate, all edges simply supported: k = 4."""
    cfg = PanelConfig(length=400.0, width=400.0, skin_thickness=2.0, n_stiffeners=0,
                      elements_x=20, elements_between_stiffeners=20, compressive_line_load=10.0)
    f06 = run_solver(write_deck(build_buckling_model(cfg), tmp_path / "plate.bdf")).with_suffix(".F06")
    load_factor = read_buckling_factors(f06)[0]
    fe_stress = load_factor * cfg.compressive_line_load / cfg.skin_thickness
    assert fe_stress == pytest.approx(plate_buckling_stress(cfg, k=4.0), rel=0.02)


def test_rectangular_plate_picks_correct_half_wave_count(tmp_path):
    """a/b = 2 buckles in two half-waves, also with k = 4."""
    cfg = PanelConfig(length=400.0, width=200.0, skin_thickness=1.5, n_stiffeners=0,
                      elements_x=32, elements_between_stiffeners=16, compressive_line_load=10.0)
    f06 = run_solver(write_deck(build_buckling_model(cfg), tmp_path / "rect.bdf")).with_suffix(".F06")
    fe_stress = read_buckling_factors(f06)[0] * cfg.compressive_line_load / cfg.skin_thickness
    assert fe_stress == pytest.approx(plate_buckling_stress(cfg, k=4.0), rel=0.03)


def test_uniform_compression_stress_state(tmp_path, small_panel):
    """Skin and stiffeners carry the same stress P / A_total, with no bending."""
    op2 = run_solver(write_deck(build_static_model(small_panel), tmp_path / "static.bdf"))
    res = read_static_results(op2)
    area = (small_panel.width * small_panel.skin_thickness
            + small_panel.n_stiffeners * blade_section(small_panel.stiffener_height,
                                                       small_panel.stiffener_thickness).A)
    sigma = small_panel.design_load / area
    assert res.max_skin_von_mises == pytest.approx(sigma, rel=1e-3)
    assert res.max_stiffener_stress == pytest.approx(sigma, rel=1e-3)
    assert res.max_displacement == pytest.approx(0.0, abs=1e-4)


def test_pressure_is_fully_reacted(tmp_path, small_panel):
    """Out-of-plane reactions balance the total pressure load p * a * b."""
    cfg = replace(small_panel, pressure=0.01)
    res = read_static_results(run_solver(write_deck(build_static_model(cfg), tmp_path / "p.bdf")))
    assert -res.reaction_force[2] == pytest.approx(cfg.pressure * cfg.length * cfg.width, rel=1e-4)


def test_stiffeners_increase_buckling_capacity(tmp_path):
    base = PanelConfig(elements_x=20, elements_between_stiffeners=4)
    rf = {n: analyse_panel(replace(base, n_stiffeners=n), tmp_path / f"n{n}", f"n{n}").rf_buckling
          for n in (2, 4)}
    assert rf[4] > rf[2]


def test_solver_error_is_reported(tmp_path):
    bad = tmp_path / "bad.bdf"
    bad.write_text("SOL 101\nCEND\nBEGIN BULK\nGRID,1,,0.,0.,0.\n")  # no ENDDATA
    with pytest.raises(SolverError):
        run_solver(bad)
