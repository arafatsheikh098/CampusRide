"""Pure matching engine (F5).

Given a rider's request and a set of candidate trip instances, return a
deterministically ordered list of matches. A match explains *why* the trip
fits the rider (exact pickup, same group, close time) so the UI can show
a "reason" chip.

This module is pure: it does not import FastAPI, SQLModel, or any
database driver. The route layer hydrates the inputs and calls match().

Ranking rules (in order):
    1. exact pickup place over same-group pickup
    2. smaller absolute time difference between the rider's window
       centre and the trip's earliest_departure
    3. more seats free (seats_offered - seats_taken)
    4. lower trip id (stable, deterministic)

Excluded (hard filter):
    * trip status != ACTIVE
    * to_place_id != rider's to_place_id
    * from_place_id not matching rider's request (exact or same group)
    * driver_id == rider.id (no self-match)
    * any instance in `blocks` between the rider and the driver
    * seats_taken >= seats_offered (full)
    * the trip has already left (latest_departure < rider's earliest)
    * the trip starts more than `time_tolerance_minutes` after the
      rider's window end
    * women-only trip and the rider is not women-only-eligible
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence, Set, Tuple


@dataclass(frozen=True)
class MatchRequest:
    """A rider's search request, fully resolved (no DB calls)."""

    rider_id: int
    from_place_id: int
    from_place_group: str
    to_place_id: int
    earliest: datetime       # tz-aware
    latest: datetime         # tz-aware
    riders_women_only_eligible: bool = False


@dataclass(frozen=True)
class TripSnapshot:
    """A trip and its parent instance, fully resolved."""

    trip_id: int
    instance_id: int
    driver_id: int
    from_place_id: int
    from_place_group: str
    to_place_id: int
    earliest_departure: datetime
    latest_departure: datetime
    seats_offered: int
    seats_taken: int
    women_only: bool
    is_active: bool          # instance.status == ACTIVE


@dataclass(frozen=True)
class Match:
    trip_id: int
    instance_id: int
    score_key: Tuple[int, int, int, int]  # lower is better
    reason: str  # "exact_pickup_close_time" | "same_group_close_time" | ...


# Reason tokens. Exposed as constants so the template/i18n layer can map
# them to translated strings.
REASON_EXACT_PICKUP = "exact_pickup"
REASON_SAME_GROUP_PICKUP = "same_group_pickup"


def _as_aware_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC so the route layer (SQLite) and pure
    tests (with explicit UTC) compare safely."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _window_centre(req: MatchRequest) -> datetime:
    """Midpoint of the rider's [earliest, latest] window (UTC-aware)."""
    e_aw = _as_aware_utc(req.earliest)
    l_aw = _as_aware_utc(req.latest)
    delta = (l_aw - e_aw).total_seconds()
    mid = e_aw.timestamp() + delta / 2.0
    return datetime.fromtimestamp(mid, tz=timezone.utc)


def _overlap_ok(
    *,
    trip: TripSnapshot,
    req: MatchRequest,
    time_tolerance_minutes: int,
) -> bool:
    """Return True if the trip's departure window overlaps the rider's
    window within `time_tolerance_minutes`.

    Rules:
        * The trip must not already have left: its latest_departure
          must be at or after the rider's earliest (the trip is still
          upcoming when the rider is ready to go).
        * The trip's earliest_departure must be at or before
          (rider_latest + tol): the rider can wait up to `tol` minutes
          past their window for the trip to actually start.
    """
    tol = time_tolerance_minutes
    trip_earliest = _as_aware_utc(trip.earliest_departure)
    trip_latest = _as_aware_utc(trip.latest_departure)
    req_earliest = _as_aware_utc(req.earliest)
    req_latest = _as_aware_utc(req.latest)
    # Trip must still be running when the rider's window opens.
    if trip_latest < req_earliest:
        return False
    # Trip must not start too late for the rider.
    rider_latest_plus_tol = req_latest.timestamp() + tol * 60
    if trip_earliest.timestamp() > rider_latest_plus_tol:
        return False
    return True


def _is_blocked(
    rider_id: int, driver_id: int, blocks: Iterable[Tuple[int, int]]
) -> bool:
    """blocks yields (blocker_id, blocked_id) pairs."""
    for blocker_id, blocked_id in blocks:
        # Either side can block the other.
        if (blocker_id == rider_id and blocked_id == driver_id) or (
            blocker_id == driver_id and blocked_id == rider_id
        ):
            return True
    return False


def _pickup_match(trip: TripSnapshot, req: MatchRequest) -> int:
    """Return 0 (exact), 1 (same group) or -1 (no match)."""
    if trip.from_place_id == req.from_place_id:
        return 0
    if trip.from_place_group and trip.from_place_group == req.from_place_group:
        return 1
    return -1


def match(
    req: MatchRequest,
    trips: Sequence[TripSnapshot],
    blocks: Iterable[Tuple[int, int]] = (),
    *,
    time_tolerance_minutes: int = 15,
    women_only_enabled: bool = False,
) -> List[Match]:
    """Return a list of `Match` objects sorted by ranking key (asc).

    `trips` should already be pre-filtered to `to_place_id == req.to_place_id`
    by the caller for efficiency; this function re-checks defensively.
    """
    blocks_set: Set[Tuple[int, int]] = set(blocks)
    centre = _window_centre(req)
    out: List[Match] = []
    for t in trips:
        if not t.is_active:
            continue
        if t.to_place_id != req.to_place_id:
            continue
        if t.driver_id == req.rider_id:
            continue
        if t.seats_offered - t.seats_taken <= 0:
            continue
        if t.women_only:
            if not women_only_enabled or not req.riders_women_only_eligible:
                continue
        pickup_rank = _pickup_match(t, req)
        if pickup_rank < 0:
            continue
        if not _overlap_ok(
            trip=t, req=req, time_tolerance_minutes=time_tolerance_minutes,
        ):
            continue
        if _is_blocked(req.rider_id, t.driver_id, blocks_set):
            continue
        # Time difference in whole minutes (smaller is better).
        t_earliest = _as_aware_utc(t.earliest_departure)
        diff_seconds = abs((t_earliest - centre).total_seconds())
        diff_minutes = int(diff_seconds // 60)
        seats_free = t.seats_offered - t.seats_taken
        # We want more seats free to rank higher -> invert with a large
        # constant so the order is stable across small N.
        seats_score = 1_000 - seats_free
        key = (pickup_rank, diff_minutes, seats_score, t.trip_id)
        reason = (
            REASON_EXACT_PICKUP if pickup_rank == 0 else REASON_SAME_GROUP_PICKUP
        )
        out.append(
            Match(
                trip_id=t.trip_id,
                instance_id=t.instance_id,
                score_key=key,
                reason=reason,
            )
        )
    out.sort(key=lambda m: m.score_key)
    return out


def reasons() -> List[str]:
    """Public list of reason tokens. The route layer maps these to
    human-readable strings via i18n."""
    return [REASON_EXACT_PICKUP, REASON_SAME_GROUP_PICKUP]
