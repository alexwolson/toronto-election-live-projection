# The store

One Redis database per environment (Rehearsal and Night, both Upstash `us-east-1`), so keys carry
no prefix. The pipelines write it; the Frontend route `/live/results.json` reads the payload, both heartbeats,
the switches and Night Close with one `MGET`.

| Key | Value | Written by |
|---|---|---|
| `payload` | The payload bytes ([payload.md](payload.md)). | The newest-pair script |
| `payload:seq` | The stored payload's seq pair, `"<all_office seq>,<ward_by_ward seq>"`. | The newest-pair script |
| `heartbeat:fly`, `heartbeat:do` | Epoch milliseconds of that pipeline's last valid, current read of both files: a 200 that passes the snapshot checks, or a 304. | Each pipeline, every tick with a readable pair |
| `switch:<name>` | `on` or `off`, one key per switch (below). Missing is on. | The `switch` workflow, or the Upstash console |
| `night_close` | `closed` once Night Close is declared (below). Missing is open. | The `night close` workflow, or the Upstash console |
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
ARCHIVE_BUCKET=toronto-election-night-archive ARCHIVE_PREFIX=rehearsal/ \
AWS_ENDPOINT_URL_S3=https://fly.storage.tigris.dev AWS_REGION=auto \
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
PING_URL_PIPELINE=https://hc-ping.com/<ping key>/pipeline-fly \
PING_URL_READER_PATH=https://hc-ping.com/<ping key>/reader-path \
PING_URL_COUNT_DECREASE=https://hc-ping.com/<ping key>/count-decrease \
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

Rehearsal and Night share each provider's bucket, `toronto-election-night-archive`, so every key
below starts with `ARCHIVE_PREFIX` (`rehearsal/` or `night/`, set in `deploy/`).

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

## Switches

Store flags the Frontend route applies before it serves (#49; #17 § Switches). The pipelines
never read them. There is no per-race switch, and every switch turns back on.

| Key | `off` means |
|---|---|
| `switch:mayor` | No mayoral projection: the mayor card shows the count, "Projection paused for the mayor's race". |
| `switch:council` | No council projections: "Projection paused for council races"; tiles read "Count only". |
| `switch:trustee` | No TDSB or TCDSB projections: "Projection paused for school board trustee races". The French-language boards are never projected. |
| `switch:mayor_variant` | The forecast-weighted variant alone is dropped: the mayor shows the count-only band if the payload carries one, else no Estimated Range and the paused wording. |
| `switch:projections` | Every projection, as all three level switches together. |
| `switch:page` | The page pause: live results are replaced with "Live results are paused. See the City of Toronto's results: [link]". |

**The variant switch's known gap.** A gated payload carries only the band shown, so while the
forecast-weighted band shows, the count-only band isn't there to fall back to, even if
count-only passed its gate. With today's Gate Results (mayor count-only failed, run 3) it makes
no difference. Publishing a live count-only band beside the variant would change `payload.py`,
and with it the model version, so it waits for the next Gate Result run that changes it anyway.

The value is `on` or `off`, lower case. A missing key is on. **Any other value is off**, so a
typo fails closed; `night status` shows it as `off (unrecognized value ...)`. A level whose gate
already keeps it off (`gate_failed`, `version_mismatch`, `gate_missing`) keeps its own status and
wording when switched off. Switched-off levels are served with the route-only status
`switched_off` ([payload.md](payload.md)). The page pause still needs a payload that passes the
schema: the route throws on a bad one, and ISR keeps the last good copy, pause or not.

A flip reaches readers in about 75 s: ISR's 15 s, then the browser's 60 s poll, which accepts an
equal `seq` pair.

**From the phone.** Actions → switch → Run workflow: the store (`night` or `rehearsal`), the
switch, and `off` or `on`. It sets the key, reads it back (the run fails if the read-back
differs), and writes the read-back and the full night status to the job summary. The run history
is the log of every flip. Locally: `REDIS_URL=... uv run election-night switch <name> <on|off>`.

**Fallback: the Upstash console.** Open the database (Night or Rehearsal), then the CLI tab, and
type, for example:

```
SET switch:council off
SET switch:council on
GET switch:council
```

The key names and values are exactly those in the table above.

## Night Close

The declared end of the night (#51; #17 § Night Close), never inferred from a quiet feed. Declare
it by hand once neither file has changed for 2 hours; `night status` shows the `seq` pair's age.
The pipelines never read the flag; the Frontend route passes it. Once it is declared:

- each race with every voting area in labels its leader "Elected (unofficial)" (never on a tie
  at the top, and never in a race still counting);
- the page says "Final unofficial count as of …", the older `seq`'s time;
- "Refreshes every minute" and the staleness banner drop, since the apps are shut down;
- the mayor card's final pre-election forecast stays hidden.

The value is exactly `closed`. A missing key is open, and **any other value is open**: the
opposite of the switches, so a typo never puts up "Elected (unofficial)". `night status` shows
it as `Open (unrecognized value ...)`. Clearing deletes the key. Like a switch, it reaches readers
in about 75 s.

**From the phone.** Actions → night close → Run workflow: the store (`night` or `rehearsal`) and
`close` or `clear`. It sets or deletes the key, reads it back (the run fails if the read-back
differs), and writes the read-back and the full night status to the job summary. On `close`, and
only after the read-back, a second job runs `deploy/shutdown.sh <store>`, which destroys that
environment's Fly and DigitalOcean apps and checks both are gone. The app names are built from
the store's name alone, so a run never touches the other environment's apps, nor the Mock Feed.
The archive is already in the buckets; the platforms' own logs go with the apps. `clear` restarts
nothing: the `deploy` workflow recreates the apps. Locally:
`REDIS_URL=... uv run election-night night-close <close|clear>`.

**Fallback: the Upstash console.** In the database's CLI tab:

```
SET night_close closed
DEL night_close
GET night_close
```

The console sets only the flag; shut the apps down with the `teardown` workflow (Rehearsal) or
`deploy/shutdown.sh night` with Fly and DigitalOcean credentials.

## Night status

`uv run election-night status` prints a Markdown summary of the store at `REDIS_URL`: both
heartbeats (stale over 5 minutes), the stored `seq` pair and the City count time, each
switch as the route reads it, current Withdrawals with their machine reasons, and every entry in
`count_decreases`, newest first (`src/election_night/status.py`). It reads with one `MGET` and
one `LRANGE`, and never writes.

On the night it runs as the `night status` workflow (`.github/workflows/night-status.yml`), from
the GitHub mobile app: Actions → night status → Run workflow, choosing `night` or `rehearsal`. It
reads `NIGHT_REDIS_URL` or `REHEARSAL_REDIS_URL` from the Actions secrets and writes to the job
summary.
