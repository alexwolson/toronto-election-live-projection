"""The archive: every City file generation, every payload and one log line per tick.

A file generation is every 200 body, readable or not: a superset of the Count Snapshots.

Each pipeline writes to its own provider's S3-compatible object store (Fly to Tigris,
DigitalOcean to Spaces). Keys are `seq` plus a content hash and are written once, so the two
archives merge by key after the night. Writes run on a background thread behind a bounded queue:
a slow or failing store never blocks or delays publishing, and is counted in the log line instead.
Key layout: docs/store.md § The archive.
"""

import hashlib
import json
import queue
import threading
from collections.abc import Callable

from botocore.exceptions import ClientError

QUEUE_SIZE = 200  # held writes; a City file is under 1 MB


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:16]


def file_key(name: str, body: bytes) -> str:
    """`files/<file>/<seq>-<hash>.json`; a body without a readable `seq` is `unreadable-<hash>`."""
    try:
        seq = str(int(json.loads(body)["seq"]))
    except ValueError, TypeError, KeyError:
        seq = "unreadable"
    return f"files/{name}/{seq}-{_digest(body)}.json"


def payload_key(payload: bytes) -> str:
    seq = json.loads(payload)["seq"]
    return f"payloads/{seq['all_office']}-{seq['ward_by_ward']}-{_digest(payload)}.json"


def log_key(pipeline: str, ms: int, line: bytes) -> str:
    return f"logs/{pipeline}/{ms}-{_digest(line)}.json"


class Archive:
    """One bucket in an S3-compatible store, written once per key.

    Write-once is a HEAD before the PUT rather than `If-None-Match: *`, which Spaces doesn't
    document (research 04). Each bucket has one writer, the pipeline's single archive thread.
    Rehearsal and Night share each bucket, so every key starts with the environment's `prefix`.
    """

    def __init__(self, client, bucket: str, prefix: str = ""):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix

    def put(self, key: str, body: bytes, metadata: dict[str, str] | None = None) -> bool:
        """Write the object unless the key exists; True if written."""
        key = self.prefix + key
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return False
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, Metadata=metadata or {})
        return True


class ArchiveWriter:
    """Archive writes off the publish path: `submit` never waits, a full queue drops the write."""

    def __init__(self, archive: Archive, maxsize: int = QUEUE_SIZE):
        self.archive = archive
        self._queue: queue.Queue = queue.Queue(maxsize)
        self._failed = 0
        self._dropped = 0
        threading.Thread(target=self._work, daemon=True).start()

    def submit(
        self, key: str | Callable[[], str], body: bytes, metadata: dict[str, str] | None = None
    ) -> None:
        """Queue one write. A callable key is computed on the archive thread, off the tick."""
        try:
            self._queue.put_nowait((key, body, metadata))
        except queue.Full:
            self._dropped += 1

    def stats(self) -> dict[str, int]:
        """Writes failed and dropped since the process started."""
        return {"failed": self._failed, "dropped": self._dropped}

    def join(self) -> None:
        """Wait until every submitted write has been tried."""
        self._queue.join()

    def _work(self) -> None:
        while True:
            key, body, metadata = self._queue.get()
            try:
                self.archive.put(key() if callable(key) else key, body, metadata)
            except Exception:  # noqa: BLE001 - any store failure is counted, never raised
                self._failed += 1
            finally:
                self._queue.task_done()
