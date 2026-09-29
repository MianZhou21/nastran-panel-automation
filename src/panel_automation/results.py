"""Extract results from solver output files.

* static results come from the binary OP2 file via pyNastran
* buckling load factors are read from the F06 text file, because MYSTRAN
  writes the buckling eigenvectors to the OP2 but not the eigenvalues
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyNastran.op2.op2 import read_op2


@dataclass(frozen=True)
class StaticResults:
    max_displacement: float  # max |w| out of plane [mm]
    max_skin_von_mises: float  # max over both shell fibres [MPa]
    max_stiffener_stress: float  # max |axial| stress in the stiffeners [MPa]
    reaction_force: np.ndarray  # sum of SPC forces [Fx, Fy, Fz] [N]


def read_static_results(op2_path: str | Path) -> StaticResults:
    op2 = read_op2(str(op2_path), debug=None, mode="nx")
    subcase = 1
    disp = op2.displacements[subcase].data[0]  # (nnodes, 6): t1 t2 t3 r1 r2 r3
    quad = op2.op2_results.stress.cquad4_stress[subcase]
    von_mises = quad.data[0, :, quad.get_headers().index("von_mises")]

    bar_stress = 0.0
    bars = op2.op2_results.stress.cbar_stress
    if subcase in bars:
        axial = bars[subcase].data[0, :, bars[subcase].get_headers().index("axial")]
        bar_stress = float(np.abs(axial).max())

    spc = op2.spc_forces[subcase].data[0]
    return StaticResults(
        max_displacement=float(np.abs(disp[:, 2]).max()),
        max_skin_von_mises=float(von_mises.max()),
        max_stiffener_stress=bar_stress,
        reaction_force=spc[:, :3].sum(axis=0),
    )


_EIGEN_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+([-+]?\d\.\d+E[-+]\d+)\s*$")


def read_buckling_factors(f06_path: str | Path) -> list[float]:
    """Buckling load factors (eigenvalues) in mode order from a MYSTRAN F06."""
    lines = Path(f06_path).read_text(errors="replace").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if "buckling load factors" in line.lower())
    except StopIteration as exc:
        raise ValueError(f"No buckling load factor table in {f06_path}") from exc

    factors: list[float] = []
    for line in lines[start + 1:]:
        match = _EIGEN_ROW.match(line)
        if match:
            factors.append(float(match.group(3)))
        elif factors and line.strip():
            break  # end of the table
    if not factors:
        raise ValueError(f"Buckling table in {f06_path} is empty")
    return factors


def read_buckling_mode(op2_path: str | Path, mode: int = 1) -> np.ndarray:
    """Out-of-plane shape (w) of a buckling mode, one value per grid point."""
    op2 = read_op2(str(op2_path), debug=None, mode="nx")
    vectors = next(iter(op2.eigenvectors.values()))
    return vectors.data[mode - 1, :, 2]
