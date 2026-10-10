"""Night Close (#51): a store flag set by hand, and the shutdown of one environment's apps."""

import os
import subprocess
from pathlib import Path

import pytest

from election_night.night_close import KEY, clear, close, night_close_state

SHUTDOWN = Path(__file__).resolve().parents[1] / "deploy" / "shutdown.sh"


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        (None, "open"),
        (b"closed", "closed"),
        (b"close", "open (unrecognized value 'close')"),
        (b"on", "open (unrecognized value 'on')"),
    ],
)
def test_only_closed_closes_the_night(raw, state):
    # The switches fail closed; Night Close fails open, so a typo never puts up "Elected".
    assert night_close_state(raw) == state


def test_close_and_clear_write_and_read_back(redis_client):
    redis_client.flushdb()
    assert close(redis_client) == "closed"
    assert redis_client.get(KEY) == b"closed"
    assert clear(redis_client) == "open"
    assert redis_client.get(KEY) is None


# Fake CLIs: each logs its arguments and answers the list calls with both environments' apps,
# until the app is destroyed.
FLYCTL = """#!/usr/bin/env bash
echo "flyctl $*" >> "$LOG"
if [ "$1 $2" = "apps list" ]; then
  apps='[{"Name":"toronto-election-rehearsal-fly"},{"Name":"toronto-election-night-fly"},{"Name":"toronto-election-mock-feed"}]'
  for gone in $(grep -o 'apps destroy [a-z-]*' "$LOG" | awk '{print $3}'); do
    apps=$(jq -c --arg g "$gone" 'map(select(.Name != $g))' <<< "$apps")
  done
  echo "$apps"
fi
"""
DOCTL = """#!/usr/bin/env bash
echo "doctl $*" >> "$LOG"
if [ "$1 $2" = "apps list" ]; then
  apps='[{"id":"r1","spec":{"name":"toronto-election-rehearsal-do"}},{"id":"n1","spec":{"name":"toronto-election-night-do"}}]'
  for gone in $(grep -o 'apps delete [a-z0-9]*' "$LOG" | awk '{print $3}'); do
    apps=$(jq -c --arg g "$gone" 'map(select(.id != $g))' <<< "$apps")
  done
  echo "$apps"
fi
"""


def run_shutdown(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("flyctl", FLYCTL), ("doctl", DOCTL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "log"
    log.touch()
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log)}
    result = subprocess.run(
        ["bash", str(SHUTDOWN), *args], env=env, capture_output=True, text=True, check=False
    )
    return result, log.read_text()


@pytest.mark.parametrize(
    ("env", "other", "do_id"), [("night", "rehearsal", "n1"), ("rehearsal", "night", "r1")]
)
def test_shutdown_destroys_only_the_named_environment(tmp_path, env, other, do_id):
    result, log = run_shutdown(tmp_path, env)
    assert result.returncode == 0, result.stderr
    destroyed = [line for line in log.splitlines() if " destroy " in line or " delete " in line]
    assert destroyed == [
        f"flyctl apps destroy toronto-election-{env}-fly --yes",
        f"doctl apps delete {do_id} --force",
    ]
    assert other not in "\n".join(destroyed)


@pytest.mark.parametrize("args", [(), ("mock-feed",), ("night", "rehearsal"), ("",)])
def test_shutdown_refuses_anything_but_one_environment(tmp_path, args):
    result, log = run_shutdown(tmp_path, *args)
    assert result.returncode != 0
    assert log == ""
