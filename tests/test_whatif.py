"""Tests for chatbot what-if override logic."""
from copy import deepcopy

from chatbot.tools.what_if import _apply_what_if_overrides


class TestApplyOverrides:
    def test_spending_override(self, default_inputs):
        inp = deepcopy(default_inputs)
        _apply_what_if_overrides(inp, {"annual_spending": 50_000})
        assert inp.assumptions.annual_spending_today == 50_000

    def test_user_stop_year_override(self, default_inputs):
        inp = deepcopy(default_inputs)
        _apply_what_if_overrides(inp, {"user_w2_stop_year": 2031})
        assert inp.user.w2_stop_year == 2031

    def test_roth_conversion_toggle(self, default_inputs):
        inp = deepcopy(default_inputs)
        _apply_what_if_overrides(
            inp,
            {"roth_conversion_enabled": True, "roth_conversion_amount": 40_000},
        )
        assert inp.roth_conversion.enabled is True
        assert inp.roth_conversion.annual_amount == 40_000

    def test_unknown_key_ignored(self, default_inputs):
        inp = deepcopy(default_inputs)
        original_spending = inp.assumptions.annual_spending_today
        _apply_what_if_overrides(inp, {"nonexistent_key": 999})
        assert inp.assumptions.annual_spending_today == original_spending

    def test_expanded_overrides(self, default_inputs):
        inp = deepcopy(default_inputs)
        _apply_what_if_overrides(
            inp,
            {
                "user_w2_salary": 200_000,
                "brokerage_balance": 500_000,
                "roth_conversion_start_year": 2031,
                "user_solo_401k_ee": 23_500,
                "user_solo_401k_ee_type": "roth",
            },
        )
        assert inp.user_w2.gross_annual == 200_000
        assert inp.accounts.brokerage == 500_000
        assert inp.roth_conversion.start_year == 2031
        assert inp.contributions.user_solo_401k_ee == 23_500
        assert inp.contributions.user_solo_401k_ee_type == "roth"
