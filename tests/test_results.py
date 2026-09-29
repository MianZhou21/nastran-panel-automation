"""Tests for the F06 parser, using a small excerpt of real MYSTRAN output."""
import pytest

from panel_automation.results import read_buckling_factors

F06_EXCERPT = """
                                      (subcase       2 buckling load factors)

                                         MODE  EXTRACTION      EIGENVALUE
                                        NUMBER   ORDER

                                             1       1        2.429943E+00
                                             2       2        2.803198E+00
                                             3       3        3.490370E+00



 >> LINK  4 END
"""


def test_reads_buckling_factors_in_order(tmp_path):
    f06 = tmp_path / "run.F06"
    f06.write_text(F06_EXCERPT)
    assert read_buckling_factors(f06) == pytest.approx([2.429943, 2.803198, 3.490370])


def test_missing_table_raises(tmp_path):
    f06 = tmp_path / "static.F06"
    f06.write_text("no eigenvalues here\n")
    with pytest.raises(ValueError):
        read_buckling_factors(f06)
