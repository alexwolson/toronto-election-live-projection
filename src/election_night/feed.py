"""Reading the City's two election-night results files.

A file is rejected only when it is unreadable: a status other than 200 or 304, a body that isn't
JSON, or a missing or renamed structural key (`seq`, `office`, the ward or candidate arrays).
Everything finer is read race by race, so one bad row can't sink the pair.
"""

import json
from dataclasses import dataclass

# Office ids are fixed in the City's spec: (race id prefix, office level).
OFFICES = {
    1: ("mayor", "mayor"),
    2: ("councillor", "council"),
    3: ("tdsb", "trustee"),
    4: ("tcdsb", "trustee"),
    5: ("viamonde", "french_trustee"),
    6: ("monavenir", "french_trustee"),
}
MAYOR_OFFICE_ID = 1
COUNCILLOR_OFFICE_ID = 2


def race_id(office_id: int, num: str) -> str:
    prefix = OFFICES[office_id][0]
    return prefix if office_id == MAYOR_OFFICE_ID else f"{prefix}-{num}"


class UnreadableFile(ValueError):
    """A City file that can't be read at all, so its pair is rejected."""


class UnreadableRow(ValueError):
    """One race's row that can't be read; only that race is affected."""


def check_status(status: int) -> None:
    """Reject a response whose status is neither 200 nor 304."""
    if status not in (200, 304):
        raise UnreadableFile(f"status {status}")


def count(value) -> int:
    """A count as the City writes it: a string of digits."""
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise UnreadableRow(f"not a count: {value!r}")
    return int(value)


@dataclass(frozen=True)
class Tally:
    """One race's counted votes, as its row in a Count Snapshot publishes them."""

    polls: int
    polls_received: int
    votes: dict[str, int]  # Ballot Name -> votes, in the feed's order
    votes_received: int  # the row's own total, which the checks compare with the candidates'


@dataclass(frozen=True)
class WardTally:
    num: str
    name: str | None
    polls: int
    polls_received: int
    votes_counted: int
    votes: dict[str, int]


@dataclass(frozen=True)
class AllOffice:
    """The all-office file: one row per race, keyed by (office id, ward num)."""

    seq: int
    election_desc: str | None
    rows: dict[tuple[int, str], dict]

    def tally(self, office_id: int, num: str) -> Tally:
        """The race's tally; raises KeyError if absent and UnreadableRow if unreadable."""
        row = self.rows[(office_id, num)]
        return Tally(
            polls=count(row.get("polls")),
            polls_received=count(row.get("pollsReceived")),
            votes=_votes(row["candidate"]),
            votes_received=count(row.get("votesReceived")),
        )


@dataclass(frozen=True)
class WardByWard:
    """The mayor-by-ward file."""

    seq: int
    election_desc: str | None
    office: dict

    def tally(self) -> Tally:
        return Tally(
            polls=count(self.office.get("polls")),
            polls_received=count(self.office.get("pollsReceived")),
            votes=_votes(self.office["candidate"]),
            votes_received=count(self.office.get("votesReceived")),
        )

    def wards(self) -> list[WardTally]:
        """Each ward's mayoral vote. The ward fields are read from the first candidate."""
        candidates = self.office["candidate"]
        if not candidates:
            return []
        wards = []
        for i, first in enumerate(candidates[0]["ward"]):
            if not isinstance(first, dict) or not isinstance(first.get("num"), str):
                raise UnreadableRow("ward row without a num")
            votes = {}
            for candidate in candidates:
                entry = candidate["ward"][i] if i < len(candidate["ward"]) else None
                if not isinstance(entry, dict) or entry.get("num") != first["num"]:
                    raise UnreadableRow(f"ward {first['num']} misaligned")
                _add(votes, candidate.get("name"), count(entry.get("votesReceived")))
            name = first.get("name")
            wards.append(
                WardTally(
                    num=first["num"],
                    name=name if isinstance(name, str) else None,
                    polls=count(first.get("polls")),
                    polls_received=count(first.get("pollsReceived")),
                    votes_counted=count(first.get("votesCounted")),
                    votes=votes,
                )
            )
        return wards

    def repeats_agree(self) -> bool:
        """Whether every candidate repeats each ward's fields exactly as the first one does.
        Call after `wards()`, which rejects a ward row that isn't an object or is misaligned."""
        candidates = self.office["candidate"]
        if not candidates:
            return True

        def fields(entry: dict) -> dict:
            return {k: v for k, v in entry.items() if k != "votesReceived"}

        first = [fields(entry) for entry in candidates[0]["ward"]]
        return all([fields(entry) for entry in c["ward"]] == first for c in candidates[1:])


def _add(votes: dict[str, int], name, n: int) -> None:
    if not isinstance(name, str) or name in votes:
        raise UnreadableRow(f"bad or repeated candidate name: {name!r}")
    votes[name] = n


def _votes(candidates: list) -> dict[str, int]:
    votes: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise UnreadableRow("candidate is not an object")
        _add(votes, candidate.get("name"), count(candidate.get("votesReceived")))
    return votes


def _load(body: bytes) -> dict:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise UnreadableFile(f"not JSON: {error}") from None
    if not isinstance(data, dict):
        raise UnreadableFile("not a JSON object")
    return data


def _seq(data: dict) -> int:
    try:
        return count(data.get("seq"))
    except UnreadableRow:
        raise UnreadableFile("missing or unreadable seq") from None


def _array(parent: dict, key: str, where: str) -> list:
    value = parent.get(key) if isinstance(parent, dict) else None
    if not isinstance(value, list):
        raise UnreadableFile(f"missing {key} array in {where}")
    return value


def _desc(data: dict) -> str | None:
    desc = data.get("electionDesc")
    return desc if isinstance(desc, str) else None


def read_all_office(body: bytes) -> AllOffice:
    data = _load(body)
    rows = {}
    for office in _array(data, "office", "the file"):
        for ward in _array(office, "ward", "an office"):
            _array(ward, "candidate", "a ward")
            office_id, num = office.get("id"), ward.get("num")
            if type(office_id) is int and isinstance(num, str):
                rows[(office_id, num)] = ward
    return AllOffice(seq=_seq(data), election_desc=_desc(data), rows=rows)


def read_ward_by_ward(body: bytes) -> WardByWard:
    data = _load(body)
    office = data.get("office")
    if not isinstance(office, dict):
        raise UnreadableFile("missing office object")
    for candidate in _array(office, "candidate", "the office"):
        _array(candidate, "ward", "a candidate")
    return WardByWard(seq=_seq(data), election_desc=_desc(data), office=office)
