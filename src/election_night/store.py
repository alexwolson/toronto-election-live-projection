"""The store: one Redis database that holds the newest payload and each pipeline's heartbeat.

Key layout (docs/store.md): `payload` holds the payload bytes, `payload:seq` its "<a>,<w>" seq
pair, `heartbeat:<pipeline>` the epoch milliseconds of that pipeline's last valid read, and
`count_decreases` one JSON entry per count decrease a pipeline saw, `check_notes` one field
per contained fault (#97), "<race>|<reason>", holding when it was first seen, and `history` one
compact entry per stored count (history.py).
"""

import json

import redis

PAYLOAD_KEY = "payload"
SEQ_KEY = "payload:seq"
DECREASES_KEY = "count_decreases"
CHECK_NOTES_KEY = "check_notes"
HISTORY_KEY = "history"
PIPELINES = ("fly", "do")

# S7: a pair is newer only if neither seq is older and at least one is newer. Equal and mixed
# pairs are rejected. Seqs are epoch milliseconds, exact as Lua doubles (below 2^53). A stored
# pair appends its history entry in the same script, so each stored pair has one entry.
NEWEST_PAIR_LUA = """\
local a, w = tonumber(ARGV[2]), tonumber(ARGV[3])
local stored = redis.call('GET', KEYS[2])
if stored then
  local sa, sw = string.match(stored, '^(%d+),(%d+)$')
  sa, sw = tonumber(sa), tonumber(sw)
  if a < sa or w < sw or (a == sa and w == sw) then
    return 0
  end
end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2] .. ',' .. ARGV[3])
if ARGV[4] ~= '' then
  redis.call('RPUSH', KEYS[3], ARGV[4])
end
return 1
"""


def heartbeat_key(pipeline: str) -> str:
    return f"heartbeat:{pipeline}"


class Store:
    def __init__(self, client: redis.Redis):
        self.client = client
        self._newest_pair = client.register_script(NEWEST_PAIR_LUA)

    def publish(self, payload: bytes, history: bytes | None = None) -> bool:
        """Store the payload if its seq pair is newer than the stored one, appending its history
        entry if it has one; True if stored."""
        seq = json.loads(payload)["seq"]
        a, w = int(seq["all_office"]), int(seq["ward_by_ward"])
        return bool(
            self._newest_pair(
                keys=[PAYLOAD_KEY, SEQ_KEY, HISTORY_KEY], args=[payload, a, w, history or b""]
            )
        )

    def heartbeat(self, pipeline: str, ms: int) -> None:
        self.client.set(heartbeat_key(pipeline), ms)

    def record_check_notes(self, entries: list[dict]) -> None:
        """Keep each contained fault once, as first seen by either pipeline, for `night status`.
        A fault seen on every tick costs one field, not one entry a minute."""
        for entry in entries:
            self.client.hsetnx(
                CHECK_NOTES_KEY, f"{entry['race']}|{entry['reason']}", json.dumps(entry)
            )

    def record_decreases(self, entries: list[dict]) -> None:
        """Append count decreases, one JSON entry each, for `night status`."""
        if entries:
            self.client.rpush(DECREASES_KEY, *(json.dumps(e) for e in entries))
