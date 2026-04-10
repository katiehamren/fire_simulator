"""Pure year-level income, contribution, tax, and expense calculations (no account mutation)."""

from dataclasses import dataclass

from .aca import estimate_aca_premium
from .models import AccountBalances, SimInputs, CURRENT_YEAR, annual_401k_ee_limit, annual_hsa_family_limit, rmd_factor
from .tax_calc import compute_federal_tax, compute_se_tax
from .year_state import SeppRuntime

# IRS 401(k) combined limit (employee + employer); conservative ceiling for solo ER.
SOLO_401K_TOTAL_LIMIT = 70_000


def compute_w2_401k(mode: str, amount: float, pct: float, w2: float, ee_limit: int) -> float:
    """Compute W2 401(k) employee contribution for the year based on the chosen mode."""
    if mode == "dollar":
        return min(amount, ee_limit, w2)
    if mode == "percent":
        return min(pct * w2, ee_limit, w2)
    return min(ee_limit, w2)


def sepp_amortization(balance: float, n_years: float, rate: float) -> float:
    """Amortization method: fixed annual payment over n_years years."""
    n = max(n_years, 5.0)
    if rate <= 0 or n <= 0:
        return balance / max(n, 1.0)
    return balance * rate / (1 - (1 + rate) ** -n)


@dataclass(frozen=True)
class YearIncome:
    user_w2: float
    spouse_w2: float
    sole_prop: float
    rental_cf: float
    rental_taxable: float
    user_age: int
    spouse_age: int
    inflation_factor: float


def build_year_income(inputs: SimInputs, year: int) -> YearIncome:
    y = year - CURRENT_YEAR
    user_w2 = 0.0
    if year < inputs.user.w2_stop_year:
        user_w2 = inputs.user_w2.gross_annual * (1 + inputs.user_w2.annual_raise_rate) ** y
    spouse_w2 = 0.0
    if year < inputs.spouse.w2_stop_year:
        spouse_w2 = inputs.spouse_w2.gross_annual * (1 + inputs.spouse_w2.annual_raise_rate) ** y
    sole_prop = (
        inputs.sole_prop.net_annual * (1 + inputs.sole_prop.growth_rate) ** y
        if y < inputs.sole_prop.years_active
        else 0.0
    )
    annual_gross_rent = inputs.rental.monthly_gross_rent * 12 * (1 + inputs.rental.rent_growth_rate) ** y
    effective_gross = annual_gross_rent * (1 - inputs.rental.vacancy_rate)
    operating_expenses = annual_gross_rent * inputs.rental.expense_ratio
    rental_cf = effective_gross - operating_expenses
    annual_depreciation = (
        (inputs.rental.property_value * (1.0 - inputs.rental.land_value_pct)) / 27.5
    )
    rental_taxable = max(0.0, rental_cf - annual_depreciation)
    return YearIncome(
        user_w2=user_w2,
        spouse_w2=spouse_w2,
        sole_prop=sole_prop,
        rental_cf=rental_cf,
        rental_taxable=rental_taxable,
        user_age=year - inputs.user.birth_year,
        spouse_age=year - inputs.spouse.birth_year,
        inflation_factor=(1 + inputs.assumptions.inflation_rate) ** y,
    )


@dataclass
class ContributionAmounts:
    user_has_earned: bool
    spouse_has_earned: bool
    ee_limit: int
    user_401k_contrib: float
    spouse_401k_contrib: float
    user_ira_contrib: float
    spouse_ira_contrib: float
    hsa_contrib: float
    solo_ee_pretax: float
    solo_ee_roth: float
    solo_er_pretax: float
    solo_er_roth: float


