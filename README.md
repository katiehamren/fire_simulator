# FIRE Simulator

A year-by-year retirement planning web app for simulating retirement scenarios, built for fun when the google spreadsheet got too complicated. The simulator models the "bridge period" between leaving W2 employment and reaching penalty-free retirement account access at 59½, with particular focus on the Roth conversion ladder, ACA healthcare subsidy management, and tax efficiency over a multi-decade horizon. Today assumes a spouse, W2 income, Sole Prop (side-gig) income, rental property. Future enhancements will make all of those things toggleable.

Built with Python + Streamlit. Includes an AI chatbot (OpenAI function-calling) that can answer natural-language questions about your simulation.

Does NOT replace advice from a qualified tax professional; major simplifications have been made, the chat window is an AI capable of hallucinating, and there may well be some lingering math bugs. 


---

## Quickstart

### Prerequisites

- Python 3.10+ managed by **pyenv**
- An OpenAI API key (for the chatbot)

### Setup

```bash
# 1. Create and activate a virtualenv
pyenv virtualenv 3.10.14 retirement-sim
pyenv activate retirement-sim

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env        # or create .env manually
# Edit .env and set:
#   OPENAI_API_KEY=sk-...

# 4. Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`. The sidebar on the left is where you enter all your inputs. Charts and analysis appear in the main panel.

### Running tests

```bash
pytest
```

### Saved scenarios

Scenario files are stored in `saved_scenarios/` (gitignored). Use the **Save / Load** panel in the sidebar to persist and restore named scenarios.

---

## High-Level Overview

### What the simulator does

Starting from the current calendar year, the engine runs a year-by-year loop through your chosen end year (default 2075). Each year it:

1. Computes gross income from all sources
2. Applies contributions to retirement and savings accounts
3. Calculates federal income tax, self-employment tax, and capital gains tax
4. Estimates healthcare costs (ACA or flat)
5. Covers any spending deficit by drawing from accounts in a defined withdrawal order
6. Grows all investment accounts by the assumed market return
7. Records a complete snapshot of every financial variable for that year

### Income sources

| Source | Who | Notes |
|---|---|---|
| W2 salary | User + Spouse | Each has a configurable stop year and annual raise rate |
| Sole proprietorship | User | Net income after business expenses; active for a configurable number of years |
| Rental property | Household | NOI (gross rent minus vacancy and operating expenses); depreciation modeled for taxes |

### Account types

The simulator tracks 11 accounts:

| Account | Tax treatment |
|---|---|
| User pre-tax 401k | Contributions reduce taxable income; withdrawals are ordinary income |
| User Roth 401k | After-tax contributions; tax-free growth and withdrawal |
| User traditional IRA | Same as pre-tax 401k |
| User Roth IRA | Same as Roth 401k; no RMDs for original owner |
| Spouse pre-tax 401k | Same as User pre-tax 401k |
| Spouse Roth 401k | Same as User Roth 401k |
| Spouse traditional IRA | Same as traditional IRA |
| Spouse Roth IRA | Same as User Roth IRA |
| Taxable brokerage | No contribution limit; capital gains tax on withdrawals |
| HSA | Triple tax-advantaged; funds healthcare expenses tax-free |
| Cash | No investment return; used as buffer |

### Key planning strategies modeled

**Roth conversion ladder** — During low-income years after W2 stops but before 59½, move money from pre-tax accounts to Roth IRA. Converted principal becomes accessible penalty-free after 5 years, creating a bridge to draw from before retirement accounts open up. The engine computes the marginal tax cost of each conversion.

**SEPP / 72(t)** — Substantially Equal Periodic Payments allow penalty-free pre-59½ withdrawals from a retirement account, as long as the same payment amount is taken for at least 5 years or until age 59½ (whichever is later). The payment is computed once using the amortization method and held fixed for the duration of the plan.

**ACA subsidy management** — Once off employer healthcare, premiums are estimated from MAGI each year. Keeping MAGI in the right range unlocks significant Premium Tax Credits. Roth conversions and brokerage withdrawals both increase MAGI, creating a direct trade-off between tax efficiency and healthcare subsidy eligibility.

