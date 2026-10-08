"""Golden payloads: one per reader state the payload function can reach so far.

Each golden is built from real City files (tests/fixtures/feed). The Frontend copies them into its
fixtures and its validator must accept every one (#17 § Schema skew).
"""

import json
from pathlib import Path

from election_night.bundle import OPENING_2026, build_bundle
from election_night.payload import build_payload

# 2026-10-26 20:01:00 EDT, one minute after the 2026 opening time.
AFTER_OPENING_2026 = 1793059260000


def zeroed_ward_by_ward(all_office: bytes, seq: int | None = None) -> bytes:
    """A zeroed mayor-by-ward file laid out from an all-office file.

    No ward-by-ward file survives from 2022, so its pairs use this one: the mayoral candidates in
    the all-office file's order, and the Councillor rows' ward fields (the City repeats those
    under every candidate), with every count at zero.
    """
    data = json.loads(all_office)
    offices = {office["id"]: office for office in data["office"]}
    citywide = offices[1]["ward"][0]
    wards = [
        {
            "name": ward["name"],
            "num": ward["num"],
            "polls": ward["polls"],
            "pollsReceived": "0",
            "totalVoters": ward["totalVoters"],
            "votesCounted": "0",
            "votesReceived": "0",
        }
        for ward in offices[2]["ward"]
    ]
    zeroed = {
        "electionDesc": data["electionDesc"],
        "office": {
            "name": "Mayor",
            "polls": citywide["polls"],
            "pollsReceived": "0",
            "totalVoters": citywide["totalVoters"],
            "votesReceived": "0",
            "candidate": [
                {"name": c["name"], "votesReceived": "0", "ward": wards}
                for c in citywide["candidate"]
            ],
        },
        "seq": str(seq) if seq is not None else data["seq"],
    }
    return json.dumps(zeroed, ensure_ascii=False, indent=2).encode("utf-8")


def _edited(body: bytes, edit) -> bytes:
    data = json.loads(body)
    edit(data)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _restamped(body: bytes, seq: int) -> bytes:
    return _edited(body, lambda d: d.update(seq=str(seq)))


def _faulted(data: dict) -> None:
    """Councillor ward 14's row made unreadable, and TDSB area 5 dropped from the file."""
    data["office"][1]["ward"][13]["pollsReceived"] = 12
    data["office"][2]["ward"].pop(4)


def goldens(fixtures: Path) -> dict[str, bytes]:
    """Golden payload bytes by name, built from the feed fixtures directory."""
    city = fixtures / "city-2026"
    wayback = fixtures / "wayback"
    ao_2026 = (city / "unofficialresult.json").read_bytes()
    wb_2026 = (city / "unofficialresult-wardbyward.json").read_bytes()
    bundle_2026 = build_bundle(ao_2026, wb_2026, opening_time=OPENING_2026)

    ao_2018 = (wayback / "2018-20181029172648-all-office.json").read_bytes()
    wb_2018 = (wayback / "2018-20181029172755-wardbyward.json").read_bytes()

    ao_2022_zero = (wayback / "2022-20221025001346-all-office.json").read_bytes()
    ao_2022_2146 = (wayback / "2022-20221025014628-all-office.json").read_bytes()
    seq_2022_2146 = json.loads(ao_2022_2146)["seq"]

    ao_2023_zero = (wayback / "2023-20230627000639-all-office.json").read_bytes()
    ao_2023_2056 = (wayback / "2023-20230627005628-all-office.json").read_bytes()
    wb_2023_2026 = (wayback / "2023-20230627002639-wardbyward.json").read_bytes()

    pairs = {
        # The City's 2026 test files as they stand: before results.
        "before-results-2026": (ao_2026, wb_2026, bundle_2026),
        # The same files a minute after opening: no units in, and the acclaimed races.
        "no-units-in-2026": (
            _restamped(ao_2026, AFTER_OPENING_2026),
            _restamped(wb_2026, AFTER_OPENING_2026),
            bundle_2026,
        ),
        # The same, with one unreadable row and one missing race: no figures for those two.
        "no-figures-2026": (
            _edited(_restamped(ao_2026, AFTER_OPENING_2026), _faulted),
            _restamped(wb_2026, AFTER_OPENING_2026),
            bundle_2026,
        ),
        # 2023 by-election: the mayor card at 20:26 (Bailão ahead, 84% of units in).
        "mayor-counting-2023": (
            ao_2023_2056,
            wb_2023_2026,
            build_bundle(ao_2023_zero, wb_2023_2026, opening_time="2023-06-26T20:00:00-04:00"),
        ),
        # 2022 at 21:46: council and trustee counting. MonAvenir 4's `polls: "0"` row shows as
        # published (539 of 0) until the per-race checks (#43) hide its Reporting Progress.
        "council-counting-2022": (
            ao_2022_2146,
            zeroed_ward_by_ward(ao_2022_zero, seq=int(seq_2022_2146)),
            build_bundle(
                ao_2022_zero,
                zeroed_ward_by_ward(ao_2022_zero),
                opening_time="2022-10-24T20:00:00-04:00",
            ),
        ),
        # 2018's final pair: every race with all units in.
        "all-units-in-2018": (
            ao_2018,
            wb_2018,
            build_bundle(ao_2018, wb_2018, opening_time="2018-10-22T20:00:00-04:00"),
        ),
    }
    return {name: build_payload(*pair) for name, pair in pairs.items()}


def write_goldens(fixtures: Path, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in goldens(fixtures).items():
        path = out / f"{name}.json"
        path.write_bytes(body)
        written.append(path)
    return written