def build_contribution_amounts(inputs: SimInputs, year: int, inc: YearIncome) -> ContributionAmounts:
    y = year - CURRENT_YEAR
    user_has_earned = (inc.user_w2 > 0) or (inc.sole_prop > 0)
    spouse_has_earned = inc.spouse_w2 > 0
    ee_limit = annual_401k_ee_limit(year)
    user_401k_contrib = (
        compute_w2_401k(
            inputs.contributions.user_401k_mode,
            inputs.contributions.user_401k_amount,
            inputs.contributions.user_401k_pct,
            inc.user_w2, ee_limit,
        ) if year < inputs.user.w2_stop_year else 0.0
    )
    spouse_401k_contrib = (
        compute_w2_401k(
            inputs.contributions.spouse_401k_mode,
            inputs.contributions.spouse_401k_amount,
            inputs.contributions.spouse_401k_pct,
            inc.spouse_w2, ee_limit,
        ) if year < inputs.spouse.w2_stop_year else 0.0
    )
    user_ira_contrib = inputs.contributions.user_ira if user_has_earned else 0.0
    spouse_ira_contrib = inputs.contributions.spouse_ira if spouse_has_earned else 0.0

    any_w2 = (inc.user_w2 > 0) or (inc.spouse_w2 > 0)
    hsa_contrib = 0.0
    if any_w2:
        hsa_cap = annual_hsa_family_limit(year, inputs.assumptions.inflation_rate)
        if inputs.contributions.hsa_mode == "max":
            hsa_contrib = hsa_cap
        elif inputs.contributions.hsa_annual > 0:
            hsa_contrib = min(inputs.contributions.hsa_annual, hsa_cap)

    solo_ee_pretax = solo_ee_roth = solo_er_pretax = solo_er_roth = 0.0
    solo_active = y < inputs.sole_prop.years_active and inc.sole_prop > 0
    if solo_active:
        # IRS employee elective deferral limit is shared across all 401(k) plans.
        # Subtract whatever was already used by the W2 plan to get remaining room.
        remaining_ee_room = max(0.0, ee_limit - user_401k_contrib)
        ee = min(inputs.contributions.user_solo_401k_ee, remaining_ee_room, inc.sole_prop)
        er = min(
            inputs.contributions.user_solo_401k_er_pct * inc.sole_prop,
            max(0.0, SOLO_401K_TOTAL_LIMIT - ee),
        )
    else:
        ee = 0.0
        er = 0.0
    if ee > 0:
        if inputs.contributions.user_solo_401k_ee_type == "roth":
            solo_ee_roth, solo_ee_pretax = ee, 0.0
        else:
            solo_ee_pretax, solo_ee_roth = ee, 0.0
    if er > 0:
        if inputs.contributions.user_solo_401k_er_type == "roth":
            solo_er_roth, solo_er_pretax = er, 0.0
        else:
            solo_er_pretax, solo_er_roth = er, 0.0

    return ContributionAmounts(
        user_has_earned=user_has_earned,
        spouse_has_earned=spouse_has_earned,
        ee_limit=ee_limit,
        user_401k_contrib=user_401k_contrib,
        spouse_401k_contrib=spouse_401k_contrib,
        user_ira_contrib=user_ira_contrib,
        spouse_ira_contrib=spouse_ira_contrib,
        hsa_contrib=hsa_contrib,
        solo_ee_pretax=solo_ee_pretax,
        solo_ee_roth=solo_ee_roth,
        solo_er_pretax=solo_er_pretax,
        solo_er_roth=solo_er_roth,
    )


def compute_sepp_payment_for_year(
    inputs: SimInputs,
    year: int,
    accts: AccountBalances,
    sepp_runtime: SeppRuntime,
) -> float:
    if not inputs.sepp.enabled:
        return 0.0
    person_birth = (
        inputs.user.birth_year if inputs.sepp.account == "user" else inputs.spouse.birth_year
    )
    sepp_end = max(inputs.sepp.start_year + 4, person_birth + 59)
    if not (inputs.sepp.start_year <= year <= sepp_end):
        return 0.0
    if year == inputs.sepp.start_year:
        if inputs.sepp.account == "user":
            bal = accts.user_401k_pretax + accts.user_trad_ira
        else:
            bal = accts.spouse_401k_pretax + accts.spouse_trad_ira
        n_years = sepp_end - inputs.sepp.start_year + 1
        sepp_runtime.annual = sepp_amortization(bal, n_years, inputs.sepp.interest_rate)
    return sepp_runtime.annual


def compute_rmd_after_sepp_credit(
    user_age: int,
    spouse_age: int,
    user_rmd_base: float,
    spouse_rmd_base: float,
    sepp_payment: float,
    sepp_account: str,
) -> tuple[float, float]:
    u_rmd_factor = rmd_factor(user_age)
    s_rmd_factor = rmd_factor(spouse_age)
    user_rmd = (
        min(user_rmd_base / u_rmd_factor, user_rmd_base) if u_rmd_factor > 0 else 0.0
    )
    spouse_rmd = (
        min(spouse_rmd_base / s_rmd_factor, spouse_rmd_base) if s_rmd_factor > 0 else 0.0
    )
    if sepp_account == "user":
        user_rmd = max(0.0, user_rmd - sepp_payment)
    else:
        spouse_rmd = max(0.0, spouse_rmd - sepp_payment)
    return user_rmd, spouse_rmd


def compute_conversion_amount(inputs: SimInputs, year: int, accts: AccountBalances) -> float:
    if not (
        inputs.roth_conversion.enabled
        and inputs.roth_conversion.start_year <= year <= inputs.roth_conversion.end_year
    ):
        return 0.0
    if inputs.roth_conversion.source == "user":
        available = accts.user_401k_pretax + accts.user_trad_ira
    else:
        available = accts.spouse_401k_pretax + accts.spouse_trad_ira
    return min(inputs.roth_conversion.annual_amount, max(0.0, available))


@dataclass(frozen=True)
class TaxTotals:
    se_tax: float
    se_deduction: float
    gross_taxable: float
    taxes_on_income: float
    conversion_tax: float
    taxes_ord: float
    total_net_income: float


