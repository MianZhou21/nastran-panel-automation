"""Design sweep: vary skin thickness, stiffener count and stiffener height,
find the lightest passing panel.

Run from the command line:

    python -m panel_automation.sweep --out results
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path

from .config import PanelConfig
from .pipeline import RF_BUCKLING_REQUIRED, PanelSummary, analyse_panel, refined_buckling_factor
from .solver import SolverError, require_solver

SKIN_THICKNESSES = (1.2, 1.6, 2.0, 2.5)
STIFFENER_COUNTS = (2, 3, 4, 5)
STIFFENER_HEIGHTS = (15.0, 20.0, 25.0, 30.0)

# The trade-study plot has one panel per stiffener height. Within a panel, colour
# and marker shape both identify the stiffener count (so colour is never the only
# cue). Filled marker = passing design, hollow marker = failing design.
# Colours are from a colour-vision-deficiency-checked categorical palette.
SERIES_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
SERIES_MARKERS = ("o", "s", "D", "^")


@dataclass(frozen=True)
class SweepResult:
    """One design point in the sweep, retaining both inputs and analysis results."""

    cfg: PanelConfig
    summary: PanelSummary
    name: str


def run_sweep(
    base: PanelConfig,
    workdir: Path,
    thicknesses=SKIN_THICKNESSES,
    counts=STIFFENER_COUNTS,
    heights=STIFFENER_HEIGHTS,
) -> list[SweepResult]:
    results: list[SweepResult] = []

    for t, n, h in product(thicknesses, counts, heights):
        cfg = replace(
            base,
            skin_thickness=t,
            n_stiffeners=n,
            stiffener_height=h,
        )
        name = f"t{t:.1f}_n{n}_h{h:.1f}".replace(".", "p")
        summary = analyse_panel(cfg, workdir / name, name=name)
        print(
            f"{name}: mass {summary.mass_kg:.3f} kg, "
            f"RF buckling {summary.rf_buckling:.2f}, "
            f"RF strength {summary.rf_strength:.2f}, "
            f"{'PASS' if summary.passes else 'fail'}"
        )
        results.append(SweepResult(cfg=cfg, summary=summary, name=name))

    return results


def lightest_passing(results: list[SweepResult]) -> SweepResult | None:
    passing = [r for r in results if r.summary.passes]
    return min(passing, key=lambda r: r.summary.mass_kg) if passing else None


def write_csv(results: list[SweepResult], path: Path) -> None:
    rows = [r.summary.as_row() for r in results]

    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_trade_study(results: list[SweepResult], path: Path) -> None:
    """Buckling RF vs mass, as small multiples: one panel per stiffener height.

    Each line holds stiffener count and height fixed while skin thickness varies.
    """
    import math

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    counts = sorted({r.cfg.n_stiffeners for r in results})
    heights = sorted({r.cfg.stiffener_height for r in results})
    if len(counts) > len(SERIES_COLOURS):
        raise ValueError(f"plot supports up to {len(SERIES_COLOURS)} stiffener counts, got {len(counts)}")
    colour = {n: SERIES_COLOURS[k] for k, n in enumerate(counts)}
    marker = {n: SERIES_MARKERS[k] for k, n in enumerate(counts)}

    ink, muted, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    ncols = min(2, len(heights))
    nrows = math.ceil(len(heights) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(9.0, 3.3 * nrows + 0.9), dpi=150,
                             sharex=True, sharey=True, squeeze=False)
    fig.patch.set_facecolor(surface)
    best = lightest_passing(results)

    for ax, h in zip(axes.flat, heights):
        ax.set_facecolor(surface)
        for n in counts:
            series = sorted(
                (r for r in results if r.cfg.n_stiffeners == n and r.cfg.stiffener_height == h),
                key=lambda r: r.cfg.skin_thickness,
            )
            if not series:
                continue
            ax.plot([r.summary.mass_kg for r in series], [r.summary.rf_buckling for r in series],
                    color=colour[n], lw=2, zorder=2)
            for r in series:
                ax.scatter(r.summary.mass_kg, r.summary.rf_buckling, s=40, marker=marker[n], zorder=3,
                           facecolor=colour[n] if r.summary.passes else surface,
                           edgecolor=colour[n], linewidths=1.8)

        ax.axhline(RF_BUCKLING_REQUIRED, color=muted, lw=1, ls="--", zorder=1)
        ax.set_title(f"{h:g} mm stiffener height", color=ink, fontsize=9, loc="left")
        ax.grid(color=grid, lw=0.8)
        ax.tick_params(colors=muted, labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(grid)

        if best is not None and best.cfg.stiffener_height == h:
            s = best.summary
            ax.scatter(s.mass_kg, s.rf_buckling, s=180, facecolor="none", edgecolor=ink,
                       linewidths=1.2, zorder=4)
            ax.annotate(f"Lightest passing: {best.cfg.skin_thickness} mm skin,\n"
                        f"{best.cfg.n_stiffeners} stiffeners, {s.mass_kg:.2f} kg, RF {s.rf_buckling:.2f}",
                        xy=(s.mass_kg, s.rf_buckling), xytext=(0.04, 0.72), textcoords="axes fraction",
                        fontsize=7.5, color=ink,
                        arrowprops={"arrowstyle": "-", "color": muted, "lw": 1})

    for ax in axes.flat[len(heights):]:
        ax.set_visible(False)
    for ax in axes[-1, :]:
        ax.set_xlabel("Panel mass [kg]", color=muted, fontsize=9)
    for ax in axes[:, 0]:
        ax.set_ylabel("Buckling reserve factor", color=muted, fontsize=9)

    handles = [Line2D([0], [0], color=colour[n], marker=marker[n], lw=2, label=f"{n} stiffeners")
               for n in counts]
    handles += [
        Line2D([0], [0], marker="o", ls="None", markerfacecolor=muted, markeredgecolor=muted, label="passes"),
        Line2D([0], [0], marker="o", ls="None", markerfacecolor=surface, markeredgecolor=muted, label="fails"),
        Line2D([0], [0], color=muted, lw=1, ls="--", label=f"required RF = {RF_BUCKLING_REQUIRED:g}"),
    ]
    legend = fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.01, 0.955),
                        ncol=len(handles), frameon=False, fontsize=8, handletextpad=0.4,
                        columnspacing=1.2)
    for text in legend.get_texts():
        text.set_color(ink)
    fig.suptitle("Stiffened panel trade study: buckling RF vs mass", x=0.01, ha="left",
                 color=ink, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def plot_mode_shape(cfg: PanelConfig, buckling_op2: Path, path: Path, rf: float) -> None:
    """Contour of the first buckling mode (out-of-plane shape, normalised)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap

    from .results import read_buckling_mode

    w = read_buckling_mode(buckling_op2, mode=1)
    w = (w / np.abs(w).max()).reshape(cfg.elements_y + 1, cfg.elements_x + 1)
    x = np.linspace(0, cfg.length, cfg.elements_x + 1)
    y = np.linspace(0, cfg.width, cfg.elements_y + 1)
    # diverging: blue (-) -> neutral grey (0) -> red (+); the sign of a mode is arbitrary
    cmap = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])

    ink, muted = "#0b0b0b", "#52514e"
    fig, ax = plt.subplots(figsize=(7.5, 5.0), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    im = ax.contourf(x, y, w, levels=np.linspace(-1, 1, 21), cmap=cmap)
    for yy in cfg.stiffener_y_positions:
        ax.plot([0, cfg.length], [yy, yy], color=ink, lw=1.5)
    ax.set_aspect("equal")
    ax.set_xlabel("x, load direction [mm]", color=muted)
    ax.set_ylabel("y [mm]", color=muted)
    ax.tick_params(colors=muted)
    ax.set_title(
        f"First buckling mode (load factor {rf:.2f}); black lines = stiffeners",
        color=ink,
        fontsize=10,
        loc="left",
    )
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, ticks=[-1, 0, 1])
    cbar.set_label("normalised out-of-plane displacement", color=muted)
    cbar.ax.tick_params(colors=muted)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("results"), help="output folder")
    parser.add_argument("--line-load", type=float, default=100.0, help="design Nx [N/mm]")
    parser.add_argument("--pressure", type=float, default=0.0, help="lateral pressure [MPa]")
    args = parser.parse_args(argv)

    try:  # check for the solver before starting 128 runs
        require_solver()
    except SolverError as exc:
        sys.exit(f"Error: {exc}")

    base = PanelConfig(compressive_line_load=args.line_load, pressure=args.pressure)
    args.out.mkdir(parents=True, exist_ok=True)
    results = run_sweep(base, args.out / "runs")
    write_csv(results, args.out / "trade_study.csv")
    plot_trade_study(results, args.out / "trade_study.png")

    best = lightest_passing(results)
    if best is None:
        print("\nLightest passing design: none")
        return

    plot_mode_shape(
        best.cfg,
        args.out / "runs" / best.name / f"{best.name}_buckling.OP2",
        args.out / "buckling_mode.png",
        best.summary.rf_buckling,
    )
    # Confirm the chosen design on a 2x finer mesh (the trade-study mesh is
    # slightly unconservative for buckling).
    rf_fine = refined_buckling_factor(best.cfg, args.out / "runs" / f"{best.name}_refined",
                                      name=f"{best.name}_refined")
    confirmed = rf_fine >= RF_BUCKLING_REQUIRED
    report = (
        f"Lightest passing design: {best.cfg.skin_thickness} mm skin, "
        f"{best.cfg.n_stiffeners} stiffeners, {best.cfg.stiffener_height:g} mm height, "
        f"{best.summary.mass_kg:.3f} kg\n"
        f"Buckling RF: {best.summary.rf_buckling:.3f} (trade-study mesh), "
        f"{rf_fine:.3f} (2x finer mesh) -> "
        f"{'confirmed' if confirmed else 'NOT confirmed'} against required RF {RF_BUCKLING_REQUIRED:g}\n"
        f"Strength RF: {best.summary.rf_strength:.2f}\n"
    )
    (args.out / "lightest_design.txt").write_text(report)
    print("\n" + report)

if __name__ == "__main__":
    main()