**HSA accumulation and spend-down** — Contributions are made while any household member has W2/HDHP coverage. In retirement, the HSA balance covers premiums and out-of-pocket costs tax-free, extending its value far beyond the nominal contributions via compound growth.

### Chatbot

The in-app AI assistant has four tools:

- **read_simulation** — answers questions about your current simulation results
- **run_what_if** — re-runs the simulation with overridden parameters and compares to baseline
- **find_threshold** — bisects over a single parameter to find the value that crosses a target (e.g., "what conversion amount keeps us solvent?")
- **web_search** — looks up current tax rules, IRS limits, and ACA parameters

---

## Detailed Math Reference

### Simulation loop order (each year)

The following steps happen in this order within each calendar year. All dollar values are **nominal** (future dollars).

---

#### 1. Income

```
user_w2    = gross_salary × (1 + raise_rate)^y        if year < user_w2_stop_year
spouse_w2  = gross_salary × (1 + raise_rate)^y        if year < spouse_w2_stop_year
sole_prop  = net_annual × (1 + growth_rate)^y          if y < years_active
rental_noi = gross_rent × (1 − vacancy) − gross_rent × expense_ratio
```

`y` is the number of years elapsed since the simulation start year.

Rental taxable income applies depreciation:
```
annual_depreciation  = property_value × (1 − land_value_pct) / 27.5
rental_taxable       = max(0, rental_noi − annual_depreciation)
```

The 27.5-year straight-line depreciation schedule follows IRS rules for residential rental property. Land is not depreciable; `land_value_pct` defaults to 20%.

---

#### 2. 401(k) and IRA contributions

**W2 401(k)** — computed while the person has W2 income. Three modes:

| Mode | Formula |
|---|---|
| `max` | `min(annual_ee_limit(year), w2_salary)` |
| `dollar` | `min(fixed_amount, annual_ee_limit(year), w2_salary)` |
| `percent` | `min(pct × w2_salary, annual_ee_limit(year))` |

The IRS employee elective deferral limit is projected as `$23,500 + $500 × (year − 2026)`.

**Solo 401(k)** — active while sole prop income > 0 and User has no W2 (cannot double-dip the employee deferral limit):

```
employee_deferral  = min(user_input, ee_limit − w2_401k_contrib)
employer_contrib   = sole_prop_net × er_pct           (max 25%, per IRS)
```

Both can be pre-tax or Roth (SECURE 2.0). Pre-tax contributions reduce gross taxable income; Roth contributions are funded from post-tax surplus.

**HSA** — while any household member has W2 income (assumes family HDHP coverage). Max family contribution is `$8,750 × (1 + inflation)^y`. Contributions reduce both ordinary taxable income and MAGI.

**IRA** — fixed dollar amount per year, while the person has earned income.

---

#### 3. Federal income tax

Taxable income:
```
gross_taxable = user_w2 − user_401k_pretax
              + spouse_w2 − spouse_401k_pretax
              + sole_prop − solo_ee_pretax − solo_er_pretax − se_deduction
              + rental_taxable
              + sepp_payment + user_rmd + spouse_rmd
              + roth_conversion_amount
              − hsa_contribution
```

Tax brackets and standard deduction are inflated from the 2025 MFJ base each year:
```
factor        = (1 + inflation_rate)^(year − 2025)
std_deduction = $31,500 × factor
bracket_floors × factor
```

Tax is computed by walking each bracket layer:
```
taxable = max(0, gross_taxable − std_deduction)
tax     = Σ layer_i × rate_i    for each bracket
```

Roth conversion tax is computed as the **marginal cost** of adding the conversion to income:
```
conversion_tax = tax(gross_taxable + conversion) − tax(gross_taxable)
```

---

#### 4. Self-employment tax

SE tax is an individual obligation of the self-employed person (the User). It is separate from and in addition to federal income tax.

```
taxable_se          = sole_prop_net × 0.9235          (IRS 92.35% rule)
ss_wage_base        = $176,100 × (1.03)^(year − 2025) (grows ~3%/yr)
ss_room             = max(0, ss_wage_base − user_w2)   (W2 FICA already paid)
ss_tax              = min(taxable_se, ss_room) × 12.4%
medicare_tax        = taxable_se × 2.9%
additional_medicare = max(0, user_w2 + taxable_se − $250,000) × 0.9%
se_tax              = ss_tax + medicare_tax + additional_medicare
```

