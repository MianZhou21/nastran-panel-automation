"""Build Nastran input decks (.bdf) for a stiffened panel with pyNastran.

Two decks can be generated from the same geometry:

* static  (SOL 101): design compression + optional lateral pressure
* buckling (SOL 105): linear buckling under the design compression

Modelling choices (kept simple on purpose, see README "Limitations"):

* skin: CQUAD4 shells, stiffeners: CBAR with a z-offset so they sit on the skin
* all four edges simply supported out of plane (T3 = 0)
* in-plane rigid-body motion removed at two corners (x, y at one; y at the other)
* in-plane drilling rotation (R3) restrained at every node
* the end load is applied as equal and opposite nodal forces on both loaded
  edges (x = 0 and x = length), so the load case is self-equilibrated.
  It is shared between skin and stiffeners in proportion to their area
  (a uniform compressive stress). Each stiffener's share acts through its own
  centroid: a nodal MOMENT transfers it from the skin node to the offset
  stiffener axis, so no spurious bending is introduced.
"""
from __future__ import annotations

from pathlib import Path

from pyNastran.bdf.bdf import BDF
from pyNastran.bdf.case_control_deck import CaseControlDeck
from pyNastran.bdf.mesh_utils.mass_properties import mass_properties

from .config import PanelConfig
from .sections import blade_section

# Card IDs used throughout the deck
MAT_ID = 1
PSHELL_ID = 1
PBAR_ID = 2
SPC_ID = 1
STATIC_LOAD_ID = 10
BUCKLING_LOAD_ID = 20
EIGRL_ID = 30
BAR_ID_OFFSET = 100_000


def node_id(cfg: PanelConfig, i: int, j: int) -> int:
    """Grid ID of the skin node at column i (x) and row j (y), both 0-based."""
    return j * (cfg.elements_x + 1) + i + 1


def _stiffener_rows(cfg: PanelConfig) -> list[int]:
    """Mesh row indices (j) that carry a stiffener."""
    return [cfg.elements_between_stiffeners * (k + 1) for k in range(cfg.n_stiffeners)]


def _add_geometry(model: BDF, cfg: PanelConfig) -> None:
    nx, ny = cfg.elements_x, cfg.elements_y
    dx, dy = cfg.length / nx, cfg.width / ny

    for j in range(ny + 1):
        for i in range(nx + 1):
            model.add_grid(node_id(cfg, i, j), [i * dx, j * dy, 0.0])

    # Skin: counter-clockwise node order so the element normal points in +z
    eid = 1
    for j in range(ny):
        for i in range(nx):
            nodes = [node_id(cfg, i, j), node_id(cfg, i + 1, j),
                     node_id(cfg, i + 1, j + 1), node_id(cfg, i, j + 1)]
            model.add_cquad4(eid, PSHELL_ID, nodes)
            eid += 1

    m = cfg.material
    model.add_mat1(MAT_ID, float(m.E), None, float(m.nu), rho=float(m.rho))
    # Nastran needs real fields written with a decimal point, hence float()
    model.add_pshell(PSHELL_ID, mid1=MAT_ID, t=float(cfg.skin_thickness), mid2=MAT_ID)

    if cfg.n_stiffeners == 0:
        return

    sec = blade_section(cfg.stiffener_height, cfg.stiffener_thickness)
    model.add_pbar(PBAR_ID, MAT_ID, A=float(sec.A), i1=float(sec.I1), i2=float(sec.I2), j=float(sec.J))
    z_offset = float(cfg.skin_thickness / 2 + cfg.stiffener_height / 2)
    offset = [0.0, 0.0, z_offset]

    bid = BAR_ID_OFFSET + 1
    for j in _stiffener_rows(cfg):
        for i in range(nx):
            model.add_cbar(
                bid, PBAR_ID, [node_id(cfg, i, j), node_id(cfg, i + 1, j)],
                x=[0.0, 0.0, 1.0], g0=None, offt="GGG", wa=offset, wb=offset,
            )
            bid += 1


def _add_constraints(model: BDF, cfg: PanelConfig) -> None:
    nx, ny = cfg.elements_x, cfg.elements_y
    edge = {node_id(cfg, i, j) for j in range(ny + 1) for i in range(nx + 1)
            if i in (0, nx) or j in (0, ny)}
    all_nodes = [node_id(cfg, i, j) for j in range(ny + 1) for i in range(nx + 1)]

    model.add_spc1(SPC_ID, "3", sorted(edge))           # simply supported out of plane
    # In-plane rigid-body motion: fix x and y at one corner, and y at the next
    # corner along the x-axis to stop in-plane rotation. Both lie on y = 0, so
    # Poisson expansion of the panel is not restrained.
    model.add_spc1(SPC_ID, "12", [node_id(cfg, 0, 0)])
    model.add_spc1(SPC_ID, "2", [node_id(cfg, nx, 0)])
    model.add_spc1(SPC_ID, "6", all_nodes)               # no drilling stiffness in CQUAD4


