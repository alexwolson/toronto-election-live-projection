# Toronto election night: live results and projection

Planning workspace for the public election-night page for the 2026 Toronto municipal election
(October 26, 2026, results from 8 p.m.): live tallies for every race in the City's media feed,
plus an Election-Night Projection for mayor, council and school-board trustee, each level shipped
only if it passes pre-registered historical replays. Race calls are out of scope.

- Start with the [wayfinder map](https://github.com/alexwolson/toronto-election-live-projection/issues/1).
- Planning tickets are GitHub issues in this repo; see the [tracker conventions](docs/agents/issue-tracker.md).
- Research findings: [docs/research/](docs/research/).
- Vocabulary: [CONTEXT.md](CONTEXT.md).

## Development

The election-night code is the `election_night` Python package in `src/`, managed with
[uv](https://docs.astral.sh/uv/) (Python 3.14).

```bash
uv sync                        # install the package and dev tools
uv run pytest                  # run the tests
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
```

The `election-night` command:

```bash
uv run election-night payload --pretty   # fetch the City's two files once (conditional GET), print the payload
uv run election-night name-inputs --backend-release backend-YYYY-MM-DD.N
                                         # vendor the registry and the forecast's ids and candidacies
uv run election-night bundle             # rebuild data/night-bundle/night-bundle.json from the City test files
uv run election-night goldens            # rewrite the golden payloads in goldens/payload/
```

The payload's field layout is in [docs/payload.md](docs/payload.md).

The bundle names every 2026 candidate from inputs vendored in `data/night-bundle/inputs/`
([README](data/night-bundle/inputs/README.md)), and fails unless the City test file, the registry
and the canonical name the same candidates in every race.

```bash
FEED_BASE_URL=... REDIS_URL=... uv run election-night pipeline --name fly --stagger 0
```

runs a pipeline: every 60 s it reads the City's two files and publishes the payload and its
heartbeat to the store. The store's keys and the newest-pair rule are in [docs/store.md](docs/store.md).

Tests that need Redis use the server at `REDIS_URL` and are skipped when it is unset. To run them
locally:

```bash
brew install redis
redis-server --port 6379 &
REDIS_URL=redis://localhost:6379/0 uv run pytest
```

CI (`.github/workflows/ci.yml`) runs the lint, format and test checks on pushes to `main` and on
pull requests, with a Redis service container. In CI a missing `REDIS_URL` fails the Redis tests
instead of skipping them.

## Replays

`election_night.replay` re-runs the past nights (2014 on its 44 wards, 2018, 2022 and the 2023
by-election for mayor) as the City's two files would have published them (#28):

- `historical.load_night(year, prereg)` reads the vendored workbooks in `data/historical/results/`
  into per-unit vote vectors, checked against every block's totals. A Reporting Unit is a
  (City ward, code) pair; the pre-registered codes (97–99) are Ward Aggregates, and 96 is an
  election-day unit.
- `orders.arrival_order(night, prereg, kind, index)` and `orders.orders(night, prereg)` give the
  seeded arrival orders, with every count, seed and code read from `gates/preregistration.json`.
- `snapshots.snapshots(night, order, steps=...)` yields the Count Snapshot pair after each step
  (one Reporting Unit per step, separate `seq`s); the last step holds the certified totals.
  `snapshots.night_bundle(night)` is the night's historical Night Bundle. Ballot Names are the
  workbook's (`Chow Olivia`), and `totalVoters` is `"0"` until electors are loaded.
- `captures.real_captures(prereg, root, nights)` gives the pre-registered real captures as named
  checkpoints, in the same names.

The scorer (#29) runs those snapshots through the payload function and scores the draws it used:

- `replay.run` checks each race at the first Count Snapshot at or after every pre-registered point
  of its own Reporting Progress (5% to 95%), plus the real captures, and scores the level's
  variant against the Tally Baseline. Acclaimed races are not scored; a race whose projection has
  retired is scored as its count.
- `replay.scoring` holds the scores (signed-margin CRPS, multiclass Brier, G1, G2 and the
  diagnostic share CRPS) and criteria 1–5, with every threshold read from the pre-registration.
- `replay.gate_result` writes each Gate Result once (`<level>-run-NNN.json`, never overwritten).
  The model version is a sha256 of the model's code (`payload.py`, `feed.py`, `projection/`) and
  its frozen parameters (`gates/params/`); the final forecast is an input outside it.

```bash
uv run election-night replay --level council --smoke   # one night, one order per timing pattern,
                                                       # 600 s hard timeout, to .cache/gates-smoke/
uv run election-night replay --level council --timeout 3600
                                                       # every night and order, to gates/results/
```

Levels are `council`, `trustee`, `mayor-count-only` and `mayor-forecast-weighted`. The smoke run
prints its timing and an extrapolation to the full run.

This is an independent Git repository within the Toronto election workspace.
