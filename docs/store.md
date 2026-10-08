# The store

One Redis database per environment (Rehearsal and Night, both Upstash `us-east-1`), so keys carry
no prefix. The pipelines write it; the Frontend route `/live/results.json` reads it with one `MGET`.

| Key | Value | Written by |
|---|---|---|
| `payload` | The payload bytes ([payload.md](payload.md)). | The newest-pair script |
| `payload:seq` | The stored payload's seq pair, `"<all_office seq>,<ward_by_ward seq>"`. | The newest-pair script |
| `heartbeat:fly`, `heartbeat:do` | Epoch milliseconds of that pipeline's last valid, current read of both files: a 200 that passes the snapshot checks, or a 304. | Each pipeline, every tick with a readable pair |

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
uv run election-night pipeline --name fly --stagger 0
```

Only the feed base URL and the store credentials come from the environment. For Upstash, `REDIS_URL`
is the database's TCP URL, `rediss://default:<token>@<host>:6379`. The two pipelines are `fly` and
`do`, staggered 30 s apart (`--stagger 0` and `--stagger 30`). Each ticks on the minute plus its
stagger, never faster than every 60 s, and skips a slot rather than ticking late after an overrun.
It logs one JSON line per tick to stderr. The process exits if no tick completes in 3 minutes, and
its platform restarts it.