def compute_tax_totals(
    inc: YearIncome,
    ca: ContributionAmounts,
    sepp_payment: float,
    user_rmd: float,
    spouse_rmd: float,
    conversion_amount: float,
    year: int,
    infl: float,
) -> TaxTotals:
    se_tax = compute_se_tax(inc.sole_prop, inc.user_w2, year)
    se_deduction = se_tax / 2.0
    gross_taxable = (
        (inc.user_w2 - ca.user_401k_contrib)
        + (inc.spouse_w2 - ca.spouse_401k_contrib)
        + inc.sole_prop - ca.solo_ee_pretax - ca.solo_er_pretax - se_deduction
        + sepp_payment
        + user_rmd + spouse_rmd
        + inc.rental_taxable
        - ca.hsa_contrib
    )
    taxes_on_income = compute_federal_tax(gross_taxable, year, infl)
    if conversion_amount > 0:
        conversion_tax = (
            compute_federal_tax(gross_taxable + conversion_amount, year, infl)
            - taxes_on_income
        )
    else:
        conversion_tax = 0.0
    taxes_ord = taxes_on_income + conversion_tax + se_tax
    net_taxable = gross_taxable - taxes_on_income
    total_net_income = net_taxable - se_tax + (inc.rental_cf - inc.rental_taxable)
    return TaxTotals(
        se_tax=se_tax,
        se_deduction=se_deduction,
        gross_taxable=gross_taxable,
        taxes_on_income=taxes_on_income,
        conversion_tax=conversion_tax,
        taxes_ord=taxes_ord,
        total_net_income=total_net_income,
    )



def compute_magi_pre_withdrawal(
    inc: YearIncome,
    ca: ContributionAmounts,
    tax: TaxTotals,
    sepp_payment: float,
    user_rmd: float,
    spouse_rmd: float,
    conversion_amount: float,
    brokerage_gains_realized: float,
) -> float:
    """MAGI (ACA); add brokerage_gains_realized after the withdrawal pass for reporting."""
    return (
        inc.user_w2
        + inc.spouse_w2
        - ca.user_401k_contrib
        - ca.spouse_401k_contrib
        - ca.hsa_contrib
        + inc.sole_prop
        - ca.solo_ee_pretax
        - ca.solo_er_pretax
        + inc.rental_taxable
        + sepp_payment
        + user_rmd
        + spouse_rmd
        + conversion_amount
        + brokerage_gains_realized
        - tax.se_deduction
    )


def compute_spending(inputs: SimInputs, year: int, inflation_factor: float) -> float:
    spending = inputs.assumptions.annual_spending_today * inflation_factor
    if inputs.spending_override is not None and year >= inputs.spending_override.change_year:
        spending *= 1 + inputs.spending_override.change_pct
    return spending


@dataclass(frozen=True)
class HealthcarePreHsa:
    on_employer_hc: bool
    healthcare_gross: float
    aca_premium: float
    aca_subsidy: float
    aca_fpl_pct: float


def compute_healthcare_before_hsa_draw(
    inputs: SimInputs,
    year: int,
    inflation_factor: float,
    magi: float,
    user_w2: float,
    spouse_w2: float,
) -> HealthcarePreHsa:
    on_employer_hc = (user_w2 > 0) or (spouse_w2 > 0)
    if on_employer_hc:
        return HealthcarePreHsa(
            on_employer_hc=True,
            healthcare_gross=0.0,
            aca_premium=0.0,
            aca_subsidy=0.0,
            aca_fpl_pct=0.0,
        )
    if inputs.assumptions.healthcare_mode == "flat":
        hc = inputs.assumptions.annual_healthcare_flat * inflation_factor
        return HealthcarePreHsa(
            on_employer_hc=False,
            healthcare_gross=hc,
            aca_premium=hc,
            aca_subsidy=0.0,
            aca_fpl_pct=0.0,
        )
    aca_result = estimate_aca_premium(
        magi=magi,
        year=year,
        inflation_rate=inputs.assumptions.inflation_rate,
        benchmark_override=inputs.assumptions.aca_benchmark_override or None,
        arp_extended=inputs.assumptions.aca_arp_extended,
    )
    aca_premium = aca_result["premium"]
    healthcare = aca_premium + inputs.assumptions.aca_additional_oop * inflation_factor
    return HealthcarePreHsa(
        on_employer_hc=False,
        healthcare_gross=healthcare,
        aca_premium=aca_premium,
        aca_subsidy=aca_result["subsidy"],
        aca_fpl_pct=aca_result["fpl_pct"],
    )


def compute_surplus_before_brokerage_components(
    total_net_income: float,
    spending: float,
    healthcare_net: float,
    user_ira_contrib: float,
    spouse_ira_contrib: float,
    hsa_contrib: float,
    solo_ee_roth: float,
    solo_er_roth: float,
    conversion_tax: float,
) -> tuple[float, float]:
    total_expenses = spending + healthcare_net
    surplus = (
        total_net_income
        - total_expenses
        - user_ira_contrib
        - spouse_ira_contrib
        - hsa_contrib
        - solo_ee_roth
        - solo_er_roth
        - conversion_tax
    )
    return total_expenses, surplus
