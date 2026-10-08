"""The store: one Redis database that holds the newest payload and each pipeline's heartbeat.

Key layout (docs/store.md): `payload` holds the payload bytes, `payload:seq` its "<a>,<w>" seq
pair, and `heartbeat:<pipeline>` the epoch milliseconds of that pipeline's last valid read.
"""

import json

import redis

PAYLOAD_KEY = "payload"
SEQ_KEY = "payload:seq"
PIPELINES = ("fly", "do")

# S7: a pair is newer only if neither seq is older and at least one is newer. Equal and mixed
# pairs are rejected. Seqs are epoch milliseconds, exact as Lua doubles (below 2^53).
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
return 1
"""


def heartbeat_key(pipeline: str) -> str:
    return f"heartbeat:{pipeline}"


class Store:
    def __init__(self, client: redis.Redis):
        self.client = client
        self._newest_pair = client.register_script(NEWEST_PAIR_LUA)

    def publish(self, payload: bytes) -> bool:
        """Store the payload if its seq pair is newer than the stored one; True if stored."""
        seq = json.loads(payload)["seq"]
        a, w = int(seq["all_office"]), int(seq["ward_by_ward"])
        return bool(self._newest_pair(keys=[PAYLOAD_KEY, SEQ_KEY], args=[payload, a, w]))

    def heartbeat(self, pipeline: str, ms: int) -> None:
        self.client.set(heartbeat_key(pipeline), ms)
