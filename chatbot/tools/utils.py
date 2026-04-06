"""Shared helpers for simulation read / what-if tools."""

import dataclasses


def snap_to_dict(snap) -> dict:
    return dataclasses.asdict(snap)


def filter_years(snapshots, start_year, end_year):
    result = snapshots
    if start_year is not None:
        result = [s for s in result if s.year >= start_year]
    if end_year is not None:
        result = [s for s in result if s.year <= end_year]
    return result


def bridge_years(inputs):
    """Return (bridge_start, bridge_end) inclusive calendar years.

    Bridge = last W2 stop → first year either person is penalty-free (age ≥ 60).
    """
    bridge_start = max(inputs.user.w2_stop_year, inputs.spouse.w2_stop_year)
    user_free = inputs.user.birth_year + 60
    spouse_free = inputs.spouse.birth_year + 60
    bridge_end = min(user_free, spouse_free) - 1
    return bridge_start, bridge_end
