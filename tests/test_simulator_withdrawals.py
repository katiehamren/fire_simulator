"""Tests for withdrawal ordering and early withdrawal penalties."""
import pytest

from engine.models import AccountBalances, AnnualContributions
from engine.simulator import run_simulation

from tests.conftest import snap_year


class TestWithdrawalOrder:
    def test_cash_drawn_first(self, default_inputs):
        """When deficit exists, cash should be reduced before other accounts."""
        default_inputs.accounts = AccountBalances(cash=200_000, brokerage=200_000)
        default_inputs.contributions = AnnualContributions()
        default_inputs.user_w2.gross_annual = 0
        default_inputs.spouse_w2.gross_annual = 0
        default_inputs.sole_prop.net_annual = 0
        default_inputs.rental.monthly_gross_rent = 0
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.cash < 200_000
        assert s.brokerage == pytest.approx(200_000)

    def test_brokerage_drawn_after_cash_exhausted(self, default_inputs):
        default_inputs.accounts = AccountBalances(cash=50_000, brokerage=200_000)
        default_inputs.contributions = AnnualContributions()
        default_inputs.user_w2.gross_annual = 0
        default_inputs.spouse_w2.gross_annual = 0
        default_inputs.sole_prop.net_annual = 0
        default_inputs.rental.monthly_gross_rent = 0
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.cash == pytest.approx(0.0)
        assert s.brokerage < 200_000

    def test_early_withdrawal_flagged_before_59(self, default_inputs):
        """Drawing from pre-tax 401k before age 59.5 should flag early_withdrawal_amount."""
        default_inputs.accounts = AccountBalances(user_401k_pretax=500_000)
        default_inputs.contributions = AnnualContributions()
        default_inputs.user_w2.gross_annual = 0
        default_inputs.spouse_w2.gross_annual = 0
        default_inputs.sole_prop.net_annual = 0
        default_inputs.rental.monthly_gross_rent = 0
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.early_withdrawal_amount > 0

    def test_no_penalty_after_59(self, default_inputs):
        """Drawing from pre-tax 401k after 59.5 should NOT flag early withdrawal."""
        default_inputs.user.birth_year = 1966
        default_inputs.accounts = AccountBalances(user_401k_pretax=500_000)
        default_inputs.contributions = AnnualContributions()
        default_inputs.user_w2.gross_annual = 0
        default_inputs.spouse_w2.gross_annual = 0
        default_inputs.sole_prop.net_annual = 0
        default_inputs.rental.monthly_gross_rent = 0
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.early_withdrawal_amount == 0.0


class TestPlanSolvency:
    def test_plan_insolvent_when_all_accounts_empty(self, default_inputs):
        default_inputs.accounts = AccountBalances(cash=10_000)
        default_inputs.contributions = AnnualContributions()
        default_inputs.user_w2.gross_annual = 0
        default_inputs.spouse_w2.gross_annual = 0
        default_inputs.sole_prop.net_annual = 0
        default_inputs.rental.monthly_gross_rent = 0
        default_inputs.assumptions.annual_spending_today = 80_000
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.plan_solvent is False

    def test_plan_solvent_with_sufficient_income(self, default_inputs):
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.plan_solvent is True
