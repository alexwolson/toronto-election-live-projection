"""A replayed night's projection inputs, built only from what was known before it (#33).

`fold_projection(target, nights, prereg)` gives the Night Bundle additions for one replayed
night: each level's parameters, fitted on the other nights (ADR 0029), and each race's
expected-total inputs. The mayor's are one entry per City ward, with an office ratio of 1
(#36). From the target night it reads only its structure (wards,
units, which codes are Ward Aggregates), its pre-night electors and its released advance figure;
never its votes.

Expected totals (#17 § Size of the Outstanding Vote): a race's expected votes in a City ward are
electors x the ward's historical mayoral turnout relative to the city x the office's historical
votes per mayoral vote in that ward, per unit of citywide turnout. 2014's 44 wards have no
comparable history, so there the turnout ratio is 1 and the office ratio is citywide.

Ward Aggregates (S5): advance aggregates are sized from the released advance figure, a ward table
if one was released, else the citywide figure split by the other nights' ward shares, else (no
figure released) each code is a historical share of the ward's total, as mail is. 2014's 44
wards have no ward shares in any other night, so there it is split by electors (an assumption, #33), then split across the night's advance codes by their historical shares. Mail
(97 from 2022) is a historical share of the ward's total. Each code's spread is its share of ward
votes' pooled coefficient of variation across wards, on the other nights where it meant the same
channel.
"""

import csv
from functools import cache

import numpy as np
import openpyxl
import xlrd

from election_night.feed import race_id
from election_night.gates import ROOT
from election_night.projection.fit import fit_level, fit_mayor
from election_night.replay.historical import Night, Race, Unit

VOTER_STATISTICS = ROOT / "data" / "historical" / "voter_statistics"
ELECTOR_FILES = {
    2014: "2014-voter-statistics.xls",
    2018: "2018_Voter_Turnout_Statistics_FINAL.XLSX",
    2022: "2022_voter_turnout_statistics_final.xlsx",
    2023: "2023-mayoral-by-election-voter-statistics-1.xlsx",
}
ADVANCE_TABLE = ROOT / "data" / "historical" / "advance_turnout" / "advance_turnout_as_released.csv"

# What each Ward Aggregate code was on each night, as the City published it beforehand
# (research 03 § 3). 96 is always an election-day unit.
CHANNELS = {
    2014: {97: "advance", 99: "advance"},
    2018: {97: "advance", 98: "advance", 99: "advance"},
    2022: {97: "mail", 98: "advance", 99: "advance"},
    2023: {97: "mail", 98: "advance", 99: "advance"},
    # Inferred: the 2026 feed can't show its codes (research 01 § 3).
    2026: {97: "mail", 98: "advance", 99: "advance"},
}
AGGREGATE_CODES_2026 = (97, 98, 99)
LEVEL_OFFICES = {"council": (2,), "trustee": (3, 4)}
MAYOR = 1


@cache
def ward_electors(year: int) -> dict[int, int]:
    """Each City ward's pre-night electors: the voter statistics' "Total Electors", summed."""
    path = VOTER_STATISTICS / ELECTOR_FILES[year]
    if path.suffix == ".xls":
        book = xlrd.open_workbook(path)
        sheets = [[s.row_values(r) for r in range(s.nrows)] for s in book.sheets()]
    else:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets = [[list(r) for r in s.iter_rows(values_only=True)] for s in book.worksheets]
        book.close()
    for rows in sheets:
        header = [" ".join(str(c or "").split()) for c in rows[0]] if rows else []
        if header[:2] != ["Ward", "Sub"] or "Total Electors" not in header:
            continue
        column = header.index("Total Electors")
        electors: dict[int, int] = {}
        for row in rows[1:]:
            if isinstance(row[0], (int, float)) and isinstance(row[column], (int, float)):
                electors[int(row[0])] = electors.get(int(row[0]), 0) + int(row[column])
        return electors
    raise ValueError(f"{path.name}: no voter turnout sheet")


# The released advance figure (S5): its ladder path, the citywide figure and any ward table.
Released = tuple[str, int | None, dict[int, int]]


def _released(year: int, prereg: dict) -> Released:
    """The released advance figure (S5): its path, the citywide figure and any ward table."""
    night = prereg["ward_aggregate_paths"]["nights"][str(year)]
    wards = {}
    if night["path"] == "ward_table":
        with ADVANCE_TABLE.open(encoding="utf-8") as f:
            wards = {
                int(r["ward"]): int(r["advance_voters"])
                for r in csv.DictReader(f)
                if r["election_year"] == str(year) and r["scope"] == "ward"
            }
    return night["path"], night["advance_voters"], wards


