"""Unit tests for input validation, section properties and deck generation.

These run without a solver: they check the model that is written, not the answer.
"""
import math

import pytest
from pyNastran.bdf.bdf import read_bdf

from panel_automation.config import PanelConfig
from panel_automation.model import (BAR_ID_OFFSET, build_buckling_model, build_static_model,
                                    end_load_distribution, node_id, panel_mass, write_deck)
from panel_automation.sections import blade_section


# --- configuration ---------------------------------------------------------------

@pytest.mark.parametrize("field, value", [
    ("length", 0.0), ("width", -1.0), ("skin_thickness", 0.0),
    ("n_stiffeners", -1), ("elements_x", 0), ("compressive_line_load", -5.0),
])
def test_invalid_config_is_rejected(field, value):
    with pytest.raises(ValueError):
        PanelConfig(**{field: value})


def test_stiffener_positions_are_evenly_spaced():
    cfg = PanelConfig(width=400.0, n_stiffeners=3)
    assert cfg.stiffener_y_positions == pytest.approx([100.0, 200.0, 300.0])


# --- section properties ----------------------------------------------------------

def test_blade_section_matches_hand_calculation():
    sec = blade_section(height=25.0, thickness=2.0)
    assert sec.A == pytest.approx(50.0)
    assert sec.I1 == pytest.approx(2.0 * 25.0**3 / 12)  # stiff direction, out of plane
    assert sec.I2 == pytest.approx(25.0 * 2.0**3 / 12)
    assert sec.J == pytest.approx(25.0 * 2.0**3 / 3 * (1 - 0.63 * 2.0 / 25.0))


def test_blade_section_rejects_bad_dimensions():
    with pytest.raises(ValueError):
        blade_section(0.0, 2.0)


# --- mesh and cards --------------------------------------------------------------

def test_mesh_counts(small_panel):
    model = build_static_model(small_panel)
    nx, ny = small_panel.elements_x, small_panel.elements_y
    quads = [e for e in model.elements.values() if e.type == "CQUAD4"]
    bars = [e for e in model.elements.values() if e.type == "CBAR"]
    assert len(model.nodes) == (nx + 1) * (ny + 1)
    assert len(quads) == nx * ny
    assert len(bars) == small_panel.n_stiffeners * nx


def test_stiffeners_lie_on_their_grid_lines(small_panel):
    model = build_static_model(small_panel)
    ys = sorted({round(model.nodes[n].xyz[1], 6)
                 for e in model.elements.values() if e.type == "CBAR" for n in e.nodes})
    assert ys == pytest.approx(small_panel.stiffener_y_positions)


def test_unstiffened_panel_has_no_bars():
    model = build_static_model(PanelConfig(n_stiffeners=0, elements_x=5, elements_between_stiffeners=5))
    assert not any(e.type == "CBAR" for e in model.elements.values())
    assert "PBAR" not in {p.type for p in model.properties.values()}


def test_skin_normals_point_up(small_panel):
    """Counter-clockwise node order gives a +z normal, so pressure acts in +z."""
    model = build_static_model(small_panel)
    model.cross_reference()
    quad = model.elements[1]
    assert quad.Normal()[2] == pytest.approx(1.0)


def test_bar_ids_do_not_clash_with_shell_ids(small_panel):
    model = build_static_model(small_panel)
    bar_ids = [eid for eid, e in model.elements.items() if e.type == "CBAR"]
    assert min(bar_ids) > BAR_ID_OFFSET


# --- loads -----------------------------------------------------------------------

def test_end_load_sums_to_design_load(small_panel):
    loads = end_load_distribution(small_panel)
    total = sum(f_skin + f_stiff for f_skin, f_stiff in loads.values())
    assert total == pytest.approx(small_panel.design_load)


def test_end_load_gives_uniform_stress(small_panel):
    """Each part's share must be proportional to its area (uniform sigma)."""
    loads = end_load_distribution(small_panel)
    sec = blade_section(small_panel.stiffener_height, small_panel.stiffener_thickness)
    sigma = small_panel.design_load / (small_panel.width * small_panel.skin_thickness
                                       + small_panel.n_stiffeners * sec.A)
    stiffener_forces = [f for _, f in loads.values() if f]
    assert stiffener_forces == pytest.approx([sigma * sec.A] * small_panel.n_stiffeners)


def test_applied_loads_are_self_equilibrated(small_panel):
    """Equal and opposite end loads: net force in x is zero, each end carries P."""
    model = build_static_model(small_panel)
    forces = [card for cards in model.loads.values() for card in cards if card.type == "FORCE"]
    fx = [f.mag * f.xyz[0] for f in forces]
    assert sum(fx) == pytest.approx(0.0, abs=1e-6)
    assert sum(v for v in fx if v > 0) == pytest.approx(small_panel.design_load)


def test_pressure_cards_only_when_requested(small_panel):
    from dataclasses import replace
    no_p = build_static_model(small_panel)
    with_p = build_static_model(replace(small_panel, pressure=0.05))
    count = lambda m: sum(c.type == "PLOAD4" for cards in m.loads.values() for c in cards)
    assert count(no_p) == 0
    assert count(with_p) == small_panel.elements_x * small_panel.elements_y


# --- deck I/O and mass -----------------------------------------------------------

def test_deck_round_trip(tmp_path, small_panel):
    """A written deck reads back with the same content and ends with ENDDATA."""
    path = write_deck(build_buckling_model(small_panel), tmp_path / "panel.bdf")
    assert path.read_text().rstrip().endswith("ENDDATA")
    model = read_bdf(str(path), debug=None)
    assert model.sol == 105
    assert len(model.nodes) == len(build_buckling_model(small_panel).nodes)
    assert model.methods[30].nd == 3


def test_mass_matches_hand_calculation(small_panel):
    c = small_panel
    sec = blade_section(c.stiffener_height, c.stiffener_thickness)
    volume = c.length * c.width * c.skin_thickness + c.n_stiffeners * sec.A * c.length
    assert panel_mass(c) == pytest.approx(volume * c.material.rho, rel=1e-9)


def test_node_numbering_is_row_major(small_panel):
    assert node_id(small_panel, 0, 0) == 1
    assert node_id(small_panel, small_panel.elements_x, 0) == small_panel.elements_x + 1
    assert node_id(small_panel, 0, 1) == small_panel.elements_x + 2
    assert math.isclose(build_static_model(small_panel).nodes[node_id(small_panel, 0, 1)].xyz[1],
                        small_panel.width / small_panel.elements_y)
