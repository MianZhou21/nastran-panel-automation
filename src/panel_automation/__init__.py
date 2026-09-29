"""Automated Nastran model generation, solving and post-processing for stiffened panels."""
from .config import AL_2024_T3, Material, PanelConfig
from .model import build_buckling_model, build_static_model, panel_mass, write_deck
from .pipeline import PanelSummary, analyse_panel

__all__ = [
    "AL_2024_T3", "Material", "PanelConfig",
    "build_buckling_model", "build_static_model", "panel_mass", "write_deck",
    "PanelSummary", "analyse_panel",
]
__version__ = "0.1.0"