Half of SE tax is deductible above-the-line:
```
se_deduction = se_tax / 2
```

This deduction reduces `gross_taxable` (step 3) but does not reduce the SE tax itself.

---

#### 5. MAGI and ACA healthcare

MAGI for ACA purposes:
```
magi = user_w2 + spouse_w2
     − user_401k_pretax − spouse_401k_pretax
     − hsa_contribution
     + sole_prop − solo_ee_pretax − solo_er_pretax − se_deduction
     + rental_taxable
     + sepp_payment + user_rmd + spouse_rmd
     + roth_conversion_amount
```

**Healthcare — ACA mode:** When neither person has W2 income, the app estimates the second-lowest-cost Silver benchmark premium for a 2-person household, then applies the applicable percentage table to determine the Premium Tax Credit (subsidy).

```
fpl_pct              = magi / federal_poverty_level × 100
expected_contribution = magi × applicable_pct(fpl_pct)
subsidy              = max(0, benchmark_premium − expected_contribution)
aca_premium          = benchmark_premium − subsidy
total_healthcare     = aca_premium + additional_oop
```

The FPL grows at ~2%/yr; the benchmark Silver plan grows at ~5%/yr. Both are inflated from the 2025 base. With ARP extension enabled, the 8.5%-of-income cap applies at all income levels. Without it, the 400% FPL cliff returns (no subsidy above ~$80k MAGI for a 2-person household in 2025 dollars).

**Healthcare — flat mode:** `annual_healthcare_flat × (1 + inflation)^y`

**HSA offset:** In either mode, available HSA balance covers healthcare costs first:
```
hsa_draw    = min(accts.hsa, total_healthcare)
accts.hsa  -= hsa_draw
out_of_pocket = total_healthcare − hsa_draw
```

---

#### 6. SEPP (72t)

The annual payment is computed once at `start_year` using the **amortization method**:
```
payment = pv × rate / (1 − (1 + rate)^−n)
```
where `pv` is the account balance at start, `rate` is the assumed interest rate (default 4.5%), and `n` is the number of years until age 59½. The payment is held fixed for the duration of the plan: the later of 5 years from start or the year the account holder turns 59.

SEPP payments are ordinary income (added to `gross_taxable`) and reduce the available balance proportionally across pre-tax 401k and traditional IRA.

---

#### 7. Roth conversion

The conversion amount is capped at the available pre-tax balance:
```
conversion_amount = min(user_input, pretax_401k + trad_ira)
```

The converted amount moves from pre-tax accounts to Roth IRA, with a proportional split between 401k and IRA based on current balances:
```
k_frac             = pretax_401k / (pretax_401k + trad_ira)
pretax_401k       -= conversion × k_frac
trad_ira          -= conversion × (1 − k_frac)
roth_ira          += conversion
```

Conversion triggers ordinary income tax (the marginal cost computed in step 3). Converted principal is tracked by vintage year; it becomes accessible penalty-free after 5 calendar years.

---

#### 8. Required Minimum Distributions

Starting at age 73 (SECURE 2.0), RMDs are required from pre-tax 401k and traditional IRA. Roth accounts are never subject to RMDs for the original owner.

```
rmd = prior_year_end_balance / IRS_uniform_lifetime_table_divisor(age)
```

The IRS Uniform Lifetime Table divisor ranges from 26.5 at age 73 down to 2.9 at age 115+. RMDs are added to ordinary taxable income.

If SEPP is active on the same account, the SEPP payment counts toward the RMD for that year (no double-distribution required).

---

#### 9. Withdrawal order and deficit resolution

If total expenses exceed net income, the simulator draws from accounts in this order:

1. **Cash** — no investment return; drawn first
2. **Taxable brokerage** — capital gains tax applies (see below)
3. **Roth IRA** — tax-free; penalty-free after 59½ or once conversions have seasoned 5 years
4. **Penalty-free retirement accounts** — pre-tax 401k and traditional IRA after account holder turns 59½; withdrawals are ordinary income
5. **Penalized retirement accounts** — same accounts before 59½; 10% early withdrawal penalty applies

