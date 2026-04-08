"""Tests for Roth conversion ladder, SEPP/72(t), and RMDs."""
import pytest

from engine.models import RothConversionPlan, SEPPPlan
from engine.simulator import run_simulation

from tests.conftest import snap_year


class TestRothConversion:
    def test_conversion_moves_pretax_to_roth(self, default_inputs):
        default_inputs.roth_conversion = RothConversionPlan(
            enabled=True,
            start_year=2029,
            end_year=2029,
            annual_amount=20_000,
            source="user",
        )
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2029)
        assert s.roth_conversion_amount == pytest.approx(20_000)
        assert s.user_roth_ira >= 20_000

    def test_conversion_not_active_outside_window(self, default_inputs):
        default_inputs.roth_conversion = RothConversionPlan(
            enabled=True,
            start_year=2030,
            end_year=2035,
            annual_amount=20_000,
            source="user",
        )
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2029)
        assert s.roth_conversion_amount == 0.0

    def test_seasoning_after_5_years(self, default_inputs):
        default_inputs.roth_conversion = RothConversionPlan(
            enabled=True,
            start_year=2027,
            end_year=2027,
            annual_amount=30_000,
            source="user",
        )
        default_inputs.end_year = 2035
        snaps = run_simulation(default_inputs)
        s2031 = snap_year(snaps, 2031)
        s2032 = snap_year(snaps, 2032)
        assert s2031.accessible_roth_seasoned == 0.0
        assert s2032.accessible_roth_seasoned >= 30_000

    def test_conversion_limited_to_available_pretax(self, default_inputs):
        default_inputs.accounts.user_401k_pretax = 5_000
        default_inputs.accounts.user_trad_ira = 0
        default_inputs.roth_conversion = RothConversionPlan(
            enabled=True,
            start_year=2029,
            end_year=2029,
            annual_amount=50_000,
            source="user",
        )
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2029)
        assert s.roth_conversion_amount <= 5_000 + 10_000 * 3


class TestSEPP:
    def test_sepp_produces_payments(self, default_inputs):
        default_inputs.sepp = SEPPPlan(
            enabled=True,
            start_year=2030,
            account="user",
            interest_rate=0.05,
        )
        default_inputs.end_year = 2050
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2030)
        assert s.sepp_payment > 0

    def test_sepp_payments_are_constant(self, default_inputs):
        default_inputs.sepp = SEPPPlan(
            enabled=True,
            start_year=2030,
            account="user",
            interest_rate=0.05,
        )
        default_inputs.end_year = 2050
        snaps = run_simulation(default_inputs)
        payments = [s.sepp_payment for s in snaps if s.sepp_payment > 0]
        assert len(set(round(p, 2) for p in payments)) == 1

    def test_sepp_stops_after_required_period(self, default_inputs):
        """SEPP runs until LATER of start+4 or age 59."""
        default_inputs.user.birth_year = 1975
        default_inputs.sepp = SEPPPlan(
            enabled=True,
            start_year=2030,
            account="user",
            interest_rate=0.05,
        )
        default_inputs.end_year = 2050
        snaps = run_simulation(default_inputs)
        s2034 = snap_year(snaps, 2034)
        s2035 = snap_year(snaps, 2035)
        assert s2034.sepp_payment > 0
        assert s2035.sepp_payment == 0


class TestRMD:
    def test_no_rmd_before_73(self, default_inputs):
        snaps = run_simulation(default_inputs)
        for s in snaps:
            if s.user_age < 73 and s.spouse_age < 73:
                assert s.user_rmd == 0.0
                assert s.spouse_rmd == 0.0

    def test_rmd_starts_at_73(self, default_inputs):
        default_inputs.user.birth_year = 1953
        default_inputs.end_year = 2030
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.user_rmd > 0

    def test_rmd_uses_prior_year_balance(self, default_inputs):
        """RMD for 2026 uses the balance as of start of 2026 (= end of 2025 = initial balance)."""
        default_inputs.user.birth_year = 1953
        default_inputs.accounts.user_401k_pretax = 265_000
        default_inputs.accounts.user_trad_ira = 0
        default_inputs.end_year = 2027
        snaps = run_simulation(default_inputs)
        s = snap_year(snaps, 2026)
        assert s.user_rmd == pytest.approx(10_000, rel=0.01)
