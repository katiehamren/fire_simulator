"""Shared test fixtures and helpers."""
import pytest

from engine.models import (
    AccountBalances,
    AnnualContributions,
    Assumptions,
    PersonInfo,
    RentalProperty,
    SimInputs,
    SolePropIncome,
    W2Income,
)


@pytest.fixture
def default_inputs() -> SimInputs:
    """Minimal SimInputs with round numbers for easy mental math verification."""
    return SimInputs(
        user=PersonInfo("User", 1985, 2029),
        spouse=PersonInfo("Spouse", 1983, 2036),
        user_w2=W2Income(100_000, 0.0),
        spouse_w2=W2Income(100_000, 0.0),
        sole_prop=SolePropIncome(50_000, 0.0, 20),
        rental=RentalProperty(
            monthly_gross_rent=2000,
            rent_growth_rate=0.0,
            vacancy_rate=0.0,
            expense_ratio=0.25,
        ),
        accounts=AccountBalances(
            user_401k_pretax=100_000,
            spouse_401k_pretax=100_000,
            brokerage=100_000,
            cash=50_000,
        ),
        contributions=AnnualContributions(
            user_401k_mode="dollar",
            user_401k_amount=10_000,
            spouse_401k_mode="dollar",
            spouse_401k_amount=10_000,
            brokerage=0,
        ),
        assumptions=Assumptions(
            market_return_rate=0.0,
            inflation_rate=0.0,
            annual_spending_today=80_000,
            annual_healthcare_off_employer=20_000,
        ),
        end_year=2040,
    )


@pytest.fixture
def zero_growth_inputs(default_inputs) -> SimInputs:
    """SimInputs with 0% returns, 0% inflation, 0% raises — pure arithmetic check."""
    return default_inputs


def snap_year(snapshots, year):
    """Get a specific year's snapshot from the list."""
    return next(s for s in snapshots if s.year == year)