def end_load_distribution(cfg: PanelConfig) -> dict[int, tuple[float, float]]:
    """Nodal loads on one loaded edge that give a uniform compressive stress.

    Returns {row index j: (skin force [N], stiffener force [N])}, both positive
    (compressive). The skin share uses tributary widths (half width at the two
    corners); rows with a stiffener also carry sigma * A_stiffener.
    """
    ny = cfg.elements_y
    dy = cfg.width / ny
    stiff_area = blade_section(cfg.stiffener_height, cfg.stiffener_thickness).A if cfg.n_stiffeners else 0.0
    total_area = cfg.width * cfg.skin_thickness + cfg.n_stiffeners * stiff_area
    sigma = cfg.design_load / total_area

    rows = set(_stiffener_rows(cfg))
    loads: dict[int, tuple[float, float]] = {}
    for j in range(ny + 1):
        trib = dy / 2 if j in (0, ny) else dy
        loads[j] = (sigma * cfg.skin_thickness * trib, sigma * stiff_area if j in rows else 0.0)
    return loads


def _add_end_load(model: BDF, cfg: PanelConfig, sid: int) -> None:
    """Equal and opposite compressive loads on edges x = 0 and x = length."""
    z = cfg.skin_thickness / 2 + cfg.stiffener_height / 2  # stiffener centroid offset
    for j, (f_skin, f_stiff) in end_load_distribution(cfg).items():
        for i, sign in ((cfg.elements_x, -1.0), (0, 1.0)):  # push inwards from both ends
            nid = node_id(cfg, i, j)
            model.add_force(sid, nid, float(f_skin + f_stiff), [sign, 0.0, 0.0])
            if f_stiff:
                # move the stiffener's share from the skin node up to its centroid
                model.add_moment(sid, nid, float(sign * f_stiff * z), [0.0, 1.0, 0.0])


def _new_model(sol: int, case_lines: list[str]) -> BDF:
    model = BDF(debug=None)
    model.sol = sol
    model.case_control_deck = CaseControlDeck(case_lines)
    model.add_param("POST", -1)  # ask the solver for an OP2 results file
    return model


def build_static_model(cfg: PanelConfig) -> BDF:
    """SOL 101 deck: design compression plus lateral pressure (if any)."""
    model = _new_model(101, [
        "TITLE = STIFFENED PANEL - STATIC",
        "SUBCASE 1",
        "  LABEL = DESIGN COMPRESSION + PRESSURE",
        f"  SPC = {SPC_ID}",
        f"  LOAD = {STATIC_LOAD_ID}",
        "  DISPLACEMENT = ALL",
        "  STRESS = ALL",
        "  SPCFORCES = ALL",
    ])
    _add_geometry(model, cfg)
    _add_constraints(model, cfg)
    _add_end_load(model, cfg, STATIC_LOAD_ID)
    if cfg.pressure > 0:
        for eid in model.elements:
            if model.elements[eid].type == "CQUAD4":
                model.add_pload4(STATIC_LOAD_ID, [eid], [float(cfg.pressure)] * 4)
    return model


def build_buckling_model(cfg: PanelConfig, n_modes: int = 3) -> BDF:
    """SOL 105 deck: linear buckling under the design compression.

    The buckling eigenvalue is the factor on the design load at which the
    panel buckles, i.e. the buckling reserve factor.
    """
    model = _new_model(105, [
        "TITLE = STIFFENED PANEL - BUCKLING",
        f"SPC = {SPC_ID}",
        "SUBCASE 1",
        "  LABEL = DESIGN COMPRESSION (PRELOAD)",
        f"  LOAD = {BUCKLING_LOAD_ID}",
        "SUBCASE 2",
        "  LABEL = BUCKLING",
        f"  METHOD = {EIGRL_ID}",
        "  DISPLACEMENT = ALL",
    ])
    _add_geometry(model, cfg)
    _add_constraints(model, cfg)
    _add_end_load(model, cfg, BUCKLING_LOAD_ID)
    model.add_eigrl(EIGRL_ID, v1=0.0, nd=n_modes)
    return model


def write_deck(model: BDF, path: str | Path) -> Path:
    """Write the deck, including the ENDDATA card that solvers require."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write_bdf(str(path), enddata=True)
    return path


def panel_mass(cfg: PanelConfig) -> float:
    """Structural mass [tonne] computed by pyNastran from the deck itself."""
    model = build_static_model(cfg)
    model.cross_reference()  # link cards (element -> property -> material)
    mass, _, _ = mass_properties(model)
    return float(mass)
