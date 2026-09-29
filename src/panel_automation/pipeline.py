"""End-to-end analysis of one panel: build decks, run solver, extract results."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .config import PanelConfig
from .model import build_buckling_model, build_static_model, panel_mass, write_deck
from .results import read_buckling_factors, read_static_results
from .solver import run_solver


# Required reserve factors. Buckling needs a small margin above 1.0 because the
# default mesh over-predicts the buckling load factor by up to ~4% (README,
# "Mesh convergence"); 1.05 keeps a design that passes on the default mesh
# passing on a converged mesh.
RF_STRENGTH_REQUIRED = 1.0
RF_BUCKLING_REQUIRED = 1.05


@dataclass(frozen=True)
class PanelSummary:
    skin_thickness: float
    n_stiffeners: int
    stiffener_height: float
    mass_kg: float
    max_displacement: float
    max_skin_von_mises: float
    max_stiffener_stress: float
    rf_strength: float  # allowable / max stress
    rf_buckling: float  # first buckling load factor

    @property
    def passes(self) -> bool:
        return self.rf_strength >= RF_STRENGTH_REQUIRED and self.rf_buckling >= RF_BUCKLING_REQUIRED

    def as_row(self) -> dict:
        return {**asdict(self), "passes": self.passes}


def analyse_panel(cfg: PanelConfig, workdir: str | Path, name: str = "panel") -> PanelSummary:
    """Run the static and buckling analyses for one design and summarise them."""
    workdir = Path(workdir)
    static_op2 = run_solver(write_deck(build_static_model(cfg), workdir / f"{name}_static.bdf"))
    buckling_op2 = run_solver(write_deck(build_buckling_model(cfg), workdir / f"{name}_buckling.bdf"))

    static = read_static_results(static_op2)
    factors = read_buckling_factors(buckling_op2.with_suffix(".F06"))
    peak_stress = max(static.max_skin_von_mises, static.max_stiffener_stress)

    return PanelSummary(
        skin_thickness=cfg.skin_thickness,
        n_stiffeners=cfg.n_stiffeners,
        stiffener_height=cfg.stiffener_height,
        mass_kg=panel_mass(cfg) * 1000.0,  # tonne -> kg
        max_displacement=static.max_displacement,
        max_skin_von_mises=static.max_skin_von_mises,
        max_stiffener_stress=static.max_stiffener_stress,
        rf_strength=cfg.material.allowable / peak_stress,
        rf_buckling=factors[0],
    )


def refined_buckling_factor(cfg: PanelConfig, workdir: str | Path, name: str = "refined",
                            refinement: int = 2) -> float:
    """First buckling load factor on a mesh `refinement` times finer in each direction.

    Used to confirm that a design chosen on the default (trade-study) mesh still
    passes once the mesh is converged.
    """
    fine = replace(cfg, elements_x=cfg.elements_x * refinement,
                   elements_between_stiffeners=cfg.elements_between_stiffeners * refinement)
    op2 = run_solver(write_deck(build_buckling_model(fine), Path(workdir) / f"{name}_buckling.bdf"))
    return read_buckling_factors(op2.with_suffix(".F06"))[0]
