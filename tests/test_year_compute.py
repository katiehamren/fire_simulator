"""Focused tests for pure functions in engine.year_compute."""
import pytest

from engine.models import SpendingOverride, annual_401k_ee_limit
from engine.tax_calc import compute_federal_tax
from engine.year_compute import (
    build_contribution_amounts,
    build_year_income,
    compute_rmd_after_sepp_credit,
    compute_spending,
    compute_tax_totals,
    compute_w2_401k,
)


def test_compute_w2_401k_max_respects_salary_and_limit():
    lim = annual_401k_ee_limit(2026)
    assert compute_w2_401k("max", 0, 0, 150_000, lim) == lim
    assert compute_w2_401k("max", 0, 0, 15_000, lim) == 15_000


def test_compute_w2_401k_dollar_and_percent():
    lim = annual_401k_ee_limit(2026)
    assert compute_w2_401k("dollar", 12_000, 0, 100_000, lim) == 12_000
    assert compute_w2_401k("percent", 0, 0.10, 100_000, lim) == pytest.approx(10_000)


def test_compute_rmd_credited_against_sepp_user():
    user_rmd, spouse_rmd = compute_rmd_after_sepp_credit(
        73, 73, 100_000, 80_000, 5_000.0, "user"
    )
    raw_user = min(100_000 / 26.5, 100_000)
    assert user_rmd == pytest.approx(max(0.0, raw_user - 5_000))
    raw_spouse = min(80_000 / 26.5, 80_000)
    assert spouse_rmd == pytest.approx(raw_spouse)


def test_compute_rmd_credited_against_sepp_spouse():
    user_rmd, spouse_rmd = compute_rmd_after_sepp_credit(
        73, 73, 100_000, 100_000, 4_000.0, "spouse"
    )
    raw = min(100_000 / 26.5, 100_000)
    assert spouse_rmd == pytest.approx(max(0.0, raw - 4_000))
    assert user_rmd == pytest.approx(raw)


def test_solo_401k_ee_zero_while_w2_active_er_allowed(default_inputs):
    default_inputs.contributions.user_solo_401k_ee = 20_000
    default_inputs.contributions.user_solo_401k_er_pct = 0.10
    inc = build_year_income(default_inputs, 2026)
    ca = build_contribution_amounts(default_inputs, 2026, inc)
    assert inc.user_w2 > 0
    assert ca.solo_ee_pretax == 0.0 and ca.solo_ee_roth == 0.0
    assert ca.solo_er_pretax == pytest.approx(0.10 * inc.sole_prop)


def test_compute_spending_override(default_inputs):
    default_inputs.spending_override = SpendingOverride(-0.10, 2030)
    infl = 1.0
    assert compute_spending(default_inputs, 2029, infl) == 80_000
    assert compute_spending(default_inputs, 2030, infl) == pytest.approx(72_000)


def test_compute_tax_totals_conversion_tax_is_marginal(default_inputs):
    inc = build_year_income(default_inputs, 2026)
    ca = build_contribution_amounts(default_inputs, 2026, inc)
    base = compute_tax_totals(inc, ca, 0, 0, 0, 0, 2026, 0.0)
    with_conv = compute_tax_totals(inc, ca, 0, 0, 0, 40_000, 2026, 0.0)
    assert with_conv.conversion_tax == pytest.approx(
        compute_federal_tax(base.gross_taxable + 40_000, 2026, 0.0)
        - base.taxes_on_income
    )
