"""Historical loaders: the certified poll-by-poll workbooks as per-unit vote vectors.

Every workbook sheet holds blocks laid out alike (research 03 § 1): a `Subdivision` header row of
unit codes ending in `Total`, one row per candidate, and a `(City) Ward N Totals` row naming the
City ward the block's units belong to. A Reporting Unit is one (City ward, code) pair. Codes listed
as Ward Aggregates in the pre-registration file (97, 98, 99) are Ward Aggregates; every other code,
96 included, is an election-day unit.

The loader checks each block against its own totals row and each candidate's `Total` cell, and that
every office covers the night's units exactly once. A workbook that fails raises `WorkbookError`.
"""

import re
import warnings
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
import openpyxl
import xlrd

from election_night.feed import COUNCILLOR_OFFICE_ID, MAYOR_OFFICE_ID
from election_night.gates import ROOT

RESULTS = ROOT / "data" / "historical" / "results"

YEARS = (2014, 2018, 2022, 2023)

# Polls close at 20:00; every night was in Eastern Daylight Time.
ELECTION_DAYS = {2014: "2014-10-27", 2018: "2018-10-22", 2022: "2022-10-24", 2023: "2023-06-26"}
ELECTION_DESC = {
    2014: "2014 Municipal Election",
    2018: "2018 Municipal Election (25 Wards)",
    2022: "2022 Municipal Election",
    2023: "2023 By-Election for Mayor",
}

# Feed office id -> workbook file per year format.
_FILES_2014 = {
    1: "MAYOR.xls",
    2: "COUNCILLOR.xls",
    3: "TORONTO DISTRICT SCHOOL BOARD.xls",
    4: "TORONTO CATHOLIC DISTRICT SCHOOL BOARD.xls",
}
_OFFICES = {
    1: "Mayor",
    2: "Councillor",
    3: "Toronto_District_School_Board",
    4: "Toronto_Catholic_District_School_Board",
}


def _files(year: int) -> dict[int, Path]:
    folder = RESULTS / str(year)
    if year == 2014:
        return {o: folder / name for o, name in _FILES_2014.items()}
    if year == 2023:
        return {1: folder / "2023_office_of_the_mayor.xlsx"}
    return {o: folder / f"{year}_Toronto_Poll_By_Poll_{name}.xlsx" for o, name in _OFFICES.items()}


class WorkbookError(ValueError):
    """A workbook that doesn't read as research 03 found it."""


@dataclass(frozen=True)
class Unit:
    ward: int
    code: int
    ward_aggregate: bool

    @property
    def key(self) -> tuple[int, int]:
        return (self.ward, self.code)


@dataclass(frozen=True, eq=False)
class Race:
    """One race's certified count by Reporting Unit."""

    office_id: int
    num: str
    name: str | None
    candidates: tuple[str, ...]  # Ballot Names as the workbook writes them, in ballot order
    units: tuple[tuple[int, int], ...]  # (City ward, code)
    votes: np.ndarray  # (unit, candidate) votes
    certified: np.ndarray  # each candidate's `Total` cell, summed over the race's blocks


@dataclass(frozen=True, eq=False)
class Night:
    year: int
    opening_time: str
    election_desc: str
    units: tuple[Unit, ...]  # every Reporting Unit, by City ward then code
    wards: tuple[tuple[int, str | None], ...]  # City ward number and name
    races: tuple[Race, ...]  # mayor, then councillor, TDSB and TCDSB by number

    @property
    def mayor(self) -> Race:
        return self.races[0]


@dataclass
class _Block:
    ward: int
    codes: list[int]
    candidates: dict[str, tuple[list[int], int]]  # name -> (votes by code, Total cell)


def _int(value, where: str) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == int(value):
        return int(value)
    raise WorkbookError(f"{where}: not a count: {value!r}")


def _blank(value) -> bool:
    return value is None or value == ""


def _sheets(path: Path) -> list[tuple[str, list[list]]]:
    if path.suffix == ".xls":
        book = xlrd.open_workbook(path)
        return [(s.name, [s.row_values(r) for r in range(s.nrows)]) for s in book.sheets()]
    with warnings.catch_warnings():  # the 2023 file's page headers, which nothing reads
        warnings.filterwarnings("ignore", "Cannot parse header or footer", UserWarning)
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            return [(s.title, [list(r) for r in s.iter_rows(values_only=True)]) for s in book]
        finally:
            book.close()


