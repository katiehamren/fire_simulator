"""Tests for engine/tax_calc.py"""
import pytest

from engine.tax_calc import compute_federal_tax, effective_rate, marginal_rate


class TestComputeFederalTax:
    def test_zero_income(self):
        assert compute_federal_tax(0) == 0.0

    def test_below_standard_deduction(self):
        """Income below standard deduction ($31,500) should yield $0 tax."""
        assert compute_federal_tax(30_000) == 0.0

    def test_just_above_standard_deduction(self):
        """$35,000 gross → $3,500 taxable → 10% bracket → $350 tax."""
        assert compute_federal_tax(35_000) == pytest.approx(350.0)

    def test_known_bracket_crossing(self):
        """$100,000 gross → $68,500 taxable.
        10% on first $23,850 = $2,385
        12% on next $44,650 ($23,850 to $68,500) = $5,358
        Total = $7,743
        """
        assert compute_federal_tax(100_000) == pytest.approx(7_743.0)

    def test_high_income(self):
        """$300,000 gross → $268,500 taxable.
        10% on $23,850 = $2,385
        12% on $73,100 = $8,772
        22% on $109,750 = $24,145
        24% on $61,800 ($206,700 to $268,500) = $14,832
        Total = $50,134
        """
        assert compute_federal_tax(300_000) == pytest.approx(50_134.0)

    def test_negative_income(self):
        assert compute_federal_tax(-10_000) == 0.0


class TestMarginalRate:
    def test_below_deduction(self):
        assert marginal_rate(20_000) == 0.10

    def test_12_pct_bracket(self):
        assert marginal_rate(60_000) == 0.12

    def test_22_pct_bracket(self):
        assert marginal_rate(150_000) == 0.22

    def test_37_pct_bracket(self):
        assert marginal_rate(800_000) == 0.37


class TestEffectiveRate:
    def test_zero_income(self):
        assert effective_rate(0) == 0.0

    def test_positive_income(self):
        rate = effective_rate(100_000)
        assert 0.0 < rate < 0.22
        assert rate == pytest.approx(7_743.0 / 100_000)
