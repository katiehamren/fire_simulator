"""
Data models for the Early Retirement Simulator.
All monetary values are in nominal dollars (future dollars when used in simulation output,
today's dollars when used as inputs — the simulator applies inflation automatically).
"""
from dataclasses import dataclass, field
from typing import Optional

CURRENT_YEAR = 2026

# IRS 401(k) employee elective deferral limit.
# Grows ~$500 every year or two; we project a steady $500/yr from the 2026 baseline.
_401K_EE_2026 = 23_500
_401K_EE_ANNUAL_BUMP = 500

def annual_401k_ee_limit(year: int) -> int:
    """Projected 401(k) employee elective deferral cap for a given calendar year."""
    return _401K_EE_2026 + _401K_EE_ANNUAL_BUMP * max(0, year - CURRENT_YEAR)


# IRS Uniform Lifetime Table (Publication 590-B, updated 2022).
_RMD_UNIFORM_TABLE: dict[int, float] = {
    73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9,
    78: 22.0, 79: 21.1, 80: 20.2, 81: 19.4, 82: 18.5,
    83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4,
    88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8,
    93: 10.1, 94: 9.5,  95: 8.9,  96: 8.4,  97: 7.8,
    98: 7.3,  99: 6.8, 100: 6.4, 101: 6.0, 102: 5.6,
   103: 5.2, 104: 4.9, 105: 4.6, 106: 4.3, 107: 4.1,
   108: 3.9, 109: 3.7, 110: 3.5, 111: 3.4, 112: 3.3,
   113: 3.1, 114: 3.0,  # 115+ → 2.9
}

def rmd_factor(age: int) -> float:
    """Return the IRS Uniform Lifetime Table divisor for the given age.
    Returns 0.0 for ages below 73 (no RMD required).
    RMD = prior_year_end_balance / rmd_factor(age).
    """
    if age < 73:
        return 0.0
    return _RMD_UNIFORM_TABLE.get(age, 2.9)  # 2.9 for age 115+


@dataclass
class PersonInfo:
    name: str
    birth_year: int
    w2_stop_year: int  # First calendar year WITHOUT W2 income


@dataclass
class W2Income:
    gross_annual: float       # Current-year gross salary
    annual_raise_rate: float  # Decimal, e.g. 0.03 for 3%


@dataclass
class SolePropIncome:
    """User's sole proprietorship — continues after W2 stop for a defined number of years."""
    net_annual: float    # Current-year net income (after biz expenses, before income tax)
    growth_rate: float   # Annual growth rate, decimal
    years_active: int = 20  # Number of years from CURRENT_YEAR before sole prop winds down to $0


@dataclass
class RentalProperty:
    monthly_gross_rent: float
    rent_growth_rate: float   # Annual rent increase rate
    vacancy_rate: float       # Fraction of year vacant, e.g. 0.05
    expense_ratio: float      # OpEx as fraction of gross rent (taxes, insurance, maintenance, mgmt)


@dataclass
class AccountBalances:
    """Current balances for all accounts."""
    user_401k_pretax: float = 0.0
    user_401k_roth: float = 0.0
    user_trad_ira: float = 0.0
    user_roth_ira: float = 0.0
    spouse_401k_pretax: float = 0.0
    spouse_401k_roth: float = 0.0
    spouse_trad_ira: float = 0.0
    spouse_roth_ira: float = 0.0
    brokerage: float = 0.0
    hsa: float = 0.0
    cash: float = 0.0


@dataclass
class AnnualContributions:
    """Annual savings contributions.

    W2 401(k) contribution mode per person (while they have W2 income):
      "max"     — contribute the IRS employee elective deferral limit each year,
                  growing $500/yr (see annual_401k_ee_limit). Capped at W2 salary.
      "dollar"  — contribute a fixed dollar amount each year (capped at IRS limit and W2).
      "percent" — contribute a fixed % of gross W2 salary (capped at IRS limit).
    """
    # W2 401(k) contribution settings
    user_401k_mode: str = "max"      # "max" | "dollar" | "percent"
    user_401k_amount: float = 0.0    # Fixed $ amount (mode == "dollar")
    user_401k_pct: float = 0.0       # Fraction of W2 (mode == "percent"), e.g. 0.10 for 10%
    spouse_401k_mode: str = "max"
    spouse_401k_amount: float = 0.0
    spouse_401k_pct: float = 0.0

    user_ira: float = 0.0      # While User has earned income (W2 or sole prop)
    spouse_ira: float = 0.0    # While Spouse has earned income
    brokerage: float = 0.0      # Annual savings to taxable brokerage; taken from surplus
    # Solo 401(k) for User's sole proprietorship (active while sole prop income > 0)
    user_solo_401k_ee: float = 0.0        # Employee elective deferral ($ per year)
    user_solo_401k_ee_type: str = "pretax" # "pretax" or "roth"
    user_solo_401k_er_pct: float = 0.0    # Employer profit-sharing % of net SE income (0.0–0.25)
    user_solo_401k_er_type: str = "pretax" # "pretax" or "roth" (SECURE 2.0 allows Roth employer)


