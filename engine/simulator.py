"""
Year-by-year retirement simulation engine.

Simplified assumptions:
- Tax is a flat effective rate on W2 + sole prop + SEPP + RMD income (not rental)
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
- Roth conversion: moves from pre-tax → Roth; triggers separate conversion tax deducted from surplus
- SEPP (72t): fixed annual payment computed once at start year; added to ordinary taxable income
- RMDs: mandatory from pre-tax 401k + Traditional IRA starting at age 73; computed from prior
  year-end balance using IRS Uniform Lifetime Table; added to ordinary taxable income;
  Roth 401k RMDs eliminated by SECURE 2.0 (2024+); Roth IRA never has RMDs for original owner
"""
import copy
from typing import List

from .models import SimInputs, YearSnapshot, CURRENT_YEAR, annual_401k_ee_limit, rmd_factor
# IRS 401(k) combined limit (employee + employer); grows with inflation but we keep this fixed
# as a conservative ceiling — the employee-only cap (annual_401k_ee_limit) grows $500/yr.
_SOLO_401K_TOTAL_LIMIT = 70_000


def _compute_w2_401k(mode: str, amount: float, pct: float, w2: float, ee_limit: int) -> float:
    """Compute W2 401(k) employee contribution for the year based on the chosen mode."""
    if mode == "dollar":
        return min(amount, ee_limit, w2)
    elif mode == "percent":
        return min(pct * w2, ee_limit, w2)
    else:  # "max"
        return min(ee_limit, w2)


def _sepp_amortization(balance: float, n_years: float, rate: float) -> float:
    """Amortization method: fixed annual payment over n_years years."""
    n = max(n_years, 5.0)
    if rate <= 0 or n <= 0:
        return balance / max(n, 1.0)
    return balance * rate / (1 - (1 + rate) ** -n)


