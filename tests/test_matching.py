"""Matching engine (F5). Pure tests over the app.matching module.

The route layer is exercised separately in test_search_route.py. These
tests focus on the deterministic ranking and the hard filters.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from app import matching
from app.matching import (
    MatchRequest,
    TripSnapshot,
    match,
    reasons,
)


# --- Module purity --------------------------------------------------------


def test_matching_module_has_no_web_or_db_imports():
    src = inspect.getsource(matching)
    assert "fastapi" not in src
    assert "sqlmodel" not in src
    assert "sqlalchemy" not in src
    assert "app.db" not in src
    assert "app.routes" not in src


def test_reasons_lists_known_tokens():
    toks = reasons()
    assert "exact_pickup" in toks
    assert "same_group_pickup" in toks


# --- Fixtures -------------------------------------------------------------


_DHAKA = timezone.utc  # use UTC for arithmetic simplicity
_T0 = datetime(2026, 3, 5, 8, 0, tzinfo=_DHAKA)


def _snap(
    *,
    trip_id: int,
    instance_id: int,
    driver_id: int = 100,
    from_place_id: int = 1,
    from_place_group: str = "Main",
    to_place_id: int = 2,
    earliest: datetime | None = None,
    latest: datetime | None = None,
    seats_offered: int = 3,
    seats_taken: int = 0,
    women_only: bool = False,
    is_active: bool = True,
) -> TripSnapshot:
    return TripSnapshot(
        trip_id=trip_id,
        instance_id=instance_id,
        driver_id=driver_id,
        from_place_id=from_place_id,
        from_place_group=from_place_group,
        to_place_id=to_place_id,
        earliest_departure=earliest or _T0,
        latest_departure=latest or (_T0 + timedelta(minutes=15)),
        seats_offered=seats_offered,
        seats_taken=seats_taken,
        women_only=women_only,
        is_active=is_active,
    )


def _req(
    *,
    rider_id: int = 999,
    from_place_id: int = 1,
    from_place_group: str = "Main",
    to_place_id: int = 2,
    earliest: datetime | None = None,
    latest: datetime | None = None,
    women: bool = False,
) -> MatchRequest:
    return MatchRequest(
        rider_id=rider_id,
        from_place_id=from_place_id,
        from_place_group=from_place_group,
        to_place_id=to_place_id,
        earliest=earliest or _T0,
        latest=latest or (_T0 + timedelta(minutes=10)),
        riders_women_only_eligible=women,
    )


# --- Cases ---------------------------------------------------------------


def test_exact_pickup_ranks_above_same_group():
    a = _snap(trip_id=1, instance_id=11, from_place_id=99,
              from_place_group="Main")  # same group
    b = _snap(trip_id=2, instance_id=22, from_place_id=1,
              from_place_group="Main")  # exact
    out = match(_req(), [a, b])
    assert [m.trip_id for m in out] == [2, 1]


def test_smaller_time_diff_ranks_higher():
    # Both trips fit within the default 15-min tolerance against the
    # rider's [T0, T0+10] window (centre T0+5). The closer one ranks first.
    near = _snap(trip_id=20, instance_id=220,
                 earliest=_T0 + timedelta(minutes=5),
                 latest=_T0 + timedelta(minutes=15))
    far = _snap(trip_id=10, instance_id=110,
                earliest=_T0, latest=_T0 + timedelta(minutes=10))
    out = match(_req(), [far, near])
    assert [m.trip_id for m in out] == [20, 10]


def test_more_seats_free_ranks_higher_when_other_keys_equal():
    small = _snap(trip_id=30, instance_id=301, seats_offered=3, seats_taken=2)
    big = _snap(trip_id=40, instance_id=401, seats_offered=4, seats_taken=1)
    out = match(_req(), [small, big])
    assert [m.trip_id for m in out] == [40, 30]


def test_lower_trip_id_breaks_ties():
    a = _snap(trip_id=5, instance_id=51)
    b = _snap(trip_id=6, instance_id=62)
    out = match(_req(), [b, a])
    assert [m.trip_id for m in out] == [5, 6]


def test_to_place_must_match():
    a = _snap(trip_id=1, instance_id=11, to_place_id=999)
    b = _snap(trip_id=2, instance_id=22, to_place_id=2)
    out = match(_req(), [a, b])
    assert [m.trip_id for m in out] == [2]


def test_full_trip_excluded():
    full = _snap(trip_id=1, instance_id=11, seats_offered=2, seats_taken=2)
    out = match(_req(), [full])
    assert out == []


def test_cancelled_instance_excluded():
    cancelled = _snap(trip_id=1, instance_id=11, is_active=False)
    out = match(_req(), [cancelled])
    assert out == []


def test_self_match_excluded():
    snap = _snap(trip_id=1, instance_id=11, driver_id=999)
    out = match(_req(rider_id=999), [snap])
    assert out == []


def test_blocked_pair_excluded_in_either_direction():
    snap = _snap(trip_id=1, instance_id=11, driver_id=42)
    # Rider blocks driver
    out = match(_req(rider_id=1), [snap], blocks=[(1, 42)])
    assert out == []
    # Driver blocks rider
    out = match(_req(rider_id=1), [snap], blocks=[(42, 1)])
    assert out == []


def test_pickup_group_must_match():
    other = _snap(trip_id=1, instance_id=11,
                   from_place_id=77, from_place_group="North")
    out = match(_req(from_place_id=1, from_place_group="Main"), [other])
    assert out == []


def test_window_too_late_excluded():
    late = _snap(trip_id=1, instance_id=11,
                 earliest=_T0 + timedelta(hours=1),
                 latest=_T0 + timedelta(hours=2))
    out = match(_req(earliest=_T0, latest=_T0 + timedelta(minutes=10)),
                [late])
    assert out == []


def test_window_too_early_excluded():
    early = _snap(trip_id=1, instance_id=11,
                  earliest=_T0 - timedelta(hours=1),
                  latest=_T0 - timedelta(minutes=30))
    out = match(_req(earliest=_T0, latest=_T0 + timedelta(minutes=10)),
                [early])
    assert out == []


def test_tolerance_allows_close_overlap():
    snap = _snap(trip_id=1, instance_id=11,
                 earliest=_T0 + timedelta(minutes=20),
                 latest=_T0 + timedelta(minutes=30))
    out = match(
        _req(earliest=_T0, latest=_T0 + timedelta(minutes=10)),
        [snap],
        time_tolerance_minutes=15,
    )
    assert [m.trip_id for m in out] == [1]


def test_tolerance_blocks_far_overlap():
    snap = _snap(trip_id=1, instance_id=11,
                 earliest=_T0 + timedelta(hours=2),
                 latest=_T0 + timedelta(hours=2, minutes=15))
    out = match(
        _req(earliest=_T0, latest=_T0 + timedelta(minutes=10)),
        [snap],
        time_tolerance_minutes=15,
    )
    assert out == []


def test_women_only_excludes_non_eligible_rider():
    snap = _snap(trip_id=1, instance_id=11, women_only=True)
    out = match(_req(women=False), [snap], women_only_enabled=True)
    assert out == []


def test_women_only_includes_eligible_rider():
    snap = _snap(trip_id=1, instance_id=11, women_only=True)
    out = match(_req(women=True), [snap], women_only_enabled=True)
    assert [m.trip_id for m in out] == [1]


def test_women_only_filtered_when_feature_disabled_globally():
    snap = _snap(trip_id=1, instance_id=11, women_only=True)
    out = match(_req(women=True), [snap], women_only_enabled=False)
    assert out == []


def test_match_is_deterministic_on_input_order():
    snaps = [
        _snap(trip_id=t, instance_id=t * 10,
              earliest=_T0 + timedelta(minutes=i * 5))
        for i, t in enumerate([3, 1, 4, 1, 5, 9, 2, 6])
    ]
    a = match(_req(), snaps)
    b = match(_req(), list(reversed(snaps)))
    assert [m.trip_id for m in a] == [m.trip_id for m in b]
    assert [m.instance_id for m in a] == [m.instance_id for m in b]


def test_score_key_is_unique_per_trip_when_other_keys_match():
    a = _snap(trip_id=1, instance_id=11)
    b = _snap(trip_id=2, instance_id=22)
    out = match(_req(), [a, b])
    keys = {m.score_key for m in out}
    assert len(keys) == 2


def test_ranking_worked_example_documented_in_docstring():
    """The 'worked example' from the plan: a rider with window [8:00, 8:10]
    sees trip A (8:00 exact) and trip B (8:20 same group). Trip A wins."""
    a = _snap(trip_id=100, instance_id=1000,
              from_place_id=1, from_place_group="Main",
              earliest=_T0, latest=_T0 + timedelta(minutes=10))
    b = _snap(trip_id=200, instance_id=2000,
              from_place_id=99, from_place_group="Main",
              earliest=_T0 + timedelta(minutes=20),
              latest=_T0 + timedelta(minutes=30))
    out = match(_req(), [b, a])
    assert [m.trip_id for m in out] == [100, 200]
    assert out[0].reason == "exact_pickup"
    assert out[1].reason == "same_group_pickup"


def test_no_violation_property_smoke():
    """Property-style smoke: any non-empty result must satisfy every rule."""
    snaps = [
        _snap(trip_id=1, instance_id=11, from_place_id=1, women_only=True),
        _snap(trip_id=2, instance_id=22, from_place_id=99,
              from_place_group="Main", seats_offered=2, seats_taken=2),
        _snap(trip_id=3, instance_id=33, to_place_id=999),
        _snap(trip_id=4, instance_id=44, driver_id=1),  # self if rider=1
        _snap(trip_id=5, instance_id=55, is_active=False),
    ]
    out = match(_req(rider_id=1, women=False), snaps, women_only_enabled=True)
    for m in out:
        assert m.trip_id != 1  # women-only excluded
        assert m.trip_id != 2  # full excluded
        assert m.trip_id != 3  # wrong to_place
        assert m.trip_id != 4  # self
        assert m.trip_id != 5  # cancelled
