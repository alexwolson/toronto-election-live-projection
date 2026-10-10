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

### Image and deploys (#32)

The `Dockerfile` bakes this repo's code and the Night Bundle into one image, so a single digest pins
everything and a restart fetches nothing from GitHub. Three manual (`workflow_dispatch`) workflows:

- **`image`** builds `linux/amd64`, pushes it to GHCR, copies it by digest to
  `registry.fly.io/toronto-election-night-image` and DOCR `<DOCR_REGISTRY>/pipeline` (the Actions variable, `toronto-election-night`), and
  fails unless all three report the built digest. The job summary prints the tag and digest.
- **`deploy`** takes the environment (`rehearsal` or `night`), that tag and digest, the feed base URL
  and the reader-path URL. It deploys the Fly Machine (`deploy/fly.<env>.toml`, `yyz`) and the App
  Platform worker (`deploy/do.<env>.yaml`, `nyc`), then fails unless each provider runs the input
  digest. The environments differ only in the store, the healthchecks.io ping key, the archive
  prefix and the URLs; the secrets come from the Actions secrets.
- **`teardown`** destroys the Rehearsal apps on both providers. It cannot touch the Night apps.

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

### Freeze gate (#40)

At the Deploy Freeze, the payloads archived from the Dress are checked against the exact
production Frontend build (#17 § Schema skew). First copy the Dress's payloads from both archive
buckets (docs/store.md § The archive), each with its own provider's endpoint and keys. The Dress
shares the `rehearsal/` prefix with earlier Rehearsals and payload keys carry no time, so delete
the local copies last modified before the Dress began, or the gate checks those too:

```bash
aws s3 sync s3://toronto-election-night-archive/rehearsal/payloads/ dress/fly/payloads/ \
  --endpoint-url https://fly.storage.tigris.dev
aws s3 sync s3://toronto-election-night-archive/rehearsal/payloads/ dress/do/payloads/ \
  --endpoint-url https://nyc3.digitaloceanspaces.com
uv run election-night freeze-gate --archive dress/fly --archive dress/do \
  --frontend-commit <production build's full SHA> \
  --backend-release-tag <the tag given to npm run deploy:production>
```

The gate fetches a clean checkout of that Frontend commit, runs its `validateLivePayload` with
Node (22.18 or later, which runs the TypeScript directly) over every payload, and checks that
each payload's `forecast_release_tag` equals the tag. It prints one `FAIL` line per failure and
exits nonzero on any failure, on an unreadable payload, on an archive with no payloads, or if the
commit can't be fetched or its validator can't run.

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

## Mock Feed scenario

`election_night.mockfeed.scenario` builds the invented, 2026-shaped true count the Rehearsals run
against (#34, S6). `load_scenario(seed)` takes the races, Ballot Names, `polls` and `totalVoters`
from the City's zeroed test files and carries votes over by rank: the mayor from 2023 in the final
forecast's rank (Bradford takes Bailão's election-day lead, and Chow wins on the late Ward
Aggregates), council and the English boards from 2022 in ballot order. The French boards have no
workbooks and stay at 0 votes. The units arrive in the pre-registered "late" order with that
seed, and `scenario.true_count(step)` gives each race's tally and the mayor's ward tallies after
`step` units: the reference for the Rehearsals' exact-tallies check. `scenario.count_snapshot(step)`
gives the same count as the City's two files, in the test files' layout (names, `polls` and
`totalVoters` kept, candidates re-sorted, strings throughout); the `mock-feed` command (#37) stamps
the `seq`s and serves them. The 2026 trustee map it
reads is in [data/mock-feed/](data/mock-feed/README.md).

## The `mock-feed` command

`election-night mock-feed --start <ISO time with offset> --speed <n>` serves the scenario as the
City serves its two files, at any path ending in `unofficialresult.json` or
`unofficialresult-wardbyward.json` (#37). Point a pipeline's `FEED_BASE_URL` at
`http://<host>:8080/results`. Every response is a pure function of the scenario, start, speed,
clock and request (`election_night.mockfeed.feed.MockFeed.respond`):

- **The night's clock.** `--start` maps to 19:50 EDT on Oct 26, and the night clock runs `--speed`
  night minutes per wall minute: about 10 for Plumbing, 1 for the Full night, 4 for the Dress.
  Before the start it serves the zeroed test files as they are.
- **Generations.** Each file is regenerated once a night minute, with its own `seq` (the
  ward-by-ward file 20 ms before the all-office one), ETag, Last-Modified and 304s, until the
  count completes at 23:37 and its last `seq` stays frozen. Units arrive on 2023's observed curve
  from 20:00: 84% by 20:26, 97% by 21:24, the rest by 23:37.
- **The Sept 28 repeat.** From 19:50 the files carry live-looking counts, then are regenerated as
  zeros at 20:00 when the count starts. The pipeline's payload stays "before results" throughout.
- **REHEARSAL.** Every file's `electionDesc` ends in "REHEARSAL", which raises the page's bar.
- **HTTP faults** on the night clock (`--faults off` or `MOCK_FEED_FAULTS=off` turns them off;
  `full-night` serves the Full night's script instead, listed in `docs/full-night-faults.md`):
  20:20-20:50 a long 304 run, 21:00-21:20 503s, 21:30-21:50 a 403 "throttle", 22:00-22:20 responses
  held 25 s (past the pipeline's 20 s timeout), 22:30-22:50 a truncated all-office body,
  23:00-23:20 the ward-by-ward `candidate` key renamed, 23:30-23:50 the ward-by-ward file failing
  (503) while the all-office file is fine.

`MockFeed.step_at(now)` gives the scenario step the files hold, so `scenario.true_count(step)` is
the exact-tallies reference. The Mock Feed runs as its own Fly app in `ord`, outside `yyz`,
deployed by digest with the `mock-feed` workflow (`deploy/fly.mockfeed.toml`).

This is an independent Git repository within the Toronto election workspace.