def run_simulation(inputs: SimInputs) -> List[YearSnapshot]:
    snapshots: List[YearSnapshot] = []

    # Mutable working state
    accts = copy.deepcopy(inputs.accounts)

    # SEPP: fixed payment computed once at start year; persists across iterations
    _sepp_annual: float = 0.0

    # Roth conversion vintage tracking: list of (year_converted, amount)
    conversion_history: list[tuple[int, float]] = []

    for year in range(CURRENT_YEAR, inputs.end_year + 1):
        y = year - CURRENT_YEAR  # years elapsed since simulation start
        user_age = year - inputs.user.birth_year
        spouse_age = year - inputs.spouse.birth_year
        inflation_factor = (1 + inputs.assumptions.inflation_rate) ** y

        # Capture start-of-year pre-tax balances for RMD calculation.
        # Per IRS rules, the RMD for year Y uses the Dec 31 of year Y-1 balance,
        # which is exactly the balance carried into the current loop iteration.
        _user_rmd_base   = accts.user_401k_pretax   + accts.user_trad_ira
        _spouse_rmd_base = accts.spouse_401k_pretax + accts.spouse_trad_ira

        # ── 1. INCOME ────────────────────────────────────────────────────────────

        user_w2 = 0.0
        if year < inputs.user.w2_stop_year:
            user_w2 = inputs.user_w2.gross_annual * (1 + inputs.user_w2.annual_raise_rate) ** y

        spouse_w2 = 0.0
        if year < inputs.spouse.w2_stop_year:
            spouse_w2 = inputs.spouse_w2.gross_annual * (1 + inputs.spouse_w2.annual_raise_rate) ** y

        # Sole prop: active for a defined number of years from simulation start
        sole_prop = (
            inputs.sole_prop.net_annual * (1 + inputs.sole_prop.growth_rate) ** y
            if y < inputs.sole_prop.years_active
            else 0.0
        )

        # Rental cash flow: NOI only
        annual_gross_rent = inputs.rental.monthly_gross_rent * 12 * (1 + inputs.rental.rent_growth_rate) ** y
        effective_gross = annual_gross_rent * (1 - inputs.rental.vacancy_rate)
        operating_expenses = annual_gross_rent * inputs.rental.expense_ratio
        rental_cf = effective_gross - operating_expenses

        # ── 2. CONTRIBUTIONS (amounts only — accounts updated later) ─────────────

        user_has_earned   = (user_w2 > 0) or (sole_prop > 0)
        spouse_has_earned = (spouse_w2 > 0)

        # W2 401(k): contribution determined by each person's chosen mode
        ee_limit = annual_401k_ee_limit(year)
        user_401k_contrib = (
            _compute_w2_401k(
                inputs.contributions.user_401k_mode,
                inputs.contributions.user_401k_amount,
                inputs.contributions.user_401k_pct,
                user_w2, ee_limit,
            ) if year < inputs.user.w2_stop_year else 0.0
        )
        spouse_401k_contrib = (
            _compute_w2_401k(
                inputs.contributions.spouse_401k_mode,
                inputs.contributions.spouse_401k_amount,
                inputs.contributions.spouse_401k_pct,
                spouse_w2, ee_limit,
            ) if year < inputs.spouse.w2_stop_year else 0.0
        )

        # IRA contributions
        user_ira_contrib   = inputs.contributions.user_ira   if user_has_earned   else 0.0
        spouse_ira_contrib = inputs.contributions.spouse_ira if spouse_has_earned else 0.0

        # Solo 401(k) — active while sole prop income > 0 AND User no longer has a W2.
        # She cannot contribute to both a W2 employer 401(k) and a Solo 401(k) simultaneously
        # (the IRS employee elective deferral limit is shared across all plans in a year).
        solo_ee_pretax = solo_ee_roth = solo_er_pretax = solo_er_roth = 0.0
        if y < inputs.sole_prop.years_active and sole_prop > 0 and year >= inputs.user.w2_stop_year:
            ee = min(inputs.contributions.user_solo_401k_ee, ee_limit, sole_prop)
            er = min(
                inputs.contributions.user_solo_401k_er_pct * sole_prop,
                max(0.0, _SOLO_401K_TOTAL_LIMIT - ee),
            )
            if inputs.contributions.user_solo_401k_ee_type == "roth":
                solo_ee_roth, solo_ee_pretax = ee, 0.0
            else:
                solo_ee_pretax, solo_ee_roth = ee, 0.0
            if inputs.contributions.user_solo_401k_er_type == "roth":
                solo_er_roth, solo_er_pretax = er, 0.0
            else:
                solo_er_pretax, solo_er_roth = er, 0.0

        # ── 3. SEPP — adds to ordinary taxable income ────────────────────────────

        sepp_payment = 0.0
        if inputs.sepp.enabled:
            person_birth = (inputs.user.birth_year if inputs.sepp.account == "user"
                            else inputs.spouse.birth_year)
            sepp_end = max(inputs.sepp.start_year + 4, person_birth + 59)

            if inputs.sepp.start_year <= year <= sepp_end:
                if year == inputs.sepp.start_year:
                    # Compute fixed annual payment based on balance at start
                    if inputs.sepp.account == "user":
                        bal = accts.user_401k_pretax + accts.user_trad_ira
                    else:
                        bal = accts.spouse_401k_pretax + accts.spouse_trad_ira
                    n_years = sepp_end - inputs.sepp.start_year + 1
                    _sepp_annual = _sepp_amortization(bal, n_years, inputs.sepp.interest_rate)
                sepp_payment = _sepp_annual

        # ── 3b. RMDs — mandatory from pre-tax 401(k) + Traditional IRA at age 73+ ──
        # RMD = prior-year-end balance / IRS Uniform Lifetime Table factor.
        # Added to ordinary taxable income; executed as withdrawal before growth.
        # Roth accounts (401k Roth, Roth IRA) are exempt.

        _k_rmd_factor = rmd_factor(user_age)
        _h_rmd_factor = rmd_factor(spouse_age)

        # Compute gross RMD; cap at available balance (can't withdraw more than exists)
        user_rmd  = min(_user_rmd_base   / _k_rmd_factor, _user_rmd_base)   if _k_rmd_factor > 0 else 0.0
        spouse_rmd = min(_spouse_rmd_base / _h_rmd_factor, _spouse_rmd_base) if _h_rmd_factor > 0 else 0.0

        # If SEPP is already drawing from that person's accounts, credit it toward the RMD.
        # Only the shortfall (if any) needs to be forced as an additional RMD withdrawal.
        if inputs.sepp.account == "user":
            user_rmd   = max(0.0, user_rmd   - sepp_payment)
        else:
            spouse_rmd = max(0.0, spouse_rmd - sepp_payment)

        # ── 4. ROTH CONVERSION — triggers conversion tax, no cash-flow effect ────

        conversion_amount = 0.0
        if (inputs.roth_conversion.enabled
                and inputs.roth_conversion.start_year <= year <= inputs.roth_conversion.end_year):
            if inputs.roth_conversion.source == "user":
                available = accts.user_401k_pretax + accts.user_trad_ira
            else:
                available = accts.spouse_401k_pretax + accts.spouse_trad_ira
            conversion_amount = min(inputs.roth_conversion.annual_amount, max(0.0, available))

        # Conversion tax is deducted from surplus (not real income — just a tax event)
        conversion_tax = conversion_amount * inputs.assumptions.effective_tax_rate

        # ── 5. TAX CALCULATION ───────────────────────────────────────────────────

        # Gross taxable = W2 (after pre-tax 401k) + SP (after solo pre-tax deductions) + SEPP + RMDs
        # Only pre-tax solo contributions reduce SE taxable income; Roth contributions do not.
        gross_taxable = (
            (user_w2   - user_401k_contrib) +
            (spouse_w2 - spouse_401k_contrib) +
            sole_prop - solo_ee_pretax - solo_er_pretax +
            sepp_payment +
            user_rmd + spouse_rmd
        )
        taxes_on_income = max(0.0, gross_taxable) * inputs.assumptions.effective_tax_rate
        taxes = taxes_on_income + conversion_tax
        net_taxable = gross_taxable - taxes_on_income
        total_net_income = net_taxable + rental_cf

        # ── 6. EXPENSES ──────────────────────────────────────────────────────────

        spending = inputs.assumptions.annual_spending_today * inflation_factor
        if inputs.spending_override is not None and year >= inputs.spending_override.change_year:
            spending *= (1 + inputs.spending_override.change_pct)
        on_employer_hc = (user_w2 > 0) or (spouse_w2 > 0)
        healthcare = 0.0 if on_employer_hc else inputs.assumptions.annual_healthcare_off_employer * inflation_factor
        total_expenses = spending + healthcare

        # ── 7. APPLY CONTRIBUTIONS TO ACCOUNTS ───────────────────────────────────

        # W2 401(k)
        accts.user_401k_pretax   += user_401k_contrib
        accts.spouse_401k_pretax += spouse_401k_contrib

        # IRA
        if user_has_earned:
            accts.user_trad_ira += user_ira_contrib
        if spouse_has_earned:
            accts.spouse_trad_ira += spouse_ira_contrib

        # Solo 401(k): route each contribution to the correct pre-tax or Roth bucket
        accts.user_401k_pretax += (solo_ee_pretax + solo_er_pretax)
        accts.user_401k_roth   += (solo_ee_roth   + solo_er_roth)

        # Execute Roth conversion (move from pre-tax to Roth)
        if conversion_amount > 0:
            if inputs.roth_conversion.source == "user":
                total_pretax = accts.user_401k_pretax + accts.user_trad_ira
                if total_pretax > 0:
                    k_frac = accts.user_401k_pretax / total_pretax
                    accts.user_401k_pretax -= conversion_amount * k_frac
                    accts.user_trad_ira    -= conversion_amount * (1 - k_frac)
                accts.user_roth_ira += conversion_amount
            else:
                total_pretax = accts.spouse_401k_pretax + accts.spouse_trad_ira
                if total_pretax > 0:
                    h_frac = accts.spouse_401k_pretax / total_pretax
                    accts.spouse_401k_pretax -= conversion_amount * h_frac
                    accts.spouse_trad_ira    -= conversion_amount * (1 - h_frac)
                accts.spouse_roth_ira += conversion_amount
            conversion_history.append((year, conversion_amount))

        # Execute SEPP withdrawal (reduce pre-tax account)
        if sepp_payment > 0:
            if inputs.sepp.account == "user":
                avail = accts.user_401k_pretax + accts.user_trad_ira
                draw = min(sepp_payment, avail)
                if avail > 0:
                    k_frac = accts.user_401k_pretax / avail
                    accts.user_401k_pretax -= draw * k_frac
                    accts.user_trad_ira    -= draw * (1 - k_frac)
            else:
                avail = accts.spouse_401k_pretax + accts.spouse_trad_ira
                draw = min(sepp_payment, avail)
                if avail > 0:
                    h_frac = accts.spouse_401k_pretax / avail
                    accts.spouse_401k_pretax -= draw * h_frac
                    accts.spouse_trad_ira    -= draw * (1 - h_frac)

        # Execute RMD withdrawals (draw pro-rata from pretax 401k and Traditional IRA)
        if user_rmd > 0:
            avail = accts.user_401k_pretax + accts.user_trad_ira
            draw = min(user_rmd, avail)
            if avail > 0:
                k_frac = accts.user_401k_pretax / avail
                accts.user_401k_pretax -= draw * k_frac
                accts.user_trad_ira    -= draw * (1 - k_frac)

        if spouse_rmd > 0:
            avail = accts.spouse_401k_pretax + accts.spouse_trad_ira
            draw = min(spouse_rmd, avail)
            if avail > 0:
                h_frac = accts.spouse_401k_pretax / avail
                accts.spouse_401k_pretax -= draw * h_frac
                accts.spouse_trad_ira    -= draw * (1 - h_frac)

        # Brokerage: from surplus after expenses, IRAs, solo Roth contributions, and conversion tax.
        # Roth solo contributions come from post-tax dollars (not a pre-tax deduction).
        surplus_before_brokerage = (
            total_net_income - total_expenses
            - user_ira_contrib - spouse_ira_contrib
            - solo_ee_roth - solo_er_roth
            - conversion_tax
        )
        brokerage_contrib = min(inputs.contributions.brokerage, max(0.0, surplus_before_brokerage))
        accts.brokerage += brokerage_contrib

        # ── 8. GROW ALL INVESTMENT ACCOUNTS ──────────────────────────────────────

        r = inputs.assumptions.market_return_rate
        accts.user_401k_pretax   *= (1 + r)
        accts.user_401k_roth     *= (1 + r)
        accts.user_trad_ira      *= (1 + r)
        accts.user_roth_ira      *= (1 + r)
        accts.spouse_401k_pretax *= (1 + r)
        accts.spouse_401k_roth   *= (1 + r)
        accts.spouse_trad_ira    *= (1 + r)
        accts.spouse_roth_ira    *= (1 + r)
        accts.brokerage           *= (1 + r)
        accts.hsa                 *= (1 + r)
        # Cash earns no return in this model (conservative)

        # ── 9. CASH FLOW & WITHDRAWALS ───────────────────────────────────────────

        net_cf = surplus_before_brokerage - brokerage_contrib
        early_withdrawal = 0.0
        plan_solvent = True

        if net_cf > 0:
            accts.cash += net_cf
        else:
            deficit = -net_cf

            # Draw order: cash → brokerage → Roth IRA → penalty-free retirement → penalized

            draw = min(accts.cash, deficit)
            accts.cash -= draw
            deficit -= draw

            if deficit > 0:
                draw = min(accts.brokerage, deficit)
                accts.brokerage -= draw
                deficit -= draw

            if deficit > 0:
                total_roth = accts.user_roth_ira + accts.spouse_roth_ira
                if total_roth > 0:
                    draw = min(total_roth, deficit)
                    user_share = accts.user_roth_ira / total_roth
                    accts.user_roth_ira   -= draw * user_share
                    accts.spouse_roth_ira -= draw * (1 - user_share)
                    deficit -= draw

            penalty_free_order = []
            penalized_order = []
            for attr, age in [
                ("user_401k_pretax", user_age),
                ("user_trad_ira",    user_age),
                ("spouse_401k_pretax", spouse_age),
                ("spouse_trad_ira",    spouse_age),
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

        # ── 10. ROTH CONVERSION VINTAGE TRACKING ─────────────────────────────────

        # Cumulative seasoned Roth = sum of conversions ≥5 years old (accessible without penalty)
        accessible_roth_seasoned = sum(amt for yr, amt in conversion_history if yr <= year - 5)

        # ── 11. ROLL-UP TOTALS ───────────────────────────────────────────────────

        total_ret = (
            accts.user_401k_pretax + accts.user_401k_roth +
            accts.user_trad_ira    + accts.user_roth_ira +
            accts.spouse_401k_pretax + accts.spouse_401k_roth +
            accts.spouse_trad_ira    + accts.spouse_roth_ira
        )
        total_liquid = accts.brokerage + accts.cash + accts.hsa
        total_nw = total_ret + total_liquid

        snapshots.append(YearSnapshot(
            year=year,
            user_age=user_age,
            spouse_age=spouse_age,
            user_w2_gross=user_w2,
            spouse_w2_gross=spouse_w2,
            sole_prop_net=sole_prop,
            rental_cashflow=rental_cf,
            gross_taxable_income=gross_taxable,
            taxes_paid=taxes,
            total_net_income=total_net_income,
            spending=spending,
            healthcare=healthcare,
            total_expenses=total_expenses,
            net_cashflow=net_cf,
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
            total_retirement_accounts=total_ret,
            total_liquid_non_retirement=total_liquid,
            total_net_worth=total_nw,
            on_employer_healthcare=on_employer_hc,
            early_withdrawal_amount=early_withdrawal,
            plan_solvent=plan_solvent,
            roth_conversion_amount=conversion_amount,
            sepp_payment=sepp_payment,
            accessible_roth_seasoned=accessible_roth_seasoned,
            user_rmd=user_rmd,
            spouse_rmd=spouse_rmd,
        ))

    return snapshots
