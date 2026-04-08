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
