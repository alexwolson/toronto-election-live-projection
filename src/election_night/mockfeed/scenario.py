"""The Mock Feed scenario: an invented, 2026-shaped true count for the Rehearsals (#34, S6).

Races, Ballot Names, `polls` and `totalVoters` come from the City's 2026 zeroed test files, so the
Night Bundle runs unchanged. Its counts are invented and never presented as real.

Votes are carried over by rank and ward (S6). Per City ward, election-day units (2023's 96
included) are merged or split until the ward has its 2026 `polls`; the Ward Aggregates (97-99)
stay whole. The mayor takes 2023's units, ranked as the final forecast ranks the 2026 field.
Council, TDSB and TCDSB take 2022's, which share units; each 2026 trustee area takes its member
wards' units, each keeping its own 2022 race's vectors. The 2026 trustee map is vendored in
`data/mock-feed/`.
"""

import csv
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

from election_night.bundle import OPENING_2026
from election_night.feed import (
    COUNCILLOR_OFFICE_ID,
    MAYOR_OFFICE_ID,
    Tally,
    WardTally,
    race_id,
    read_all_office,
    read_ward_by_ward,
)
from election_night.gates import ROOT, load_preregistration
from election_night.name_inputs import FORECAST, load_name_inputs
from election_night.names import Candidacy, ForecastUnmatched
from election_night.replay.historical import Night, Race, Unit, load_night
from election_night.replay.orders import arrival_order
from election_night.replay.snapshots import Cumulative


def read_trustee_wards(text: str) -> dict[tuple[int, str], tuple[int, ...]]:
    """Each 2026 trustee area's member City wards, keyed by (office id, area num)."""
    return {
        (int(row["office_code"]), row["ward_id"]): tuple(
            int(w) for w in row["city_wards"].split(";")
        )
        for row in csv.DictReader(text.splitlines())
    }


@dataclass(frozen=True)
class TrueCount:
    """The true count once a step's Reporting Units are in."""

    step: int
    races: dict[str, Tally]  # by race id, candidates in ballot order
    wards: list[WardTally]  # the mayor's count in each City ward


@dataclass(frozen=True, eq=False)
class Scenario:
    """The units' vote vectors, revealed one Reporting Unit per step in a Replay arrival order."""

    seed: int
    night: Night  # every 2026 race, on the scenario's Reporting Units
    order: np.ndarray  # the arrival order, as indices into `night.units`
    # The zeroed test files the scenario is shaped on: the Mock Feed (#37) serves their layout,
    # names and `totalVoters` with the true count's figures.
    all_office: bytes
    ward_by_ward: bytes

    @cached_property
    def _cums(self) -> dict[str, tuple[Race, Cumulative]]:
        return {
            race_id(r.office_id, r.num): (r, Cumulative(r, self.night, self.order))
            for r in self.night.races
        }

    @cached_property
    def _wards(self) -> list[tuple[int, str | None, Cumulative]]:
        return [
            (num, name, Cumulative(self.night.mayor, self.night, self.order, ward=num))
            for num, name in self.night.wards
        ]

    @property
    def steps(self) -> int:
        return len(self.order)

    def true_count(self, step: int) -> TrueCount:
        """The reference for the Rehearsals' exact-tallies check at `step` units in."""
        if not 0 <= step <= self.steps:
            raise ValueError(f"step {step} outside 0..{self.steps}")
        races = {
            rid: Tally(
                polls=cum.polls,
                polls_received=int(cum.received[step]),
                votes=dict(zip(race.candidates, cum.votes[step].tolist())),
                votes_received=int(cum.votes[step].sum()),
            )
            for rid, (race, cum) in self._cums.items()
        }
        mayor = self.night.mayor
        wards = [
            WardTally(
                num=str(num),
                name=name,
                polls=cum.polls,
                polls_received=int(cum.received[step]),
                votes_counted=int(cum.votes[step].sum()),
                votes=dict(zip(mayor.candidates, cum.votes[step].tolist())),
            )
            for num, name, cum in self._wards
        ]
        return TrueCount(step, races, wards)

    def count_snapshot(self, step: int) -> tuple[bytes, bytes]:
        """The all-office and ward-by-ward files at `step`, in the test files' own layout.

        Each row keeps the test file's names, `polls` and `totalVoters` and takes the true count's
        figures as strings, with candidates re-sorted by votes (ties in ballot order). The `seq`s
        and `electionDesc` are the test files'; the Mock Feed (#37) stamps its own.
        """
        count = self.true_count(step)
        all_office = json.loads(self.all_office)
        for office in all_office["office"]:
            for row in office["ward"]:
                _fill(row, count.races[race_id(office["id"], row["num"])])
        ward_by_ward = json.loads(self.ward_by_ward)
        office = ward_by_ward["office"]
        mayor = count.races[race_id(MAYOR_OFFICE_ID, "0")]
        office["pollsReceived"] = str(mayor.polls_received)
        office["votesReceived"] = str(sum(mayor.votes.values()))
        wards = {t.num: t for t in count.wards}
        for candidate in office["candidate"]:
            candidate["votesReceived"] = str(mayor.votes[candidate["name"]])
            for row in candidate["ward"]:
                ward = wards[row["num"]]
                row["pollsReceived"] = str(ward.polls_received)
                row["votesCounted"] = str(ward.votes_counted)
                row["votesReceived"] = str(ward.votes[candidate["name"]])
        office["candidate"] = _by_votes(office["candidate"])
        return _dumps(all_office), _dumps(ward_by_ward)


