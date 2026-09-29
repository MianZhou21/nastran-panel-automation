"""Input definitions for a stiffened panel.

Units throughout: N, mm, MPa, tonne (so density is in tonne/mm^3).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Material:
    """Linear elastic isotropic material (maps to a Nastran MAT1 card)."""

    name: str
    E: float  # Young's modulus [MPa]
    nu: float  # Poisson's ratio [-]
    rho: float  # density [tonne/mm^3]
    allowable: float  # allowable von Mises stress for strength checks [MPa]

    def __post_init__(self) -> None:
        if self.E <= 0:
            raise ValueError("E must be positive")
        if not 0.0 <= self.nu < 0.5:
            raise ValueError("nu must be in [0, 0.5)")
        if self.rho <= 0 or self.allowable <= 0:
            raise ValueError("rho and allowable must be positive")


# Typical values for an aluminium alloy used in fuselage skins.
# Allowable is an illustrative yield-based value, not a certified design allowable.
AL_2024_T3 = Material(name="Al 2024-T3", E=72_400.0, nu=0.33, rho=2.78e-9, allowable=290.0)


@dataclass(frozen=True)
class PanelConfig:
    """Flat skin panel with blade stiffeners running in the loaded (x) direction.

    The panel spans 0 <= x <= length and 0 <= y <= width. Stiffeners are equally
    spaced in y and sit on top of the skin (offset in +z).
    """

    length: float = 500.0  # panel length in the load direction, x [mm]
    width: float = 400.0  # panel width, y [mm]
    skin_thickness: float = 2.0  # [mm]
    n_stiffeners: int = 3  # number of blade stiffeners (0 = unstiffened plate)
    stiffener_height: float = 25.0  # blade height [mm]
    stiffener_thickness: float = 2.0  # blade thickness [mm]
    # Default mesh: buckling load factor within ~4% of a 2x finer mesh (see README)
    elements_x: int = 40  # skin elements along x
    elements_between_stiffeners: int = 6  # skin elements between adjacent stiffeners in y
    material: Material = field(default=AL_2024_T3)

    # Loads
    compressive_line_load: float = 100.0  # design end load per unit width, Nx [N/mm]
    pressure: float = 0.0  # design lateral pressure on the skin [MPa], +z

    def __post_init__(self) -> None:
        for name in ("length", "width", "skin_thickness"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.n_stiffeners < 0:
            raise ValueError("n_stiffeners must be >= 0")
        if self.n_stiffeners > 0 and (self.stiffener_height <= 0 or self.stiffener_thickness <= 0):
            raise ValueError("stiffener dimensions must be positive")
        if self.elements_x < 1 or self.elements_between_stiffeners < 1:
            raise ValueError("mesh densities must be >= 1")
        if self.compressive_line_load < 0 or self.pressure < 0:
            raise ValueError("loads must be non-negative")

    @property
    def stiffener_pitch(self) -> float:
        """Distance between stiffeners (and from the outer stiffeners to the edges)."""
        return self.width / (self.n_stiffeners + 1)

    @property
    def elements_y(self) -> int:
        return self.elements_between_stiffeners * (self.n_stiffeners + 1)

    @property
    def stiffener_y_positions(self) -> list[float]:
        return [self.stiffener_pitch * (k + 1) for k in range(self.n_stiffeners)]

    @property
    def design_load(self) -> float:
        """Total compressive end load [N]."""
        return self.compressive_line_load * self.width
