"""The Rehearsal pass checklist's archive checks (docs/rehearsal-checklist.md, #42).

- **Exact tallies:** every Live Tally in every archived payload equals what the Mock Feed served
  under its `seq` pair (`MockFeed.reference`, faults included; docs/full-night-faults.md § Exact
  tallies). A race with no tally, or one the feed served unreadable or not at all, has nothing to
  compare.
- **Byte-identical archives:** a `seq` pair found in every archive has one hash. The feed's
  stalled `seq` is the exception: it served several counts under one pair, so each pipeline may
  have archived its own.

Each archive is a local copy of one bucket (Tigris or Spaces) under a Rehearsal's prefix; its
payloads are `payloads/<all-office seq>-<ward-by-ward seq>-<sha256>.json` (archive.payload_key).
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from election_night.mockfeed.feed import MockFeed


@dataclass
class Report:
    tallies: int = 0  # Live Tallies compared
    shared: int = 0  # seq pairs found in every archive
    failures: list[str] = field(default_factory=list)


def _payloads(archive: Path) -> list[Path]:
    return sorted(archive.rglob("payloads/*.json"))


def check_archives(feed: MockFeed, archives: list[Path]) -> Report:
    report = Report()
    references: dict[tuple[int, int], list] = {}
    digests: dict[tuple[int, int], dict[Path, set[str]]] = defaultdict(lambda: defaultdict(set))
    for archive in archives:
        paths = _payloads(archive)
        if not paths:
            report.failures.append(f"{archive}: no payloads")
        for path in paths:
            a_seq, w_seq, digest = path.stem.split("-")
            pair = int(a_seq), int(w_seq)
            digests[pair][archive].add(digest)
            if pair not in references:
                references[pair] = feed.reference(*pair)
            served = references[pair]
            if not served:
                report.failures.append(f"{path}: the Mock Feed never served this seq pair")
                continue
            for race in json.loads(path.read_bytes())["races"]:
                tally = {c["key"]: c["votes"] for c in race["candidates"]}
                if not tally or any(v is None for v in tally.values()):
                    continue
                expected = [s.get(race["id"]) for s in served]
                if all(e is None for e in expected):
                    continue
                report.tallies += 1
                if tally not in expected:
                    report.failures.append(f"{path}: {race['id']} differs from the feed's count")
    for pair, by_archive in sorted(digests.items()):
        if len(by_archive) < len(archives):
            continue
        report.shared += 1
        if len(set().union(*by_archive.values())) > 1 and len(references[pair]) <= 1:
            report.failures.append(f"seq pair {pair[0]}-{pair[1]}: archives differ")
    return report
