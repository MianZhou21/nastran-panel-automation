import pytest

from panel_automation.config import PanelConfig
from panel_automation.solver import find_solver

# Tests marked `solver` need MYSTRAN; they are skipped automatically without it.
requires_solver = pytest.mark.skipif(find_solver() is None, reason="MYSTRAN not available")


@pytest.fixture
def small_panel() -> PanelConfig:
    """Coarse stiffened panel that builds (and solves) quickly."""
    return PanelConfig(length=300.0, width=240.0, n_stiffeners=2,
                       elements_x=12, elements_between_stiffeners=3)