The 59½ test uses exact calendar year (birth year + 59, rounded).

---

#### 10. Capital gains tax on brokerage withdrawals

The simulator tracks brokerage cost basis as a running variable:
```
brokerage_basis initialized at: brokerage_balance × brokerage_cost_basis_pct
```

When brokerage is drawn:
```
gains_fraction  = 1 − (basis / balance)
realized_gains  = draw × gains_fraction
basis          -= draw × (1 − gains_fraction)
```

LTCG tax uses 2025 MFJ brackets, inflated by the plan inflation rate:

| Rate | Taxable income + gains threshold (2025, inflated each year) |
|---|---|
| 0% | Up to $96,700 |
| 15% | $96,701 – $600,050 |
| 20% | Above $600,050 |

The LTCG rate is determined by stacking capital gains on top of ordinary taxable income.

---

#### 11. Account growth

All investment accounts grow at the uniform market return rate:
```
balance_end = balance_mid_year × (1 + market_return_rate)
```

Cash earns no return. Growth is applied after contributions and withdrawals for the year.

---

### Key simplifications

The following are known simplifications relative to real tax law. They are documented here so users can apply judgment:

- **Federal tax only** — no state income tax
- **No Social Security modeling** — benefits not included in income projections
- **Single MAGI timing** — MAGI for ACA subsidy is computed before brokerage withdrawals are known for the year; years with brokerage draws may slightly overstate the subsidy
- **Uniform return** — all accounts grow at the same rate; no asset allocation or sequence-of-returns modeling
- **Passive loss rules** — rental paper losses (depreciation exceeding NOI) are floored at zero; passive activity loss carryforward not modeled
- **Roth accessibility** — the Roth IRA is treated as fully accessible once seasoned conversions exist; the 5-year rule on the account itself is not modeled separately
- **SEPP + conversion conflict** — running both simultaneously on the same account is not blocked; the user should avoid this combination as it can interfere with the SEPP plan
- **No AMT** — Alternative Minimum Tax not modeled

---

## Project Structure

```
retirement_simulator/
├── app.py                      # Streamlit entry point (streamlit run app.py)
├── engine/
│   ├── models.py               # All dataclasses: SimInputs, YearSnapshot, etc.
│   ├── simulator.py            # Main run_simulation() loop
│   ├── year_compute.py         # Pure functions for per-year calculations
│   ├── account_ops.py          # Account mutation functions (contributions, withdrawals)
│   ├── year_state.py           # Mutable scratch state for one year
│   ├── tax_calc.py             # Federal tax, SE tax, LTCG tax
│   ├── tax_brackets.json       # 2025 MFJ brackets (base year; inflated at runtime)
│   ├── aca.py                  # ACA premium tax credit estimator
│   └── insights.py             # Derived metrics (FI date, bridge analysis, etc.)
├── chatbot/
│   ├── agent.py                # OpenAI function-calling agent loop
│   ├── prompts.py              # System prompt with full field reference
│   ├── ui.py                   # Streamlit chatbot panel
│   └── tools/
│       ├── read_simulation.py  # Tool: query current simulation results
│       ├── what_if.py          # Tool: re-run with parameter overrides
│       ├── find_threshold.py   # Tool: bisection search over a parameter
│       └── web_search.py       # Tool: live web search for tax/ACA rules
├── ui/
│   ├── main.py                 # Top-level layout and tab routing
│   ├── sidebar.py              # All input widgets
│   ├── validation.py           # Input sanity checks and warnings
│   ├── formatting.py           # Number formatting helpers
│   ├── scenarios.py            # Save/load scenario JSON
│   └── tabs/                   # One file per chart tab
│       ├── overview.py
│       ├── income_cashflow.py
│       ├── account_balances.py
│       ├── bridge_strategies.py
│       ├── insights.py
│       ├── sensitivity.py
│       └── year_detail.py
├── scenarios/
│   └── defaults.py             # Factory preset scenarios
├── tests/                      # pytest test suite
├── requirements.txt
├── pytest.ini
├── .env.example                # Template for OPENAI_API_KEY (copy to .env; .env is gitignored)
└── .env                        # Local secrets — not in git
```
