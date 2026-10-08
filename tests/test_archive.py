"""The archive: write-once keys in each pipeline's object store, written off the publish path."""

import hashlib
import json
import threading
import time

from botocore.exceptions import ClientError

from election_night.archive import Archive, ArchiveWriter, file_key, log_key, payload_key


class FakeS3:
    """The two S3 calls the archive makes, against a dict."""

    def __init__(self):
        self.objects = {}
        self.puts = []

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def put_object(self, Bucket, Key, Body, Metadata):
        self.puts.append(Key)
        self.objects[(Bucket, Key)] = (Body, Metadata)


def test_keys_are_seq_plus_a_content_hash():
    body = json.dumps({"seq": "1793059260000", "office": []}).encode()
    digest = hashlib.sha256(body).hexdigest()[:16]
    assert file_key("unofficialresult.json", body) == (
        f"files/unofficialresult.json/1793059260000-{digest}.json"
    )
    payload = json.dumps({"seq": {"all_office": 5, "ward_by_ward": 7}}).encode()
    assert payload_key(payload) == (f"payloads/5-7-{hashlib.sha256(payload).hexdigest()[:16]}.json")
    assert log_key("fly", 1000, b"{}").startswith("logs/fly/1000-")


def test_an_unreadable_file_is_still_archived_by_its_hash():
    assert file_key("unofficialresult.json", b"<html>").startswith(
        "files/unofficialresult.json/unreadable-"
    )


def test_keys_are_write_once():
    s3 = FakeS3()
    archive = Archive(s3, "night")
    assert archive.put("files/a/1-x.json", b"first", {"received-ms": "1"})
    assert not archive.put("files/a/1-x.json", b"first", {"received-ms": "2"})
    assert s3.puts == ["files/a/1-x.json"]
    assert s3.objects[("night", "files/a/1-x.json")] == (b"first", {"received-ms": "1"})


class HangingArchive:
    def __init__(self):
        self.release = threading.Event()

    def put(self, key, body, metadata=None):
        self.release.wait()
        return True


class FailingArchive:
    def put(self, key, body, metadata=None):
        raise ClientError({"Error": {"Code": "500"}}, "PutObject")


def test_a_hanging_archive_never_delays_a_submit_and_overflow_is_dropped():
    archive = HangingArchive()
    writer = ArchiveWriter(archive, maxsize=2)
    start = time.monotonic()
    for i in range(5):
        writer.submit(f"k{i}", b"", {})
    assert time.monotonic() - start < 0.5
    assert writer.stats()["dropped"] >= 2
    archive.release.set()


def test_a_failing_archive_is_counted_not_raised():
    writer = ArchiveWriter(FailingArchive())
    writer.submit("k", b"", {})
    writer.join()
    assert writer.stats() == {"failed": 1, "dropped": 0}
