"""Property tests for the matching engine (F5).

These use Hypothesis to generate random requests and trip sets. The
properties are:

    * no violation: every match in the output satisfies a hard filter.
    * deterministic ordering: input order does not change the result.
    * result is a subset of the input (never returns trips the input
      doesn't contain).
    * exact-pickup trips always rank before same-group-only trips
      against the same request.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from hypothesis import given, settings, strategies as st

from app.matching import MatchRequest, TripSnapshot, match


_BASE = datetime(2026, 3, 5, 8, 0, tzinfo=timezone.utc)

_driver_ids = st.integers(min_value=1, max_value=1_000)
_place_ids = st.integers(min_value=1, max_value=200)
_groups = st.sampled_from(["Main", "North", "South", "East", "West"])


@st.composite
def requests(draw):
    rider_id = draw(_driver_ids)
    to_id = draw(_place_ids)
    # rider's window somewhere on the same UTC day, between 0 and 12 hours
    # after the baseline, plus a width of 0 to 30 minutes.
    e_offset = draw(st.integers(min_value=0, max_value=12 * 60))
    w_width = draw(st.integers(min_value=0, max_value=30))
    e_aw = _BASE + timedelta(minutes=e_offset)
    l_aw = e_aw + timedelta(minutes=w_width)
    women = draw(st.booleans())
    return MatchRequest(
        rider_id=rider_id,
        from_place_id=draw(_place_ids),
        from_place_group=draw(_groups),
        to_place_id=to_id,
        earliest=e_aw,
        latest=l_aw,
        riders_women_only_eligible=women,
    )


@st.composite
def snapshots(draw, *, n_max=8):
    out: List[TripSnapshot] = []
    n = draw(st.integers(min_value=0, max_value=n_max))
    for _ in range(n):
        trip_id = draw(_driver_ids)
        instance_id = draw(_driver_ids)
        driver_id = draw(_driver_ids)
        fpid = draw(_place_ids)
        fpg = draw(_groups)
        tpid = draw(_place_ids)
        e_off = draw(st.integers(min_value=-60, max_value=12 * 60 + 60))
        w_w = draw(st.integers(min_value=0, max_value=30))
        early = _BASE + timedelta(minutes=e_off)
        late = early + timedelta(minutes=w_w)
        seats_off = draw(st.integers(min_value=1, max_value=6))
        seats_taken = draw(st.integers(min_value=0, max_value=seats_off))
        women = draw(st.booleans())
        active = draw(st.booleans())
        out.append(
            TripSnapshot(
                trip_id=trip_id,
                instance_id=instance_id,
                driver_id=driver_id,
                from_place_id=fpid,
                from_place_group=fpg,
                to_place_id=tpid,
                earliest_departure=early,
                latest_departure=late,
                seats_offered=seats_off,
                seats_taken=seats_taken,
                women_only=women,
                is_active=active,
            )
        )
    return out


@given(req=requests(), trips=snapshots())
@settings(max_examples=50, deadline=None)
def test_no_violation_property(req, trips):
    out = match(req, trips, time_tolerance_minutes=15,
                women_only_enabled=False)
    for m in out:
        snap = next(s for s in trips if s.trip_id == m.trip_id)
        # (1) active
        assert snap.is_active
        # (2) to_place matches
        assert snap.to_place_id == req.to_place_id
        # (3) not self
        assert snap.driver_id != req.rider_id
        # (4) seats free
        assert snap.seats_offered - snap.seats_taken > 0
        # (5) pickup matches (exact or same group)
        assert (snap.from_place_id == req.from_place_id
                or snap.from_place_group == req.from_place_group)


@given(req=requests(), trips=snapshots())
@settings(max_examples=50, deadline=None)
def test_deterministic_property(req, trips):
    a = match(req, trips, time_tolerance_minutes=15,
              women_only_enabled=False)
    b = match(req, list(reversed(trips)), time_tolerance_minutes=15,
              women_only_enabled=False)
    assert [m.trip_id for m in a] == [m.trip_id for m in b]
    assert [m.instance_id for m in a] == [m.instance_id for m in b]


@given(req=requests(), trips=snapshots())
@settings(max_examples=50, deadline=None)
def test_result_is_subset_property(req, trips):
    out = match(req, trips, time_tolerance_minutes=15,
                women_only_enabled=False)
    input_ids = {s.trip_id for s in trips}
    for m in out:
        assert m.trip_id in input_ids


def test_exact_pickup_wins_against_same_group_smoke():
    # Hand-built scenario that has both kinds and a single request.
    req = MatchRequest(
        rider_id=999,
        from_place_id=1, from_place_group="Main",
        to_place_id=2,
        earliest=_BASE, latest=_BASE + timedelta(minutes=15),
    )
    a = TripSnapshot(
        trip_id=10, instance_id=110, driver_id=50,
        from_place_id=99, from_place_group="Main",  # same group
        to_place_id=2,
        earliest_departure=_BASE,
        latest_departure=_BASE + timedelta(minutes=10),
        seats_offered=3, seats_taken=0,
        women_only=False, is_active=True,
    )
    b = TripSnapshot(
        trip_id=20, instance_id=220, driver_id=60,
        from_place_id=1, from_place_group="Main",  # exact
        to_place_id=2,
        earliest_departure=_BASE,
        latest_departure=_BASE + timedelta(minutes=10),
        seats_offered=3, seats_taken=0,
        women_only=False, is_active=True,
    )
    out = match(req, [a, b])
    assert [m.trip_id for m in out] == [20, 10]
