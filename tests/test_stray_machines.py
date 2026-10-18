"""A Fly Machine on an unreachable host survives a deploy and comes back later (#111)."""

import subprocess
from pathlib import Path

from election_night.status import list_machines, render_machines

CHECK = Path(__file__).resolve().parents[1] / "deploy" / "unreachable-check.sh"

# The Mock Feed deploy of Oct 16 (run 38957849954): Fly skipped the old Machine and carried on.
OCT_16 = """\
Updating existing machines in 'toronto-election-mock-feed' with immediate strategy
> Skipped lease for unreachable machine d896d2f4e01708
> Updating machine config for d896d2f4e01708
> Replacing d896d2f4e01708 [app] by new machine
"""
CLEAN = """\
Updating existing machines in 'toronto-election-mock-feed' with immediate strategy
> Updating machine config for 8ed9063b372648
> Machine 8ed9063b372648 updated successfully!
"""


def check(tmp_path: Path, log: str) -> subprocess.CompletedProcess:
    path = tmp_path / "deploy.log"
    path.write_text(log)
    return subprocess.run(
        [str(CHECK), str(path), "toronto-election-mock-feed"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_deploy_that_skipped_an_unreachable_machine_fails_naming_it(tmp_path):
    result = check(tmp_path, OCT_16)
    assert result.returncode == 1
    assert "d896d2f4e01708" in result.stdout
    assert "flyctl machine destroy d896d2f4e01708 -a toronto-election-mock-feed --force" in (
        result.stdout
    )


def test_a_clean_deploy_passes(tmp_path):
    assert check(tmp_path, CLEAN).returncode == 0


def machine(id_: str, state: str = "started", digest: str = "sha256:aaa") -> dict:
    return {"id": id_, "state": state, "region": "yyz", "image_ref": {"digest": digest}}


def test_one_started_machine_per_app_reads_ok():
    text = "\n".join(render_machines({"toronto-election-night-fly": [machine("m1")]}))
    assert "| toronto-election-night-fly | m1 | started | yyz | `sha256:aaa` |  |" in text
    assert "**" not in text


def test_a_second_machine_on_another_digest_is_flagged():
    apps = {"toronto-election-night-fly": [machine("m1"), machine("m0", digest="sha256:old")]}
    text = "\n".join(render_machines(apps))
    assert "**2 Machines, expected 1**" in text
    assert "`sha256:old`" in text
    assert "**images differ**" in text


def test_no_started_machine_is_flagged():
    text = "\n".join(render_machines({"app": [machine("m1", state="stopped")]}))
    assert "**not started**" in text
    assert "**no Machines**" in "\n".join(render_machines({"app": []}))


def test_an_app_fly_could_not_list_says_so():
    text = "\n".join(render_machines({"app": "flyctl: not found"}))
    assert "**Couldn't check:** flyctl: not found" in text


def test_list_machines_asks_flyctl_per_app_and_keeps_a_failure_as_its_reason(tmp_path, monkeypatch):
    fake = tmp_path / "flyctl"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$4" = good ]; then echo \'[{"id": "m1"}]\'; else printf "Error: app\nnot found\n" >&2; exit 1; fi\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    listed = list_machines(["good", "gone"])
    assert listed["good"] == [{"id": "m1"}]
    assert listed["gone"] == "Error: app not found"


def test_list_machines_without_flyctl_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert list_machines(["app"])["app"] == "flyctl is not installed"