def _blocks(rows: list[list], where: str) -> list[_Block]:
    blocks = []
    header = None  # (code columns, total column)
    candidates: dict = {}
    for i, row in enumerate(rows):
        first = row[0] if row else None
        if first == "Subdivision":
            cols, total = [], None
            for c, cell in enumerate(row[1:], start=1):
                if cell == "Total":
                    total = c
                    break
                if not _blank(cell):
                    cols.append((c, _int(cell, f"{where} header")))
            if total is None:
                raise WorkbookError(f"{where}: header without a Total column")
            header, candidates = (cols, total), {}
            continue
        if header is None or not isinstance(first, str) or not first.strip():
            continue
        cols, total = header
        name = first.strip()
        cells = [row[c] if c < len(row) else None for c, _ in cols]
        if "total" in name.casefold():
            match = re.search(r"Ward (\d+) Totals", name)
            if not match:
                raise WorkbookError(f"{where} row {i}: unreadable totals row {name!r}")
            sums = [sum(v[k] for v, _ in candidates.values()) for k in range(len(cols))]
            if sums != [_int(v, f"{where} totals") for v in cells]:
                raise WorkbookError(f"{where}: block for ward {match[1]} doesn't sum to its totals")
            blocks.append(_Block(int(match[1]), [code for _, code in cols], candidates))
            header = None
            continue
        if all(_blank(v) for v in cells):
            continue  # the office label row ("Mayor", "Councillor")
        votes = [_int(v, f"{where} {name}") for v in cells]
        certified = _int(row[total], f"{where} {name} Total")
        if sum(votes) != certified:
            raise WorkbookError(f"{where}: {name}'s units don't sum to its Total")
        if name in candidates:
            raise WorkbookError(f"{where}: {name} repeated in a block")
        candidates[name] = (votes, certified)
    if header is not None:
        raise WorkbookError(f"{where}: block without a totals row")
    return blocks


def _race(office_id: int, num: str, name: str | None, blocks: list[_Block], where: str) -> Race:
    candidates = list(blocks[0].candidates)
    units, rows = [], []
    certified = np.zeros(len(candidates), dtype=np.int64)
    for block in blocks:
        if set(block.candidates) != set(candidates):
            raise WorkbookError(f"{where}: candidates differ between blocks")
        matrix = np.array([block.candidates[c][0] for c in candidates], dtype=np.int64).T
        units += [(block.ward, code) for code in block.codes]
        rows.append(matrix)
        certified += np.array([block.candidates[c][1] for c in candidates], dtype=np.int64)
    if len(set(units)) != len(units):
        raise WorkbookError(f"{where}: a unit appears twice")
    return Race(
        office_id=office_id,
        num=num,
        name=name,
        candidates=tuple(candidates),
        units=tuple(units),
        votes=np.vstack(rows),
        certified=certified,
    )


def _sheet_num(title: str) -> str | None:
    match = re.fullmatch(r"Ward\s*(\d+)", title.strip())
    return str(int(match[1])) if match else None


def _ward_name(rows: list[list]) -> str | None:
    """The City ward's name from a sheet's title row (2018 on); 2014's titles have none."""
    title = rows[0][0] if rows and rows[0] else None
    match = re.fullmatch(r"City Ward \d+ (.+)", title.strip()) if isinstance(title, str) else None
    return match[1].strip() if match else None


def _office_races(office_id: int, path: Path) -> tuple[list[Race], dict[int, str | None]]:
    races, names = [], {}
    sheets = [(n, rows) for n, rows in _sheets(path) if _sheet_num(n) is not None]
    if office_id == MAYOR_OFFICE_ID:
        blocks = []
        for title, rows in sheets:
            where = f"{path.name} {title}"
            sheet_blocks = _blocks(rows, where)
            blocks += sheet_blocks
            names[sheet_blocks[0].ward] = _ward_name(rows)
        return [_race(MAYOR_OFFICE_ID, "0", "City-wide", blocks, path.name)], names
    for title, rows in sorted(sheets, key=lambda s: int(_sheet_num(s[0]))):
        num, where = _sheet_num(title), f"{path.name} {title}"
        name = _ward_name(rows) if office_id == COUNCILLOR_OFFICE_ID else None
        races.append(_race(office_id, num, name, _blocks(rows, where), where))
    return races, names


@cache
def _load(year: int, aggregate_codes: tuple[int, ...]) -> Night:
    races: list[Race] = []
    wards: dict[int, str | None] = {}
    for office_id, path in sorted(_files(year).items()):
        office_races, names = _office_races(office_id, path)
        races += office_races
        wards.update(names)
    mayor = races[0]
    keys = sorted(mayor.units)
    for office_id in {r.office_id for r in races}:
        covered = sorted(u for r in races if r.office_id == office_id for u in r.units)
        if covered != keys:
            raise WorkbookError(f"{year} office {office_id} doesn't cover the night's units once")
    return Night(
        year=year,
        opening_time=f"{ELECTION_DAYS[year]}T20:00:00-04:00",
        election_desc=ELECTION_DESC[year],
        units=tuple(Unit(w, c, c in aggregate_codes) for w, c in keys),
        wards=tuple(sorted(wards.items())),
        races=tuple(races),
    )


def load_night(year: int, prereg: dict) -> Night:
    """The night's races from the vendored workbooks, with Ward Aggregates as pre-registered."""
    codes = prereg["arrival_orders"]["ward_aggregates"]["codes"]
    return _load(year, tuple(sorted(codes)))
