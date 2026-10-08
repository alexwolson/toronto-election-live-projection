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
uv run election-night bundle             # rebuild data/night-bundle/night-bundle.json from the City test files
uv run election-night goldens            # rewrite the golden payloads in goldens/payload/
```

The payload's field layout is in [docs/payload.md](docs/payload.md).

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

This is an independent Git repository within the Toronto election workspace.
