"""Tests for engine/insights.py computed metrics."""
from engine.insights import bridge_burn, fi_crossover
from engine.simulator import run_simulation


class TestFICrossover:
    def test_returns_none_when_never_reached(self, default_inputs):
        default_inputs.assumptions.market_return_rate = 0.001
        default_inputs.assumptions.annual_spending_today = 999_999
        snaps = run_simulation(default_inputs)
        result = fi_crossover(snaps, 0.001, 0.0)
        assert result is None

    def test_returns_year_when_reached(self, default_inputs):
        default_inputs.assumptions.market_return_rate = 0.10
        default_inputs.assumptions.annual_spending_today = 10_000
        snaps = run_simulation(default_inputs)
        result = fi_crossover(snaps, 0.10, 0.0)
        assert result is not None
        assert result["year"] >= 2026


class TestBridgeBurn:
    def test_bridge_period_years(self, default_inputs):
        snaps = run_simulation(default_inputs)
        result = bridge_burn(snaps, default_inputs)
        assert result["bridge_start"] == 2029
        assert result["bridge_end"] == 2043
        assert result["years"] == 14
