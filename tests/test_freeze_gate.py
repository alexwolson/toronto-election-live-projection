"""The freeze gate: archived payloads against one Frontend commit's validator and release tag."""

import json
import subprocess
from pathlib import Path

import pytest

from election_night.cli import main

TAG = "backend-2026-10-20.1"

# A stand-in for the Frontend's validator, at its path in the Frontend repo. Like the real one it
# is TypeScript with a type-only import, and returns the payload or null.
VALIDATOR = """\
import type { LivePayload } from "@/types/live";

export function validateLivePayload(value: unknown): LivePayload | null {
  const v = value as { schema_version?: unknown };
  return v && v.schema_version === 1 ? (value as LivePayload) : null;
}
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def frontend(tmp_path) -> tuple[str, str]:
    """A Frontend repo whose HEAD carries the validator, and a later commit that breaks it."""
    repo = tmp_path / "frontend"
    validator = repo / "src" / "lib" / "live-payload.ts"
    validator.parent.mkdir(parents=True)
    git(tmp_path, "init", "-q", str(repo))
    validator.write_text(VALIDATOR)
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "validator")
    commit = git(repo, "rev-parse", "HEAD")
    # The working tree moves on; the gate must still use the given commit's validator.
    validator.write_text("export function validateLivePayload() { return null; }\n")
    return str(repo), commit


def archive(root: Path, *payloads: dict) -> Path:
    """Payloads under an archive's `<prefix>/payloads/` keys."""
    for i, payload in enumerate(payloads):
        path = root / "rehearsal" / "payloads" / f"{i}-{i}-{i:016x}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    return root


def payload(**fields) -> dict:
    return {"schema_version": 1, "forecast_release_tag": TAG} | fields


def gate(frontend, *archives: Path, tag: str = TAG) -> int:
    repo, commit = frontend
    args = ["freeze-gate", "--frontend-repo", repo, "--frontend-commit", commit]
    args += ["--backend-release-tag", tag]
    for path in archives:
        args += ["--archive", str(path)]
    try:
        main(args)
    except SystemExit as error:
        return error.code
    return 0


def test_a_clean_archive_passes(frontend, tmp_path, capsys):
    fly = archive(tmp_path / "fly", payload(), payload())
    do = archive(tmp_path / "do", payload())

    assert gate(frontend, fly, do) == 0
    assert "3 payloads pass" in capsys.readouterr().out


def test_a_payload_failing_validation_fails_the_gate(frontend, tmp_path, capsys):
    fly = archive(tmp_path / "fly", payload(), payload(schema_version=2))

    assert gate(frontend, fly) != 0
    assert "1-1-0000000000000001.json" in capsys.readouterr().out


def test_a_tag_mismatch_fails_the_gate(frontend, tmp_path, capsys):
    fly = archive(tmp_path / "fly", payload(), payload(forecast_release_tag="backend-2026-10-07.2"))

    assert gate(frontend, fly) != 0
    assert "backend-2026-10-07.2" in capsys.readouterr().out


def test_a_null_tag_fails_the_gate(frontend, tmp_path, capsys):
    fly = archive(tmp_path / "fly", payload(forecast_release_tag=None))

    assert gate(frontend, fly) != 0
    assert "forecast release tag None" in capsys.readouterr().out


def test_an_unreadable_payload_fails_the_gate(frontend, tmp_path, capsys):
    fly = archive(tmp_path / "fly", payload())
    (fly / "rehearsal" / "payloads" / "9-9-bad.json").write_text("{not json")

    assert gate(frontend, fly) != 0
    assert "9-9-bad.json: not a readable payload" in capsys.readouterr().out


def test_an_archive_without_payloads_fails_the_gate(frontend, tmp_path, capsys):
    (tmp_path / "fly").mkdir()

    assert gate(frontend, tmp_path / "fly") != 0
    assert "no payloads under" in capsys.readouterr().out


def test_a_commit_that_cannot_be_checked_out_fails_the_gate(frontend, tmp_path, capsys):
    fly = archive(tmp_path / "fly", payload())

    assert gate((frontend[0], "0" * 40), fly) != 0
    assert "no checkout of" in capsys.readouterr().out


def test_a_validator_that_cannot_run_fails_the_gate(tmp_path, capsys):
    repo = tmp_path / "frontend"
    git(tmp_path, "init", "-q", str(repo))
    (repo / "README.md").write_text("no validator here\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "no validator")
    fly = archive(tmp_path / "fly", payload())

    assert gate((str(repo), git(repo, "rev-parse", "HEAD")), fly) != 0
    assert "the validator didn't run" in capsys.readouterr().out


def test_a_relative_frontend_repo_path_works(frontend, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fly = archive(tmp_path / "fly", payload())

    assert gate(("frontend", frontend[1]), fly) == 0