@dataclass
class Assumptions:
    effective_tax_rate: float = 0.22          # Flat effective rate on W2 + sole prop gross income
    market_return_rate: float = 0.07          # Annual investment return
    inflation_rate: float = 0.03              # Annual inflation
    annual_spending_today: float = 90_000.0   # Annual household spending in TODAY's dollars
    annual_healthcare_off_employer: float = 24_000.0  # Full health ins + OOP when not on employer plan


@dataclass
class RothConversionPlan:
    """
    Annual pre-tax → Roth conversions during low-income years.

    Mechanics: move `annual_amount` from the source person's pre-tax 401k/IRA to their
    Roth IRA each year in [start_year, end_year].  Ordinary income tax is triggered on
    the converted amount.  Converted principal is accessible penalty-free after 5 years
    (the Roth conversion ladder).
    """
    enabled: bool = False
    start_year: int = CURRENT_YEAR
    end_year: int = CURRENT_YEAR + 9   # 10-year window by default
    annual_amount: float = 0.0
    source: str = "user"              # "user" or "spouse"


@dataclass
class SEPPPlan:
    """
    Substantially Equal Periodic Payments — IRS 72(t) rule.

    Allows penalty-free distributions from a pre-tax retirement account before age 59½.
    The annual payment is computed once (amortization method) and held fixed until the
    plan ends at the LATER of (start_year + 4) or (birth_year + 59).
    """
    enabled: bool = False
    start_year: int = CURRENT_YEAR
    account: str = "user"    # "user" or "spouse" — whose pre-tax accounts to draw from
    interest_rate: float = 0.045  # Assumed rate (≈120% IRS mid-term AFR); amortization method


@dataclass
class SpendingOverride:
    """Adjust annual spending by a fixed percentage starting in a given year.

    change_pct: fractional change, e.g. -0.10 for a 10% spending cut.
    change_year: first calendar year the override takes effect.
    """
    change_pct: float
    change_year: int


@dataclass
class SimInputs:
    user: PersonInfo
    spouse: PersonInfo
    user_w2: W2Income
    spouse_w2: W2Income
    sole_prop: SolePropIncome
    rental: RentalProperty
    accounts: AccountBalances
    contributions: AnnualContributions
    assumptions: Assumptions
    end_year: int = 2080
    roth_conversion: RothConversionPlan = field(default_factory=RothConversionPlan)
    sepp: SEPPPlan = field(default_factory=SEPPPlan)
    spending_override: Optional[SpendingOverride] = None


@dataclass
class YearSnapshot:
    """Complete state of the simulation for a single calendar year."""
    year: int
    user_age: int
    spouse_age: int

    # Gross income by source (before tax)
    user_w2_gross: float
    spouse_w2_gross: float
    sole_prop_net: float
    rental_cashflow: float        # NOI (effective rent minus operating expenses)

    # Tax & net income
    gross_taxable_income: float   # W2 + sole prop + SEPP (rental excluded — separate treatment)
    taxes_paid: float             # Includes ordinary income tax + Roth conversion tax
    total_net_income: float       # After-tax W2+SP+SEPP + rental cashflow

    # Expenses
    spending: float               # Inflation-adjusted spending
    healthcare: float             # 0 if on employer plan; else inflation-adjusted cost
    total_expenses: float

    # Cash flow
    net_cashflow: float           # net_income - expenses - brokerage_contrib

    # Account balances at END of year (after growth, contributions, withdrawals)
    user_401k_pretax: float
    user_401k_roth: float
    user_trad_ira: float
    user_roth_ira: float
    spouse_401k_pretax: float
    spouse_401k_roth: float
    spouse_trad_ira: float
    spouse_roth_ira: float
    brokerage: float
    hsa: float
    cash: float

    # Rollup totals
    total_retirement_accounts: float   # All 401k + IRA balances
    total_liquid_non_retirement: float # Brokerage + cash + HSA
    total_net_worth: float             # total_retirement_accounts + total_liquid_non_retirement

    # Status
    on_employer_healthcare: bool
    early_withdrawal_amount: float    # Amount from retirement accts while under 59.5 (10% penalty territory)
    plan_solvent: bool                # False if expenses could not be covered

    # Roth ladder & SEPP
    roth_conversion_amount: float = 0.0     # Converted this year (pre-tax → Roth)
    sepp_payment: float = 0.0              # SEPP distribution this year
    accessible_roth_seasoned: float = 0.0   # Cumulative Roth conversions ≥5 years old

    # RMDs (pre-tax 401k + Traditional IRA, age 73+)
    user_rmd: float = 0.0
    spouse_rmd: float = 0.0
