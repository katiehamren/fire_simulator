"""
Year-by-year retirement simulation engine.

Simplified assumptions:
- Federal ordinary tax: MFJ brackets (base config year) with thresholds and standard deduction inflated
  by the plan inflation rate; ordinary income includes taxable rental (NOI minus depreciation), SE tax
  half-deduction; self-employment tax on sole prop; LTCG on taxable brokerage withdrawals
- Roth conversion tax is computed separately and deducted from surplus
- Rental cashflow is included post-expense (NOI - mortgage)
- Market returns applied uniformly to all investment accounts
- Withdrawal order: cash → brokerage → Roth IRA → penalty-free retirement accts → penalized retirement accts
- 401k/IRA is "penalty-free" once the account holder turns 59.5
- Roth IRA treated as fully accessible (simplification; in reality only contributions + seasoned conversions)
- Pre-tax 401k contributions reduce taxable income and are deducted from gross pay
- Solo 401(k) pre-tax employee + employer profit-sharing reduce SE taxable income
- Solo 401(k) Roth employee contributions come from post-tax surplus (deducted from surplus, like IRA)
- IRA contributions are deducted from post-tax surplus before brokerage allocation
- HSA: optional contribution while any household member has W2 — **max** mode uses the projected IRS
  family HDHP limit each year, **dollar** mode uses a fixed amount (capped at that limit); reduces ordinary
  income and MAGI; funded from surplus; credited to HSA before growth
- Roth conversion: moves from pre-tax → Roth; triggers separate conversion tax deducted from surplus
- SEPP (72t): fixed annual payment computed once at start year; added to ordinary taxable income
- RMDs: mandatory from pre-tax 401k + Traditional IRA starting at age 73; computed from prior
  year-end balance using IRS Uniform Lifetime Table; added to ordinary taxable income;
  Roth 401k RMDs eliminated by SECURE 2.0 (2024+); Roth IRA never has RMDs for original owner
"""
import copy
from typing import List

from .account_ops import (
    apply_brokerage_contribution,
    apply_hsa_contribution,
    apply_hsa_for_healthcare,
    apply_solo_401k_contributions,
    apply_w2_and_ira_contributions,
    execute_rmd_withdrawals,
    execute_roth_conversion,
    execute_sepp_withdrawal,
    grow_investment_accounts,
    resolve_cashflow_deficit,
)
from .models import SimInputs, YearSnapshot
from .models import CURRENT_YEAR
from .tax_calc import effective_rate, marginal_rate
from .year_compute import (
    build_contribution_amounts,
    build_year_income,
    compute_conversion_amount,
    compute_healthcare_before_hsa_draw,
    compute_magi_pre_withdrawal,
    compute_rmd_after_sepp_credit,
    compute_sepp_payment_for_year,
    compute_spending,
    compute_surplus_before_brokerage_components,
    compute_tax_totals,
    compute_w2_401k,
)
from .year_state import SeppRuntime, YearScratch


_compute_w2_401k = compute_w2_401k


