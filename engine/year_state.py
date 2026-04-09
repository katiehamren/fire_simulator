"""Mutable runtime state and per-year workspace for the retirement simulation loop."""

from dataclasses import dataclass


@dataclass
class SeppRuntime:
    """Fixed SEPP payment, recomputed on the plan start year from account balances."""

    annual: float = 0.0


@dataclass
class YearScratch:
    """All quantities computed for one calendar year before / including snapshot assembly."""

    year: int = 0
    y: int = 0
    user_age: int = 0
    spouse_age: int = 0
    inflation_factor: float = 1.0

    user_w2: float = 0.0
    spouse_w2: float = 0.0
    sole_prop: float = 0.0
    rental_cf: float = 0.0
    rental_taxable: float = 0.0

    user_has_earned: bool = False
    spouse_has_earned: bool = False
    ee_limit: int = 0

    user_401k_contrib: float = 0.0
    spouse_401k_contrib: float = 0.0
    user_ira_contrib: float = 0.0
    spouse_ira_contrib: float = 0.0
    hsa_contrib: float = 0.0
    solo_ee_pretax: float = 0.0
    solo_ee_roth: float = 0.0
    solo_er_pretax: float = 0.0
    solo_er_roth: float = 0.0

    sepp_payment: float = 0.0
    user_rmd: float = 0.0
    spouse_rmd: float = 0.0
    conversion_amount: float = 0.0

    infl: float = 0.0
    se_tax: float = 0.0
    se_deduction: float = 0.0
    gross_taxable: float = 0.0
    taxes_on_income: float = 0.0
    conversion_tax: float = 0.0
    taxes_ord: float = 0.0
    total_net_income: float = 0.0

    magi: float = 0.0
    spending: float = 0.0
    on_employer_hc: bool = False
    aca_premium: float = 0.0
    aca_subsidy: float = 0.0
    aca_fpl_pct: float = 0.0
    healthcare: float = 0.0
    total_expenses: float = 0.0
    hsa_for_healthcare: float = 0.0

    surplus_before_brokerage: float = 0.0
    brokerage_contrib: float = 0.0
    net_cf: float = 0.0
    early_withdrawal: float = 0.0
    plan_solvent: bool = True
    brokerage_gains_realized: float = 0.0
    ltcg_tax_total: float = 0.0
    taxes_paid: float = 0.0

    accessible_roth_seasoned: float = 0.0
    total_ret: float = 0.0
    total_liquid: float = 0.0
    total_nw: float = 0.0

    # RMD bases (start of year); stored for clarity / debugging
    user_rmd_base: float = 0.0
    spouse_rmd_base: float = 0.0