class _Votes:
    """One night's votes by City ward: per office, and the mayor's per Ward Aggregate channel."""

    def __init__(self, night: Night):
        self.year = night.year
        self.wards = [num for num, _ in night.wards]
        self.electors = ward_electors(night.year)
        self.office: dict[int, dict[int, float]] = {}
        for race in night.races:
            by_ward = self.office.setdefault(race.office_id, {})
            for (ward, _), total in zip(race.units, race.votes.sum(axis=1)):
                by_ward[ward] = by_ward.get(ward, 0.0) + float(total)
        mayor = night.mayor
        self.code: dict[int, dict[int, float]] = {}  # code -> ward -> mayoral votes
        for (ward, code), total in zip(mayor.units, mayor.votes.sum(axis=1)):
            if code in CHANNELS[night.year]:
                self.code.setdefault(code, {})[ward] = float(total)

    def channel(self, name: str) -> dict[int, float]:
        votes: dict[int, float] = {}
        for code, kind in CHANNELS[self.year].items():
            if kind == name:
                for ward, v in self.code.get(code, {}).items():
                    votes[ward] = votes.get(ward, 0.0) + v
        return votes

    @property
    def mayor(self) -> dict[int, float]:
        return self.office[MAYOR]

    def turnout(self) -> float:
        return sum(self.mayor.values()) / sum(self.electors[w] for w in self.wards)


def _mean(values: list[float], default: float) -> float:
    return float(np.mean(values)) if values else default


def _cv(shares_by_night: list[np.ndarray]) -> float | None:
    cvs = [s.std() / s.mean() for s in shares_by_night if len(s) > 1 and s.mean() > 0]
    return float(np.sqrt(np.mean(np.square(cvs)))) if cvs else None


def _spread(history: list[_Votes], code: int, kind: str) -> float:
    """The code's share of ward votes, on the nights it meant the same channel: its coefficient
    of variation across wards, pooled. A code with no such night takes its channel's."""
    by_code = [
        np.array([v / h.mayor[w] for w, v in h.code[code].items() if h.mayor.get(w)])
        for h in history
        if CHANNELS[h.year].get(code) == kind and code in h.code
    ]
    by_channel = [
        np.array([v / h.mayor[w] for w, v in h.channel(kind).items() if h.mayor.get(w)])
        for h in history
    ]
    # 0.25: a code no night has seen in that channel (2026 adds none), about the observed CVs.
    return _cv(by_code) or _cv(by_channel) or 0.25


def _code_shares(history: list[_Votes], codes: list[int]) -> dict[int, float]:
    """Each advance code's historical share of advance votes, renormalised over `codes`."""
    shares = {}
    for code in codes:
        seen = [
            sum(h.code[code].values()) / sum(h.channel("advance").values())
            for h in history
            if CHANNELS[h.year].get(code) == "advance" and code in h.code
        ]
        if not seen:
            return {c: 1 / len(codes) for c in codes}
        shares[code] = float(np.mean(seen))
    total = sum(shares.values())
    return {c: s / total for c, s in shares.items()}


def fit_params(nights: list[Night]) -> dict:
    """Each level's parameters, fitted on `nights`."""
    params = {
        level: vars(fit_level(nights, offices))
        for level, offices in LEVEL_OFFICES.items()
        if any(r.office_id in offices for n in nights for r in n.races)
    }
    params["mayor"] = vars(fit_mayor(nights))
    return params


def fold_projection(target: Night, nights: dict[int, Night], prereg: dict) -> dict:
    """The target night's projection inputs, from the other nights and its pre-night facts."""
    others = [n for y, n in sorted(nights.items()) if y != target.year]
    races = race_inputs(target, others, ward_electors(target.year), _released(target.year, prereg))
    return {"params": fit_params(others), "races": races}


