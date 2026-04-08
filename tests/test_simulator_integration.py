"""Integration tests: full scenarios with known expected outcomes."""
import pytest

from engine.simulator import run_simulation


class TestBaselineScenario:
    def test_full_simulation_runs_without_error(self, default_inputs):
        snaps = run_simulation(default_inputs)
        assert len(snaps) == default_inputs.end_year - 2026 + 1

    def test_net_worth_never_negative_with_surplus_income(self, default_inputs):
        """With both W2s and sole prop, should never go negative in first 15 years."""
        snaps = run_simulation(default_inputs)
        for s in snaps:
            if s.year < 2040:
                assert s.total_net_worth >= 0, f"Negative NW in {s.year}"

    def test_healthcare_only_when_no_w2(self, default_inputs):
        snaps = run_simulation(default_inputs)
        for s in snaps:
            if s.user_w2_gross > 0 or s.spouse_w2_gross > 0:
                assert s.healthcare == 0.0, f"Healthcare charged in {s.year} with W2 income"
            elif s.year >= default_inputs.spouse.w2_stop_year:
                assert s.healthcare > 0.0, f"No healthcare in {s.year} without W2"

    def test_snapshot_field_consistency(self, default_inputs):
        """Verify rollup fields are consistent with component fields."""
        snaps = run_simulation(default_inputs)
        for s in snaps:
            expected_ret = (
                s.user_401k_pretax
                + s.user_401k_roth
                + s.user_trad_ira
                + s.user_roth_ira
                + s.spouse_401k_pretax
                + s.spouse_401k_roth
                + s.spouse_trad_ira
                + s.spouse_roth_ira
            )
            assert s.total_retirement_accounts == pytest.approx(expected_ret, rel=1e-6), (
                f"Year {s.year}"
            )

            expected_liquid = s.brokerage + s.cash + s.hsa
            assert s.total_liquid_non_retirement == pytest.approx(expected_liquid, rel=1e-6), (
                f"Year {s.year}"
            )

            expected_nw = expected_ret + expected_liquid
            assert s.total_net_worth == pytest.approx(expected_nw, rel=1e-6), f"Year {s.year}"
