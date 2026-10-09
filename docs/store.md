# The store

One Redis database per environment (Rehearsal and Night, both Upstash `us-east-1`), so keys carry
no prefix. The pipelines write it; the Frontend route `/live/results.json` reads it with one `MGET`.

| Key | Value | Written by |
|---|---|---|
| `payload` | The payload bytes ([payload.md](payload.md)). | The newest-pair script |
| `payload:seq` | The stored payload's seq pair, `"<all_office seq>,<ward_by_ward seq>"`. | The newest-pair script |
| `heartbeat:fly`, `heartbeat:do` | Epoch milliseconds of that pipeline's last valid, current read of both files: a 200 that passes the snapshot checks, or a 304. | Each pipeline, every tick with a readable pair |
| `count_decreases` | A list, one JSON entry per count decrease: `{"pipeline", "seq", "ms", "scope", "race", "ward"?, "before", "after"}`. `scope` is `citywide` (the mayor race), `ward` (a councillor race or a mayoral ward) or `area` (a trustee race). Read by `night status` (#50). | Each pipeline, on a decrease |

**The newest-pair script** (`NEWEST_PAIR_LUA` in `src/election_night/store.py`) stores a payload
only if its seq pair is newer than `payload:seq`: neither `seq` is older and at least one is newer
(#17, S7). Equal and mixed pairs are rejected. There is no leader or lease.

A heartbeat follows the read, not the store's verdict: a pipeline whose readable pair the store
rejects (because the other pipeline already stored it, or a newer one) still refreshes its
heartbeat. An unreadable file rejects the whole pair, so neither the payload nor the heartbeat is
written.

## Running a pipeline

```bash
FEED_BASE_URL=https://mediaresults.toronto.ca/results \
REDIS_URL=redis://localhost:6379/0 \
ARCHIVE_BUCKET=night-archive-fly \
AWS_ENDPOINT_URL_S3=https://fly.storage.tigris.dev AWS_REGION=auto \
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
PING_URL_PIPELINE=https://hc-ping.com/<pipeline-fly uuid> \
PING_URL_READER_PATH=https://hc-ping.com/<reader-path uuid> \
PING_URL_COUNT_DECREASE=https://hc-ping.com/<count-decrease uuid> \
READER_PATH_URL=https://<site>/live/results.json \
uv run election-night pipeline --name fly --stagger 0
```

Every URL, bucket and credential comes from the environment, and the command exits if one is
missing. For Upstash, `REDIS_URL` is the database's TCP URL, `rediss://default:<token>@<host>:6379`.
The archive's endpoint and keys are boto3's standard variables; Spaces' endpoint is
`https://nyc3.digitaloceanspaces.com`. The two pipelines are `fly` and
`do`, staggered 30 s apart (`--stagger 0` and `--stagger 30`). Each ticks on the minute plus its
stagger, never faster than every 60 s, and skips a slot rather than ticking late after an overrun.
It logs one JSON line per tick to stderr. The process exits if no tick completes in 3 minutes, and
its platform restarts it.

## The archive

Each pipeline writes to its own provider's S3-compatible bucket (Fly to Tigris, DigitalOcean to
Spaces `nyc3`), in `src/election_night/archive.py`. Keys are `seq` plus the first 16 hex digits of
the content's SHA-256, written once (a HEAD before each PUT: Spaces doesn't document
`If-None-Match: *`), so the two buckets merge by key after the night.

| Key | Object |
|---|---|
| `files/<file>/<seq>-<hash>.json` | Every 200 body as raw bytes, readable or not (`unreadable-<hash>` without a `seq`). Metadata: `status`, `etag`, `last-modified`, `received-ms`. A 304 is the same generation and isn't rewritten. |
| `payloads/<all_office seq>-<ward_by_ward seq>-<hash>.json` | Every payload the pipeline builds, stored or not. |
| `logs/<pipeline>/<ms>-<hash>.json` | One log line per tick: the tick's record, with the probe result and the archive's `failed` and `dropped` counts. |

Only 200 bodies are archived; a non-200 response appears as its status in the log line. Writes
never block or delay publishing: they go to one background thread behind a queue of 200, which
also computes the keys.
A full queue drops the write, a failed write is not retried, and both are counted in the next log
line. Writes still queued when the process exits are lost.

## Calm alerts

healthchecks.io checks, delivered through Pushover (#17 § On the night):

- **`pipeline-fly`, `pipeline-do`.** After every completed tick, including a rejected pair or a
  failed store write, the pipeline pings its own check. It shows the process is alive and ticking;
  whether readers get fresh results is `reader-path`'s job.
- **`reader-path`.** Every tick, the pipeline GETs the public `/live/results.json` and pings only on
  a 200 whose `heartbeat` is under 5 minutes old.
- **`count-decrease`.** The pipeline compares each payload it builds with its own previous one
  (since the process started). A drop in the mayor race's summed candidate votes pings
  `<url>/fail`, the explicit fail signal. Ward- and area-level decreases send nothing. Every
  decrease is appended to `count_decreases`. The check gets no success pings, so it stays down
  after one signal and Pushover sends the sound once; a later decrease that night is silent, and
  the check must be resumed by hand before the next Rehearsal reuses it. A restart starts with no
  previous payload, so a decrease across a restart is missed.

The probe, the pings and the log line run on a thread after each tick, so a slow route or
healthchecks.io never pushes a tick past its slot.

## Night status

`uv run election-night status` prints a Markdown summary of the store at `REDIS_URL`: both
heartbeats (stale over 5 minutes), the stored `seq` pair and the City count time, current
Withdrawals with their machine reasons, and every entry in `count_decreases`, newest first
(`src/election_night/status.py`). It reads with one `MGET` and one `LRANGE`, and never writes.
Switch states join it with the switches (#49).

On the night it runs as the `night status` workflow (`.github/workflows/night-status.yml`), from
the GitHub mobile app: Actions → night status → Run workflow, choosing `night` or `rehearsal`. It
reads `NIGHT_REDIS_URL` or `REHEARSAL_REDIS_URL` from the Actions secrets and writes to the job
summary.