def race_inputs(
    target: Night, others: list[Night], electors: dict[int, int], released: Released
) -> dict:
    """Each projected race's expected-total inputs for `target`, whose structure alone is read,
    from the history nights `others`, its pre-night electors by City ward and its released
    advance figure, by race id."""
    history = [_Votes(n) for n in others]
    comparable = [h for h in history if len(h.wards) == len(target.wards)]
    # Ward-level history needs the same 25-ward map (2018 on); 2014's 44 wards have none.
    ward_level = len(target.wards) == 25 and bool(comparable)
    city_electors = sum(electors[w] for w, _ in target.wards)

    def turnout_ratio(ward: int) -> float:
        if not ward_level:
            return 1.0
        return _mean([(h.mayor[ward] / h.electors[ward]) / h.turnout() for h in comparable], 1.0)

    def office_ratio(office: int, ward: int) -> float:
        if ward_level:
            seen = [
                h.office[office][ward] / h.mayor[ward] for h in comparable if office in h.office
            ]
            if seen:
                return float(np.mean(seen))
        return _mean(
            [
                sum(h.office[office].values()) / sum(h.mayor.values())
                for h in history
                if office in h.office
            ],
            1.0,
        )

    path, citywide, table = released
    advance_share = {}
    for ward, _ in target.wards:
        if ward_level:
            advance_share[ward] = _mean(
                [
                    h.channel("advance")[ward] / sum(h.channel("advance").values())
                    for h in comparable
                ],
                electors[ward] / city_electors,
            )
        else:
            advance_share[ward] = electors[ward] / city_electors

    def advance_voters(ward: int) -> float | None:
        if path == "ward_table":
            return table[ward]
        if path == "citywide":
            return citywide * advance_share[ward]
        return None  # no figure released: each code is a historical share of the ward's total

    channels = CHANNELS[target.year]
    advance_codes = sorted(c for c, kind in channels.items() if kind == "advance")
    code_share = _code_shares(history, advance_codes)

    def channel_share(kind: str, ward: int) -> float:
        """The channel's historical share of the ward's mayoral votes."""
        seen = [h for h in history if h.channel(kind)]
        seen_comparable = [h for h in seen if len(h.wards) == len(target.wards)]
        if ward_level and seen_comparable:
            return float(np.mean([h.channel(kind)[ward] / h.mayor[ward] for h in seen_comparable]))
        return _mean([sum(h.channel(kind).values()) / sum(h.mayor.values()) for h in seen], 0.0)

    aggregate = {u.key: u.ward_aggregate for u in target.units}
    races = {}
    for race in target.races:
        if race.office_id != MAYOR and not any(race.office_id in o for o in LEVEL_OFFICES.values()):
            continue
        wards = []
        for ward in sorted({w for w, _ in race.units}):
            codes = [c for w, c in race.units if w == ward and aggregate[(w, c)]]
            ratio = office_ratio(race.office_id, ward)
            aggregates = []
            for code in codes:
                kind = channels[code]
                voters = advance_voters(ward) if kind == "advance" else None
                share = None
                if voters is None:
                    share = channel_share(kind, ward) * (
                        code_share[code] if kind == "advance" else 1.0
                    )
                aggregates.append(
                    {
                        "code": code,
                        "votes": None if voters is None else voters * ratio * code_share[code],
                        "share": share,
                        "spread": _spread(history, code, kind),
                    }
                )
            wards.append(
                {
                    "ward": str(ward),
                    "base": electors[ward] * turnout_ratio(ward) * ratio,
                    "election_day_units": sum(1 for w, c in race.units if w == ward) - len(codes),
                    "aggregates": aggregates,
                }
            )
        races[race_id(race.office_id, race.num)] = {"wards": wards}
    return races


def structure_2026(races: list[dict]) -> Night:
    """The 2026 night's structure from its Night Bundle races, with no votes: each City ward's
    `polls` as its election-day units plus one Ward Aggregate per 2026 code, each council race
    its ward's units and each trustee area its City wards' units (research 03 § 4)."""
    mayor = next(r for r in races if r["office_id"] == MAYOR)
    if any(w["polls"] <= len(AGGREGATE_CODES_2026) for w in mayor["wards"]):
        raise ValueError("a City ward's polls don't cover its Ward Aggregates")
    units = [
        Unit(int(w["num"]), code, code in AGGREGATE_CODES_2026)
        for w in mayor["wards"]
        for code in (
            *range(1, w["polls"] - len(AGGREGATE_CODES_2026) + 1),
            *AGGREGATE_CODES_2026,
        )
    ]
    by_ward: dict[int, list[tuple[int, int]]] = {}
    for unit in units:
        by_ward.setdefault(unit.ward, []).append(unit.key)

    def race(spec: dict, wards: list[int]) -> Race:
        keys = tuple(key for ward in wards for key in by_ward[ward])
        n = len(spec["candidates"])
        return Race(
            spec["office_id"],
            spec["num"],
            spec["name"],
            tuple(c["key"] for c in spec["candidates"]),
            keys,
            np.zeros((len(keys), n)),
            np.zeros(n),
        )

    offices = {o for level in LEVEL_OFFICES.values() for o in level}
    return Night(
        year=2026,
        opening_time="",
        election_desc="",
        units=tuple(units),
        wards=tuple((int(w["num"]), w["name"]) for w in mayor["wards"]),
        races=(
            race(mayor, sorted(by_ward)),
            *(
                race(
                    r,
                    [int(r["num"])]
                    if r["office_id"] in LEVEL_OFFICES["council"]
                    else [int(w) for w in r["city_wards"]],
                )
                for r in races
                if r["office_id"] in offices
            ),
        ),
    )


def replay_bundle(target: Night, nights: dict[int, Night], prereg: dict) -> dict:
    """The replayed night's Night Bundle with its fold's projection inputs."""
    from election_night.replay.snapshots import night_bundle

    bundle = night_bundle(target)
    fold = fold_projection(target, nights, prereg)
    bundle["projection"] = {"params": fold["params"]}
    for spec in bundle["races"]:
        if spec["id"] in fold["races"]:
            spec["expected"] = fold["races"][spec["id"]]
    return bundle
