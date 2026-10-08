"""Feed-shaped Count Snapshots: a Replay as the City's two files would have published it.

Step k of an order is the pair published once its first k Reporting Units are in: step 0 is the
night's zeroed pair, and the last step holds the certified totals. Both files take the City's
shape (string counts, candidates re-sorted by votes, separate `seq`s), so the payload function
reads a Replay exactly as it reads the night. `totalVoters` is "0" throughout: electors are not
loaded yet, and the payload never reads them.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from election_night.bundle import build_bundle
from election_night.replay.historical import Night, Race

OFFICE_NAMES = {
    1: "Mayor",
    2: "Councillor",
    3: "Toronto District School Board",
    4: "Toronto Catholic District School Board",
}
STEP_MS = 60_000  # one step a minute after the opening time
WARD_BY_WARD_LAG_MS = 30_000  # the ward-by-ward file's own seq, half a step later


@dataclass(frozen=True)
class Snapshot:
    step: int  # Reporting Units in
    all_office_seq: int
    ward_by_ward_seq: int
    all_office: bytes
    ward_by_ward: bytes


def _dumps(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


class _Cumulative:
    """A race's (or one mayoral ward's) counted votes after each step of an order."""

    def __init__(self, race: Race, night: Night, order: np.ndarray, ward: int | None = None):
        row = {u: i for i, u in enumerate(race.units) if ward is None or u[0] == ward}
        index = np.array([row.get(night.units[i].key, -1) for i in order])
        member = index >= 0
        votes = np.zeros((len(order) + 1, len(race.candidates)), dtype=np.int64)
        votes[1:][member] = race.votes[index[member]]
        self.votes = np.cumsum(votes, axis=0)
        self.received = np.concatenate([[0], np.cumsum(member)])
        self.polls = len(row)


def _ranked(candidates: tuple[str, ...], votes: np.ndarray) -> list[int]:
    """Candidates by votes, descending; ties in ballot order."""
    return sorted(range(len(candidates)), key=lambda c: (-votes[c], c))


def _row(race: Race, cum: _Cumulative, step: int, name: bool) -> dict:
    votes = cum.votes[step]
    total = int(votes.sum())
    row = {"name": race.name} if name else {}
    row |= {
        "num": race.num,
        "polls": str(cum.polls),
        "pollsReceived": str(int(cum.received[step])),
        "totalVoters": "0",
        "votesReceived": str(total),
        "candidate": [
            {
                "name": race.candidates[c],
                "votesReceived": str(int(votes[c])),
                "percentage": f"{100 * votes[c] / total:.2f}" if total else "0.00",
            }
            for c in _ranked(race.candidates, votes)
        ],
    }
    return row


def _opening_ms(night: Night) -> int:
    return int(datetime.fromisoformat(night.opening_time).timestamp() * 1000)


def snapshots(
    night: Night, order: np.ndarray, steps: Iterable[int] | None = None
) -> Iterator[Snapshot]:
    """The order's Count Snapshot pairs at `steps` (default: every step, 0 to all units in)."""
    order = np.asarray(order)
    if sorted(order.tolist()) != list(range(len(night.units))):
        raise ValueError("the order must be a permutation of the night's units")
    cums = [_Cumulative(race, night, order) for race in night.races]
    mayor = night.races[0]
    wards = [(num, name, _Cumulative(mayor, night, order, ward=num)) for num, name in night.wards]
    opening = _opening_ms(night)

    for step in range(len(order) + 1) if steps is None else steps:
        if not 0 <= step <= len(order):
            raise ValueError(f"step {step} outside 0..{len(order)}")
        a_seq = opening + STEP_MS * step
        w_seq = a_seq + WARD_BY_WARD_LAG_MS
        offices = []
        for race, cum in zip(night.races, cums):
            if not offices or offices[-1]["id"] != race.office_id:
                offices.append(
                    {"id": race.office_id, "name": OFFICE_NAMES[race.office_id], "ward": []}
                )
            offices[-1]["ward"].append(_row(race, cum, step, name=race.office_id <= 2))
        all_office = {"electionDesc": night.election_desc, "office": offices, "seq": str(a_seq)}

        citywide = _row(mayor, cums[0], step, name=True)
        ward_rows = {
            c: [
                {
                    "name": name,
                    "num": str(num),
                    "polls": str(cum.polls),
                    "pollsReceived": str(int(cum.received[step])),
                    "totalVoters": "0",
                    "votesCounted": str(int(cum.votes[step].sum())),
                    "votesReceived": str(int(cum.votes[step][c])),
                }
                for num, name, cum in wards
            ]
            for c in range(len(mayor.candidates))
        }
        ward_by_ward = {
            "electionDesc": night.election_desc,
            "office": {
                "name": OFFICE_NAMES[1],
                "polls": citywide["polls"],
                "pollsReceived": citywide["pollsReceived"],
                "totalVoters": "0",
                "votesReceived": citywide["votesReceived"],
                "candidate": [
                    {
                        "name": mayor.candidates[c],
                        "votesReceived": str(int(cums[0].votes[step][c])),
                        "ward": ward_rows[c],
                    }
                    for c in _ranked(mayor.candidates, cums[0].votes[step])
                ],
            },
            "seq": str(w_seq),
        }
        yield Snapshot(step, a_seq, w_seq, _dumps(all_office), _dumps(ward_by_ward))


def zeroed_pair(night: Night) -> Snapshot:
    """The night's step-0 pair: every race laid out, nothing counted."""
    return next(snapshots(night, np.arange(len(night.units)), steps=[0]))


def night_bundle(night: Night) -> dict:
    """The historical Night Bundle: what was known before the night, from its zeroed pair."""
    zero = zeroed_pair(night)
    return build_bundle(zero.all_office, zero.ward_by_ward, opening_time=night.opening_time)
