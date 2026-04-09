"""Tests for basic simulation mechanics: income, contributions, growth, expenses."""
import pytest

from engine.models import AccountBalances, AnnualContributions
from engine.simulator import run_simulation

from tests.conftest import snap_year


class TestIncome:
    def test_w2_income_active_before_stop_year(self, default_inputs):
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.user_w2_gross == 100_000
        assert s.spouse_w2_gross == 100_000

    def test_w2_income_zero_at_stop_year(self, default_inputs):
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2029)
        assert s.user_w2_gross == 0.0
        assert s.spouse_w2_gross == 100_000

    def test_sole_prop_active_for_years_active(self, default_inputs):
        snaps = run_simulation(default_inputs)
        s2026 = snap_year(snaps, 2026)
        assert s2026.sole_prop_net == 50_000

    def test_rental_noi_calculation(self, default_inputs):
        """$24k gross * (1 - 0.0 vacancy) - $24k * 0.25 expense = $18k NOI."""
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.rental_cashflow == pytest.approx(18_000)

    def test_w2_raises_compound(self, default_inputs):
        default_inputs.user_w2.annual_raise_rate = 0.10
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2028)
        assert s.user_w2_gross == pytest.approx(100_000 * 1.1**2)


class TestContributions:
    def test_401k_dollar_mode(self, default_inputs):
        """With $10k/yr dollar mode, 401k should grow by $10k/yr (0% return)."""
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.user_401k_pretax >= 110_000

    def test_401k_stops_when_w2_stops(self, default_inputs):
        snaps = run_simulation(default_inputs)
        s2029 = snap_year(snaps, 2029)
        s2030 = snap_year(snaps, 2030)
        assert s2030.user_401k_pretax <= s2029.user_401k_pretax

    def test_401k_max_mode_uses_irs_limit(self, default_inputs):
        default_inputs.contributions.user_401k_mode = "max"
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.user_401k_pretax == pytest.approx(100_000 + 23_500)


class TestHSAContribution:
    def test_hsa_funded_while_any_w2(self, default_inputs):
        default_inputs.contributions.hsa_mode = "dollar"
        default_inputs.contributions.hsa_annual = 8_000
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.hsa_contribution == pytest.approx(8_000)
        assert s.hsa == pytest.approx(8_000)

    def test_hsa_max_mode_family_cap(self, default_inputs):
        from engine.models import annual_hsa_family_limit

        default_inputs.contributions.hsa_mode = "max"
        default_inputs.contributions.hsa_annual = 0.0
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        cap = annual_hsa_family_limit(2026, default_inputs.assumptions.inflation_rate)
        assert s.hsa_contribution == pytest.approx(cap)

    def test_hsa_stops_when_no_w2(self, default_inputs):
        default_inputs.contributions.hsa_mode = "dollar"
        default_inputs.contributions.hsa_annual = 5_000
        default_inputs.end_year = 2045
        snaps = run_simulation(default_inputs)
        s = next(x for x in snaps if x.year == 2037)
        assert s.user_w2_gross == 0 and s.spouse_w2_gross == 0
        assert s.hsa_contribution == 0.0


class TestAccountGrowth:
    def test_zero_return_no_growth(self, default_inputs):
        """With 0% return, account growth should be zero."""
        default_inputs.contributions.user_401k_mode = "dollar"
        default_inputs.contributions.user_401k_amount = 0
        default_inputs.contributions.spouse_401k_amount = 0
        default_inputs.accounts = AccountBalances(brokerage=100_000)
        default_inputs.assumptions.annual_spending_today = 0
        default_inputs.assumptions.annual_healthcare_flat = 0
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.brokerage >= 100_000

    def test_positive_return_compounds(self, default_inputs):
        default_inputs.assumptions.market_return_rate = 0.10
        default_inputs.accounts = AccountBalances(brokerage=100_000)
        default_inputs.assumptions.annual_spending_today = 0
        default_inputs.assumptions.annual_healthcare_flat = 0
        default_inputs.contributions = AnnualContributions()
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.brokerage > 110_000