def run_simulation(inputs: SimInputs) -> List[YearSnapshot]:
    snapshots: List[YearSnapshot] = []

    accts = copy.deepcopy(inputs.accounts)
    sepp_rt = SeppRuntime()
    conversion_history: list[tuple[int, float]] = []
    brokerage_basis: list[float] = [accts.brokerage * inputs.assumptions.brokerage_cost_basis_pct]

    for year in range(CURRENT_YEAR, inputs.end_year + 1):
        scratch = YearScratch()
        scratch.year = year
        scratch.y = year - CURRENT_YEAR
        inc = build_year_income(inputs, year)
        scratch.user_age = inc.user_age
        scratch.spouse_age = inc.spouse_age
        scratch.inflation_factor = inc.inflation_factor
        scratch.user_w2 = inc.user_w2
        scratch.spouse_w2 = inc.spouse_w2
        scratch.sole_prop = inc.sole_prop
        scratch.rental_cf = inc.rental_cf
        scratch.rental_taxable = inc.rental_taxable

        scratch.user_rmd_base = accts.user_401k_pretax + accts.user_trad_ira
        scratch.spouse_rmd_base = accts.spouse_401k_pretax + accts.spouse_trad_ira

        ca = build_contribution_amounts(inputs, year, inc)
        scratch.user_has_earned = ca.user_has_earned
        scratch.spouse_has_earned = ca.spouse_has_earned
        scratch.ee_limit = ca.ee_limit
        scratch.user_401k_contrib = ca.user_401k_contrib
        scratch.spouse_401k_contrib = ca.spouse_401k_contrib
        scratch.user_ira_contrib = ca.user_ira_contrib
        scratch.spouse_ira_contrib = ca.spouse_ira_contrib
        scratch.hsa_contrib = ca.hsa_contrib
        scratch.solo_ee_pretax = ca.solo_ee_pretax
        scratch.solo_ee_roth = ca.solo_ee_roth
        scratch.solo_er_pretax = ca.solo_er_pretax
        scratch.solo_er_roth = ca.solo_er_roth

        scratch.sepp_payment = compute_sepp_payment_for_year(inputs, year, accts, sepp_rt)
        scratch.user_rmd, scratch.spouse_rmd = compute_rmd_after_sepp_credit(
            inc.user_age,
            inc.spouse_age,
            scratch.user_rmd_base,
            scratch.spouse_rmd_base,
            scratch.sepp_payment,
            inputs.sepp.account,
        )
        scratch.conversion_amount = compute_conversion_amount(inputs, year, accts)

        infl = inputs.assumptions.inflation_rate
        scratch.infl = infl
        tax = compute_tax_totals(
            inc,
            ca,
            scratch.sepp_payment,
            scratch.user_rmd,
            scratch.spouse_rmd,
            scratch.conversion_amount,
            year,
            infl,
        )
        scratch.se_tax = tax.se_tax
        scratch.se_deduction = tax.se_deduction
        scratch.gross_taxable = tax.gross_taxable
        scratch.taxes_on_income = tax.taxes_on_income
        scratch.conversion_tax = tax.conversion_tax
        scratch.taxes_ord = tax.taxes_ord
        scratch.total_net_income = tax.total_net_income

        scratch.magi = compute_magi_pre_withdrawal(
            inc,
            ca,
            tax,
            scratch.sepp_payment,
            scratch.user_rmd,
            scratch.spouse_rmd,
            scratch.conversion_amount,
            0.0,
        )

        scratch.spending = compute_spending(inputs, year, inc.inflation_factor)
        hc_pre = compute_healthcare_before_hsa_draw(
            inputs,
            year,
            inc.inflation_factor,
            scratch.magi,
            inc.user_w2,
            inc.spouse_w2,
        )
        scratch.on_employer_hc = hc_pre.on_employer_hc
        scratch.aca_premium = hc_pre.aca_premium
        scratch.aca_subsidy = hc_pre.aca_subsidy
        scratch.aca_fpl_pct = hc_pre.aca_fpl_pct
        scratch.hsa_for_healthcare, healthcare_net = apply_hsa_for_healthcare(
            accts, hc_pre.healthcare_gross
        )
        scratch.healthcare = healthcare_net

        scratch.total_expenses, scratch.surplus_before_brokerage = (
            compute_surplus_before_brokerage_components(
                scratch.total_net_income,
                scratch.spending,
                healthcare_net,
                ca.user_ira_contrib,
                ca.spouse_ira_contrib,
                ca.hsa_contrib,
                ca.solo_ee_roth,
                ca.solo_er_roth,
                tax.conversion_tax,
            )
        )

        apply_w2_and_ira_contributions(
            accts,
            ca.user_401k_contrib,
            ca.spouse_401k_contrib,
            ca.user_ira_contrib,
            ca.spouse_ira_contrib,
            ca.user_has_earned,
            ca.spouse_has_earned,
        )
        apply_solo_401k_contributions(
            accts,
            ca.solo_ee_pretax,
            ca.solo_ee_roth,
            ca.solo_er_pretax,
            ca.solo_er_roth,
        )
        apply_hsa_contribution(accts, ca.hsa_contrib)
        execute_roth_conversion(
            accts, inputs, scratch.conversion_amount, year, conversion_history
        )
        execute_sepp_withdrawal(accts, inputs, scratch.sepp_payment)
        execute_rmd_withdrawals(accts, scratch.user_rmd, scratch.spouse_rmd)

        scratch.brokerage_contrib = min(
            inputs.contributions.brokerage,
            max(0.0, scratch.surplus_before_brokerage),
        )
        apply_brokerage_contribution(accts, brokerage_basis, scratch.brokerage_contrib)

        grow_investment_accounts(accts, inputs.assumptions.market_return_rate)

        scratch.net_cf = scratch.surplus_before_brokerage - scratch.brokerage_contrib
        (
            _,
            scratch.brokerage_gains_realized,
            scratch.ltcg_tax_total,
            scratch.early_withdrawal,
            scratch.plan_solvent,
        ) = resolve_cashflow_deficit(
            accts,
            brokerage_basis,
            scratch.net_cf,
            scratch.gross_taxable,
            year,
            infl,
            float(scratch.user_age),
            float(scratch.spouse_age),
        )

        scratch.taxes_paid = scratch.taxes_ord + scratch.ltcg_tax_total
        scratch.magi += scratch.brokerage_gains_realized

        scratch.accessible_roth_seasoned = sum(
            amt for yr, amt in conversion_history if yr <= year - 5
        )

        scratch.total_ret = (
            accts.user_401k_pretax
            + accts.user_401k_roth
            + accts.user_trad_ira
            + accts.user_roth_ira
            + accts.spouse_401k_pretax
            + accts.spouse_401k_roth
            + accts.spouse_trad_ira
            + accts.spouse_roth_ira
        )
        scratch.total_liquid = accts.brokerage + accts.cash + accts.hsa
        scratch.total_nw = scratch.total_ret + scratch.total_liquid

        snapshots.append(
            YearSnapshot(
                year=year,
                user_age=scratch.user_age,
                spouse_age=scratch.spouse_age,
                user_w2_gross=scratch.user_w2,
                spouse_w2_gross=scratch.spouse_w2,
                sole_prop_net=scratch.sole_prop,
                rental_cashflow=scratch.rental_cf,
                gross_taxable_income=scratch.gross_taxable,
                taxes_paid=scratch.taxes_paid,
                total_net_income=scratch.total_net_income,
                spending=scratch.spending,
                healthcare=scratch.healthcare,
                total_expenses=scratch.total_expenses,
                net_cashflow=scratch.net_cf,
                user_401k_pretax=accts.user_401k_pretax,
                user_401k_roth=accts.user_401k_roth,
                user_trad_ira=accts.user_trad_ira,
                user_roth_ira=accts.user_roth_ira,
                spouse_401k_pretax=accts.spouse_401k_pretax,
                spouse_401k_roth=accts.spouse_401k_roth,
                spouse_trad_ira=accts.spouse_trad_ira,
                spouse_roth_ira=accts.spouse_roth_ira,
                brokerage=accts.brokerage,
                hsa=accts.hsa,
                cash=accts.cash,
                total_retirement_accounts=scratch.total_ret,
                total_liquid_non_retirement=scratch.total_liquid,
                total_net_worth=scratch.total_nw,
                on_employer_healthcare=scratch.on_employer_hc,
                early_withdrawal_amount=scratch.early_withdrawal,
                plan_solvent=scratch.plan_solvent,
                roth_conversion_amount=scratch.conversion_amount,
                sepp_payment=scratch.sepp_payment,
                accessible_roth_seasoned=scratch.accessible_roth_seasoned,
                user_rmd=scratch.user_rmd,
                spouse_rmd=scratch.spouse_rmd,
                marginal_tax_rate=marginal_rate(scratch.gross_taxable, year, infl),
                effective_tax_rate=effective_rate(scratch.gross_taxable, year, infl),
                se_tax=scratch.se_tax,
                rental_taxable_income=scratch.rental_taxable,
                brokerage_gains_realized=scratch.brokerage_gains_realized,
                ltcg_tax=scratch.ltcg_tax_total,
                magi=scratch.magi,
                aca_premium=scratch.aca_premium,
                aca_subsidy=scratch.aca_subsidy,
                aca_fpl_pct=scratch.aca_fpl_pct,
                hsa_for_healthcare=scratch.hsa_for_healthcare,
                hsa_contribution=scratch.hsa_contrib,
            )
        )

    return snapshots
