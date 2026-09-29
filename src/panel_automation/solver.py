"""Run a Nastran-compatible solver (MYSTRAN by default) on a .bdf deck."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class SolverError(RuntimeError):
    """Raised when the solver is missing or reports a fatal error."""


SOLVER_HELP = (
    "MYSTRAN solver not found. Either:\n"
    "  * set the MYSTRAN_EXE environment variable to the full path of the mystran executable, or\n"
    "  * put `mystran` on your PATH, or\n"
    "  * run the analysis on GitHub instead: Actions tab -> 'run design sweep' -> 'Run workflow'.\n"
    "See the README (Quick start) for how to install MYSTRAN."
)


def find_solver() -> str | None:
    """Locate the solver: $MYSTRAN_EXE first, then `mystran` on the PATH."""
    exe = os.environ.get("MYSTRAN_EXE")
    if exe and Path(exe).is_file():
        return exe
    return shutil.which("mystran")


def require_solver() -> str:
    """Return the solver path, or raise SolverError with setup instructions."""
    exe = find_solver()
    if exe is None:
        raise SolverError(SOLVER_HELP)
    return exe


def run_solver(bdf_path: str | Path, exe: str | None = None, timeout: float = 600) -> Path:
    """Run the solver in the deck's folder and return the path of the OP2 file.

    MYSTRAN writes <name>.F06 (text log), <name>.ERR and <name>.OP2 (binary
    results) next to the input deck.
    """
    bdf_path = Path(bdf_path).resolve()
    exe = exe or require_solver()

    stem = bdf_path.with_suffix("")
    for ext in (".F06", ".ERR", ".OP2", ".NEU"):  # clear results from earlier runs
        stem.with_suffix(ext).unlink(missing_ok=True)

    proc = subprocess.run([exe, bdf_path.name], cwd=bdf_path.parent,
                          capture_output=True, text=True, timeout=timeout)

    f06 = stem.with_suffix(".F06")
    log = f06.read_text(errors="replace") if f06.exists() else ""
    if proc.returncode != 0 or "FATAL" in proc.stdout or "*ERROR" in log:
        errors = [line.strip() for line in log.splitlines() if "*ERROR" in line]
        raise SolverError(f"Solver failed on {bdf_path.name}: " + ("; ".join(errors) or proc.stdout[-500:]))

    op2 = stem.with_suffix(".OP2")
    if not op2.exists():
        raise SolverError(f"No OP2 file written for {bdf_path.name}")
    return op2
