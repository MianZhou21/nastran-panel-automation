"""Cross-section properties for beam (CBAR) stiffeners."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BarSection:
    """Section properties in the form a Nastran PBAR card expects."""

    A: float  # area [mm^2]
    I1: float  # second moment of area for bending in element plane 1 [mm^4]
    I2: float  # second moment of area for bending in element plane 2 [mm^4]
    J: float  # torsion constant [mm^4]


def blade_section(height: float, thickness: float) -> BarSection:
    """Rectangular blade stiffener standing vertically on the skin.

    Plane 1 is the vertical (z) plane, so I1 is the stiff out-of-plane bending
    term that resists panel buckling. J uses the thin-rectangle approximation
    J = h t^3 / 3 * (1 - 0.63 t/h), valid for h >= t.
    """
    if height <= 0 or thickness <= 0:
        raise ValueError("height and thickness must be positive")
    h, t = height, thickness
    a, b = max(h, t), min(h, t)
    return BarSection(
        A=h * t,
        I1=t * h**3 / 12.0,
        I2=h * t**3 / 12.0,
        J=a * b**3 / 3.0 * (1.0 - 0.63 * b / a),
    )
