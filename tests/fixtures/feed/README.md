# City feed fixtures

Real copies of the City's two election-night results files, for the payload tests. Every file's
source URL and sha256 is in [SOURCES.csv](SOURCES.csv).

- `city-2026/`: the City's zeroed 2026 test files, fetched once on 2026-10-08 02:02 UTC with their
  response headers. Their ETags match the ones research 01 recorded on 2026-10-05, so they are the
  files regenerated after the Sept 28 test.
- `wayback/`: the Wayback Machine captures listed in
  [research 02](../../../docs/research/02-past-election-night-reporting.md) and its
  `02-feed-snapshots.csv`, named `<year>-<capture timestamp>-<file>.json`. The Wayback Machine
  stored the `electionresults.toronto.ca` copies gzip-encoded; those were decoded to the JSON body,
  and the sha256s are of the decoded bytes.

No ward-by-ward file survives from 2022. Where a test needs a 2022 pair, it derives a zeroed
ward-by-ward file from the all-office file (`election_night.goldens.zeroed_ward_by_ward`).