def _by_votes(candidates: list[dict]) -> list[dict]:
    """Candidates by votes, descending, as the City sorts them; ties keep ballot order."""
    return sorted(candidates, key=lambda c: -int(c["votesReceived"]))


def _fill(row: dict, tally: Tally) -> None:
    total = sum(tally.votes.values())
    row["pollsReceived"] = str(tally.polls_received)
    row["votesReceived"] = str(total)
    for candidate in row["candidate"]:
        votes = tally.votes[candidate["name"]]
        candidate["votesReceived"] = str(votes)
        candidate["percentage"] = f"{100 * votes / total:.2f}" if total else "0.00"
    row["candidate"] = _by_votes(row["candidate"])


def _dumps(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _member_wards(
    office_id: int, num: str, trustee_wards: dict[tuple[int, str], tuple[int, ...]]
) -> tuple[int, ...] | None:
    """The City wards a race covers; None for the mayor's, which covers them all."""
    if office_id == MAYOR_OFFICE_ID:
        return None
    if office_id == COUNCILLOR_OFFICE_ID:
        return (int(num),)
    return trustee_wards[(office_id, num)]


def _rows(race: Race, ward: int, codes: list[int]) -> np.ndarray:
    """A source race's vote rows for one City ward's units, in `codes` order."""
    index = {u: i for i, u in enumerate(race.units)}
    return race.votes[[index[(ward, c)] for c in codes]]


def _fit(rows: np.ndarray, size_columns: int, n: int) -> np.ndarray:
    """S6: merge the two smallest election-day units, or split the largest, until there are `n`.

    A unit's size is its first `size_columns` columns' votes (the source night's mayoral vote);
    ties go to the earlier unit. A merge keeps the earlier position; a split halves every column,
    the earlier half taking the odd vote.
    """
    rows = list(rows)

    def size(k: int) -> int:
        return int(rows[k][:size_columns].sum())

    while len(rows) > n:
        i, j = sorted(sorted(range(len(rows)), key=lambda k: (size(k), k))[:2])
        rows[i] = rows[i] + rows.pop(j)
    while len(rows) < n:
        k = min(range(len(rows)), key=lambda k: (-size(k), k))
        half = rows[k] // 2
        rows[k : k + 1] = [rows[k] - half, half]
    return np.array(rows, dtype=np.int64)


def _fitted_wards(
    night: Night, offices: list[int], aggregate_codes: list[int], target: dict[int, int]
) -> dict[int, dict[int, tuple[Race, np.ndarray]]]:
    """Each City ward's units fitted to `target` election-day units, for the source's `offices`.

    Returns ward -> office id -> (the source race covering the ward, its rows: the fitted
    election-day units, then the Ward Aggregates in `aggregate_codes` order). The offices share
    units, so they are fitted together, sized by the source night's mayoral vote.
    """
    fitted = {}
    for ward, n in target.items():
        source_codes = sorted(c for w, c in night.mayor.units if w == ward)
        if sorted(set(source_codes) & set(aggregate_codes)) != aggregate_codes:
            raise ValueError(f"{night.year} ward {ward} lacks a Ward Aggregate")
        day = [c for c in source_codes if c not in aggregate_codes]
        races = [night.mayor] + [
            next(r for r in night.races if r.office_id == o and (ward, day[0]) in r.units)
            for o in offices
            if o != MAYOR_OFFICE_ID
        ]
        widths = [len(r.candidates) for r in races]
        day_rows = _fit(np.hstack([_rows(r, ward, day) for r in races]), widths[0], n)
        agg_rows = np.hstack([_rows(r, ward, aggregate_codes) for r in races])
        rows = np.vstack([day_rows, agg_rows])
        edges = np.cumsum([0] + widths)
        blocks = {r.office_id: (r, rows[:, edges[i] : edges[i + 1]]) for i, r in enumerate(races)}
        fitted[ward] = {o: blocks[o] for o in offices}
    return fitted


def _carry(source: Race, rows: np.ndarray, m: int) -> np.ndarray:
    """S6: the source's vectors by rank onto `m` candidates in carry order.

    The k-th candidate takes the source's k-th ranked vector (certified total, ties in ballot
    order); extra source vectors fold into the last, and extra candidates get 0.
    """
    rank = sorted(range(len(source.candidates)), key=lambda c: (-source.certified[c], c))
    out = np.zeros((len(rows), m), dtype=np.int64)
    for k, c in enumerate(rank):
        out[:, min(k, m - 1)] += rows[:, c]
    return out


def forecast_rank(forecast: dict, mayor_candidacies: dict[str, Candidacy]) -> list[str]:
    """The forecast's named mayoral candidates as Ballot Names, by election-day median share.

    Forecast ids join to Ballot Names by `person_id` through the canonical, as the bundle's do.
    """
    names = {c.person_id: name for name, c in mayor_candidacies.items() if c.person_id}
    ranked = sorted(forecast["election_day"]["candidates"], key=lambda c: -c["median"])
    missing = [c["candidate_id"] for c in ranked if c["candidate_id"] not in names]
    if missing:
        raise ForecastUnmatched(f"forecast candidates on no mayoral row: {missing}")
    return [names[c["candidate_id"]] for c in ranked]


def build_scenario(
    all_office: bytes,
    ward_by_ward: bytes,
    trustee_wards: dict[tuple[int, str], tuple[int, ...]],
    mayor_source: Night,
    council_source: Night,
    mayor_rank: list[str],
    prereg: dict,
    seed: int,
) -> Scenario:
    """The scenario on the zeroed test files, carried over from the two source nights by S6.

    The mayor comes from `mayor_source` (2023), council and the English boards from
    `council_source` (2022). Mayoral candidates take 2023's ranks in `mayor_rank`'s order (the
    forecast's), then in ballot order; everyone else takes 2022's in ballot order. The French
    boards have no workbooks, so their candidates get 0 votes. The arrival order is the
    pre-registered "late" pattern's `seed`th order, so the Ward Aggregates come in last.
    """
    a = read_all_office(all_office)
    w = read_ward_by_ward(ward_by_ward)
    aggregate_codes = sorted(prereg["arrival_orders"]["ward_aggregates"]["codes"])
    day_units = {int(t.num): t.polls - len(aggregate_codes) for t in w.wards()}
    mayor_rows = _fitted_wards(mayor_source, [MAYOR_OFFICE_ID], aggregate_codes, day_units)
    other_rows = _fitted_wards(
        council_source, [COUNCILLOR_OFFICE_ID, 3, 4], aggregate_codes, day_units
    )

    def ward_codes(ward: int) -> list[int]:
        return list(range(1, day_units[ward] + 1)) + aggregate_codes

    units = [
        Unit(ward, c, c in aggregate_codes) for ward in sorted(day_units) for c in ward_codes(ward)
    ]
    races = []
    for office_id, num in sorted(a.rows, key=lambda k: (k[0], int(k[1]))):
        candidates = tuple(a.tally(office_id, num).votes)
        carry = list(candidates)
        if office_id == MAYOR_OFFICE_ID:
            carry = mayor_rank + [c for c in candidates if c not in mayor_rank]
        columns = [carry.index(c) for c in candidates]
        wards = _member_wards(office_id, num, trustee_wards) or tuple(sorted(day_units))
        keys, blocks = [], []
        for ward in sorted(wards):
            keys += [(ward, c) for c in ward_codes(ward)]
            fitted = (mayor_rows if office_id == MAYOR_OFFICE_ID else other_rows)[ward]
            if office_id in fitted:
                source, rows = fitted[office_id]
                blocks.append(_carry(source, rows, len(candidates))[:, columns])
            else:
                blocks.append(np.zeros((len(ward_codes(ward)), len(candidates)), dtype=np.int64))
        votes = np.vstack(blocks)
        races.append(
            Race(
                office_id=office_id,
                num=num,
                name=a.rows[(office_id, num)].get("name"),
                candidates=candidates,
                units=tuple(keys),
                votes=votes,
                certified=votes.sum(axis=0),
            )
        )
    night = Night(
        year=2026,
        opening_time=OPENING_2026,
        election_desc=a.election_desc,
        units=tuple(units),
        wards=tuple((int(t.num), t.name) for t in w.wards()),
        races=tuple(races),
    )
    order = arrival_order(night, prereg, "late", seed)
    return Scenario(seed, night, order, all_office, ward_by_ward)


def load_scenario(seed: int, root: Path = ROOT) -> Scenario:
    """The scenario from the inputs vendored in this repo."""
    city = root / "tests" / "fixtures" / "feed" / "city-2026"
    prereg = load_preregistration(root / "gates" / "preregistration.json")
    inputs = root / "data" / "night-bundle" / "inputs"
    names = load_name_inputs(inputs)
    forecast = json.loads((inputs / FORECAST).read_text(encoding="utf-8"))
    return build_scenario(
        (city / "unofficialresult.json").read_bytes(),
        (city / "unofficialresult-wardbyward.json").read_bytes(),
        read_trustee_wards((root / "data" / "mock-feed" / "trustee_wards_2026.csv").read_text()),
        load_night(2023, prereg),
        load_night(2022, prereg),
        forecast_rank(forecast, names.canonical[race_id(MAYOR_OFFICE_ID, "0")]),
        prereg,
        seed,
    )
