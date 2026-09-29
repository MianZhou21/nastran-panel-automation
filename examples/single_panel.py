"""Analyse one panel design end to end and print its reserve factors.

    python examples/single_panel.py
"""
import sys

from panel_automation import PanelConfig, analyse_panel
from panel_automation.solver import SolverError, require_solver

try:
    require_solver()
except SolverError as exc:
    sys.exit(f"Error: {exc}")

cfg = PanelConfig(
    skin_thickness=1.6,        # mm
    n_stiffeners=3,
    stiffener_height=25.0,     # mm
    compressive_line_load=100.0,  # N/mm
    pressure=0.05,             # MPa (0.5 bar)
)

summary = analyse_panel(cfg, workdir="runs/single_panel", name="panel")

print(f"Mass:                 {summary.mass_kg:.3f} kg")
print(f"Max out-of-plane w:   {summary.max_displacement:.2f} mm")
print(f"Max skin von Mises:   {summary.max_skin_von_mises:.1f} MPa")
print(f"RF strength:          {summary.rf_strength:.2f}")
print(f"RF buckling:          {summary.rf_buckling:.2f}")
print("Result:              ", "PASS" if summary.passes else "FAIL")
