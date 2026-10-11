"""Per-race checks (#43; #17 § Per-race checks and Withdrawals, #9; tiers #97).

Each check reads one race's rows and returns the machine reason it failed, or None. The mayor's
checks stay inside the ward-by-ward file: the two files are separate generations.

Failures are tiered (ADR 0004). A vote-sum mismatch and a Reporting Progress fault are
contained: the candidates' votes stand, a faulty row's progress is hidden and its units in are
unknown to the model, and the reason becomes a check note for the operator. Any other failure
withdraws that race's projection, leaving its Live Tally.
"""

import math

from election_night.feed import Tally, WardByWard, WardTally

POLLS_RECEIVED_ABOVE_POLLS = "polls_received_above_polls"
POLLS_ZERO = "polls_zero"
POLLS_DIFFER_FROM_BUNDLE = "polls_differ_from_bundle"
VOTES_RECEIVED_MISMATCH = "votes_received_mismatch"
WARD_FIELDS_DIFFER = "ward_fields_differ"
WARD_VOTES_COUNTED_MISMATCH = "ward_votes_counted_mismatch"
WARDS_DIFFER_FROM_OFFICE = "wards_differ_from_office"
COUNT_ABOVE_EXPECTED = "count_above_expected"
PROJECTION_NUMERICS = "projection_numerics"

# Tiers 1 and 2 (#97): faults the projection carries on through. A mayoral ward's progress
# faults are these with a `ward_` prefix.
CONTAINED = frozenset(
    {
        VOTES_RECEIVED_MISMATCH,
        WARD_VOTES_COUNTED_MISMATCH,
        WARDS_DIFFER_FROM_OFFICE,
        POLLS_ZERO,
        POLLS_RECEIVED_ABOVE_POLLS,
        POLLS_DIFFER_FROM_BUNDLE,
    }
)


def contained(reason: str) -> bool:
    """Whether a failed check leaves the projection standing (tiers 1 and 2, ADR 0004)."""
    return reason in CONTAINED or reason.removeprefix("ward_") in CONTAINED


def progress(received: int, polls: int, bundle_polls: int) -> str | None:
    """Why a row's Reporting Progress can't be trusted, or None. Such a row hides it."""
    if polls == 0:
        return POLLS_ZERO
    if received > polls:
        return POLLS_RECEIVED_ABOVE_POLLS
    if polls != bundle_polls:
        return POLLS_DIFFER_FROM_BUNDLE
    return None


def votes(tally: Tally) -> str | None:
    """The row's own total against its candidates' votes."""
    return VOTES_RECEIVED_MISMATCH if tally.votes_received != sum(tally.votes.values()) else None


def mayor_wards(w: WardByWard, tally: Tally, wards: list[WardTally]) -> str | None:
    """The ward-by-ward file against itself: the ward fields repeated under every candidate
    are identical, each ward's `votesCounted` is its candidates' sum, and the wards sum to the
    office totals."""
    if not w.repeats_agree():
        return WARD_FIELDS_DIFFER
    if any(ward.votes_counted != sum(ward.votes.values()) for ward in wards):
        return WARD_VOTES_COUNTED_MISMATCH
    summed = (
        sum(ward.polls for ward in wards),
        sum(ward.polls_received for ward in wards),
        sum(ward.votes_counted for ward in wards),
        {key: sum(ward.votes.get(key, 0) for ward in wards) for key in tally.votes},
    )
    if summed != (tally.polls, tally.polls_received, tally.votes_received, tally.votes):
        return WARDS_DIFFER_FROM_OFFICE
    return None


def above_expected(counted: float, top_total: float) -> str | None:
    """A count above the race's expected total at the top of the turnout grid."""
    return COUNT_ABOVE_EXPECTED if counted > top_total else None


def bands(projection: dict) -> str | None:
    """A projection whose numbers fail: a band that isn't finite, out of order, or outside
    0-100%, or an effective sample size that isn't finite."""
    for variant in projection["bands"].values():
        for band in variant.values():
            low, mid, high = band["low"], band["mid"], band["high"]
            if not all(math.isfinite(x) for x in (low, mid, high)):
                return PROJECTION_NUMERICS
            if not 0 <= low <= mid <= high <= 100:
                return PROJECTION_NUMERICS
    ess = projection.get("variant", {}).get("ess")
    if ess is not None and not math.isfinite(ess):
        return PROJECTION_NUMERICS
    return None
