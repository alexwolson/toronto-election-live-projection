"""The freeze gate: archived payloads against the exact production Frontend build (#17 § Schema skew).

Every payload in the archives must pass the given Frontend commit's validator, and carry the
forecast release tag that build serves. The validator comes from a fresh checkout of that commit,
never a working copy, and Node runs its TypeScript directly (type stripping, Node 22.18+), so the
gate needs no `npm ci`. Anything the gate can't check is a failure: an unreadable payload, an
archive with no payloads, or a validator Node can't load.
"""

import json
import subprocess
import tempfile
from pathlib import Path

FRONTEND_REPO = "https://github.com/alexwolson/toronto-election-poll-tracker.git"
VALIDATOR = "src/lib/live-payload.ts"

# Reads a JSON list of payload paths on stdin; prints whether each passes `validateLivePayload`.
RUNNER = """
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const { validateLivePayload } = await import(pathToFileURL(process.argv[1]).href);
const paths = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify(paths.map(
  (p) => validateLivePayload(JSON.parse(readFileSync(p, "utf8"))) !== null)));
"""


def checkout(repo: str, commit: str, into: Path) -> Path:
    """A clean checkout of exactly `commit`; returns its validator's path."""
    if Path(repo).exists():  # a local repo; git runs in `into`, so make the path absolute
        repo = str(Path(repo).resolve())
    for args in (
        ["init", "-q"],
        ["fetch", "-q", "--depth", "1", repo, commit],
        ["checkout", "-q", "--detach", "FETCH_HEAD"],
    ):
        done = subprocess.run(
            ["git", "-C", str(into), *args], capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise RuntimeError(f"no checkout of {commit} from {repo}: {done.stderr.strip()}")
    return into / VALIDATOR


def validate(validator: Path, paths: list[Path]) -> list[bool]:
    """Run the validator over the payload files with Node; raises if Node fails."""
    done = subprocess.run(
        ["node", "--input-type=module", "-e", RUNNER, str(validator)],
        input=json.dumps([str(p) for p in paths]),
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"the validator didn't run: {done.stderr.strip()}")
    return json.loads(done.stdout)


def check_archives(archives: list[Path], repo: str, commit: str, tag: str) -> tuple[int, list[str]]:
    """The number of payloads checked and one line per failure."""
    paths = sorted(p for root in archives for p in root.glob("**/payloads/*.json"))
    if not paths:
        return 0, [f"no payloads under {', '.join(map(str, archives))}"]
    failures, readable = [], []
    for path in paths:
        try:
            payload_tag = json.loads(path.read_bytes())["forecast_release_tag"]
        except OSError, ValueError, TypeError, KeyError:
            failures.append(f"{path}: not a readable payload")
            continue
        readable.append(path)
        if payload_tag != tag:
            failures.append(f"{path}: forecast release tag {payload_tag} is not {tag}")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            verdicts = validate(checkout(repo, commit, Path(tmp)), readable)
        except (RuntimeError, OSError) as error:
            return len(paths), failures + [str(error)]
    failures += [
        f"{p}: fails the validator at {commit}" for p, ok in zip(readable, verdicts) if not ok
    ]
    return len(paths), sorted(failures)
