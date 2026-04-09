"""Account balance mutators for the simulation year loop (order matches simulator)."""

from __future__ import annotations

from .models import AccountBalances, SimInputs
from .tax_calc import compute_ltcg_tax


def apply_hsa_for_healthcare(accts: AccountBalances, healthcare_gross: float) -> tuple[float, float]:
    """Pay healthcare from HSA first. Returns (hsa_drawn, healthcare_remaining). Mutates accts.hsa."""
    hsa_drawn = 0.0
    healthcare = healthcare_gross
    if healthcare > 0 and accts.hsa > 0:
        hsa_drawn = min(accts.hsa, healthcare)
        accts.hsa -= hsa_drawn
        healthcare -= hsa_drawn
    return hsa_drawn, healthcare


def apply_w2_and_ira_contributions(
    accts: AccountBalances,
    user_401k: float,
    spouse_401k: float,
    user_ira: float,
    spouse_ira: float,
    user_has_earned: bool,
    spouse_has_earned: bool,
) -> None:
    accts.user_401k_pretax += user_401k
    accts.spouse_401k_pretax += spouse_401k
    if user_has_earned:
        accts.user_trad_ira += user_ira
    if spouse_has_earned:
        accts.spouse_trad_ira += spouse_ira


def apply_solo_401k_contributions(
    accts: AccountBalances,
    solo_ee_pretax: float,
    solo_ee_roth: float,
    solo_er_pretax: float,
    solo_er_roth: float,
) -> None:
    accts.user_401k_pretax += solo_ee_pretax + solo_er_pretax
    accts.user_401k_roth += solo_ee_roth + solo_er_roth


def apply_hsa_contribution(accts: AccountBalances, hsa_contrib: float) -> None:
    accts.hsa += hsa_contrib


def execute_roth_conversion(
    accts: AccountBalances,
    inputs: SimInputs,
    conversion_amount: float,
    year: int,
    conversion_history: list[tuple[int, float]],
) -> None:
    if conversion_amount <= 0:
        return
    if inputs.roth_conversion.source == "user":
        total_pretax = accts.user_401k_pretax + accts.user_trad_ira
        if total_pretax > 0:
            k_frac = accts.user_401k_pretax / total_pretax
            accts.user_401k_pretax -= conversion_amount * k_frac
            accts.user_trad_ira -= conversion_amount * (1 - k_frac)
        accts.user_roth_ira += conversion_amount
    else:
        total_pretax = accts.spouse_401k_pretax + accts.spouse_trad_ira
        if total_pretax > 0:
            h_frac = accts.spouse_401k_pretax / total_pretax
            accts.spouse_401k_pretax -= conversion_amount * h_frac
            accts.spouse_trad_ira -= conversion_amount * (1 - h_frac)
        accts.spouse_roth_ira += conversion_amount
    conversion_history.append((year, conversion_amount))


def execute_sepp_withdrawal(
    accts: AccountBalances,
    inputs: SimInputs,
    sepp_payment: float,
) -> None:
    if sepp_payment <= 0:
        return
    if inputs.sepp.account == "user":
        avail = accts.user_401k_pretax + accts.user_trad_ira
        draw = min(sepp_payment, avail)
        if avail > 0:
            k_frac = accts.user_401k_pretax / avail
            accts.user_401k_pretax -= draw * k_frac
            accts.user_trad_ira -= draw * (1 - k_frac)
    else:
        avail = accts.spouse_401k_pretax + accts.spouse_trad_ira
        draw = min(sepp_payment, avail)
        if avail > 0:
            h_frac = accts.spouse_401k_pretax / avail
            accts.spouse_401k_pretax -= draw * h_frac
            accts.spouse_trad_ira -= draw * (1 - h_frac)


def execute_rmd_withdrawals(
    accts: AccountBalances,
    user_rmd: float,
    spouse_rmd: float,
) -> None:
    if user_rmd > 0:
        avail = accts.user_401k_pretax + accts.user_trad_ira
        draw = min(user_rmd, avail)
        if avail > 0:
            k_frac = accts.user_401k_pretax / avail
            accts.user_401k_pretax -= draw * k_frac
            accts.user_trad_ira -= draw * (1 - k_frac)
    if spouse_rmd > 0:
        avail = accts.spouse_401k_pretax + accts.spouse_trad_ira
        draw = min(spouse_rmd, avail)
        if avail > 0:
            h_frac = accts.spouse_401k_pretax / avail
            accts.spouse_401k_pretax -= draw * h_frac
            accts.spouse_trad_ira -= draw * (1 - h_frac)


def apply_brokerage_contribution(
    accts: AccountBalances,
    brokerage_basis: list[float],
    brokerage_contrib: float,
) -> None:
    accts.brokerage += brokerage_contrib
    brokerage_basis[0] += brokerage_contrib


def grow_investment_accounts(accts: AccountBalances, r: float) -> None:
    accts.user_401k_pretax *= 1 + r
    accts.user_401k_roth *= 1 + r
    accts.user_trad_ira *= 1 + r
    accts.user_roth_ira *= 1 + r
    accts.spouse_401k_pretax *= 1 + r
    accts.spouse_401k_roth *= 1 + r
    accts.spouse_trad_ira *= 1 + r
    accts.spouse_roth_ira *= 1 + r
    accts.brokerage *= 1 + r
    accts.hsa *= 1 + r


def resolve_cashflow_deficit(
    accts: AccountBalances,
    brokerage_basis: list[float],
    net_cf: float,
    gross_taxable: float,
    year: int,
    infl: float,
    user_age: float,
    spouse_age: float,
) -> tuple[float, float, float, float, bool]:
    """If net_cf > 0, add to cash. Else cover deficit. Returns (
        net_cf_out,
        brokerage_gains_realized,
        ltcg_tax_total,
        early_withdrawal,
        plan_solvent,
    )."""
    early_withdrawal = 0.0
    plan_solvent = True
    brokerage_gains_realized = 0.0
    ltcg_tax_total = 0.0
    if net_cf > 0:
        accts.cash += net_cf
        return net_cf, brokerage_gains_realized, ltcg_tax_total, early_withdrawal, plan_solvent

    deficit = -net_cf
    draw = min(accts.cash, deficit)
    accts.cash -= draw
    deficit -= draw

    if deficit > 0 and accts.brokerage > 0:
        basis_ref = brokerage_basis[0]
        while deficit > 0 and accts.brokerage > 0:
            draw = min(accts.brokerage, deficit)
            basis_frac = basis_ref / accts.brokerage if accts.brokerage > 0 else 0.0
            gains_fraction = 1.0 - basis_frac
            realized_gains = draw * gains_fraction
            ltcg = compute_ltcg_tax(gross_taxable, realized_gains, year, infl)
            brokerage_gains_realized += realized_gains
            ltcg_tax_total += ltcg
            accts.brokerage -= draw
            basis_ref -= draw * basis_frac
            deficit -= draw - ltcg
        brokerage_basis[0] = basis_ref

    if deficit > 0:
        total_roth = accts.user_roth_ira + accts.spouse_roth_ira
        if total_roth > 0:
            draw = min(total_roth, deficit)
            user_share = accts.user_roth_ira / total_roth
            accts.user_roth_ira -= draw * user_share
            accts.spouse_roth_ira -= draw * (1 - user_share)
            deficit -= draw

    penalty_free_order: list[str] = []
    penalized_order: list[str] = []
    for attr, age in [
        ("user_401k_pretax", user_age),
        ("user_trad_ira", user_age),
        ("spouse_401k_pretax", spouse_age),
        ("spouse_trad_ira", spouse_age),
    ]:
        if age >= 59.5:
            penalty_free_order.append(attr)
        else:
            penalized_order.append(attr)

    for attr in penalty_free_order:
        if deficit > 0:
            bal = getattr(accts, attr)
            draw = min(bal, deficit)
            setattr(accts, attr, bal - draw)
            deficit -= draw

    for attr in penalized_order:
        if deficit > 0:
            bal = getattr(accts, attr)
            draw = min(bal, deficit)
            setattr(accts, attr, bal - draw)
            early_withdrawal += draw
            deficit -= draw

    if deficit > 0:
        plan_solvent = False

    return net_cf, brokerage_gains_realized, ltcg_tax_total, early_withdrawal, plan_solvent
