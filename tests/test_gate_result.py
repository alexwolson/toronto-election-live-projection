"""Gate Results and the model version (spec #17 § Gate Result; ticket #29)."""

import json

import pytest

from election_night.replay.gate_result import model_files, model_version, write_gate_result


def _tree(root):
    """A tiny repo: model code, frozen parameters, a forecast and unrelated code."""
    for path, text in {
        "src/election_night/payload.py": "def build(): ...\n",
        "src/election_night/feed.py": "def read(): ...\n",
        "src/election_night/projection/council.py": "def project(): ...\n",
        "src/election_night/cli.py": "def main(): ...\n",
        "gates/params/council.json": '{"spread": 1.0}\n',
        "data/night-bundle/inputs/mayoral_forecast.json": '{"tag": "backend-1"}\n',
    }.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")


def _version(root):
    return model_version(root, model_files(root))


def test_the_model_version_changes_with_the_code(tmp_path):
    _tree(tmp_path)
    before = _version(tmp_path)
    (tmp_path / "src/election_night/projection/council.py").write_text("def project(): 1\n")

    assert _version(tmp_path) != before


def test_the_model_version_changes_with_the_frozen_parameters(tmp_path):
    _tree(tmp_path)
    before = _version(tmp_path)
    (tmp_path / "gates/params/council.json").write_text('{"spread": 1.5}\n')

    assert _version(tmp_path) != before


def test_the_model_version_changes_when_a_model_file_is_added(tmp_path):
    _tree(tmp_path)
    before = _version(tmp_path)
    (tmp_path / "gates/params/trustee.json").write_text("{}\n")

    assert _version(tmp_path) != before


def test_the_model_version_ignores_the_forecast_and_code_outside_the_model(tmp_path):
    _tree(tmp_path)
    before = _version(tmp_path)
    (tmp_path / "data/night-bundle/inputs/mayoral_forecast.json").write_text('{"tag": "b-2"}\n')
    (tmp_path / "src/election_night/cli.py").write_text("def main(): 2\n")
    cache = tmp_path / "src/election_night/projection/__pycache__"
    cache.mkdir()
    (cache / "council.cpython-314.pyc").write_bytes(b"\0")

    assert _version(tmp_path) == before


def test_gate_results_are_written_once_and_the_run_count_increments(tmp_path):
    first = write_gate_result({"level": "council", "pass": False}, tmp_path, "council")
    second = write_gate_result({"level": "council", "pass": True}, tmp_path, "council")
    other = write_gate_result({"level": "trustee", "pass": False}, tmp_path, "trustee")

    assert first.name == "council-run-001.json"
    assert second.name == "council-run-002.json"
    assert other.name == "trustee-run-001.json"
    assert json.loads(first.read_text())["run"] == 1
    assert json.loads(first.read_text())["pass"] is False  # untouched by the second run
    assert json.loads(second.read_text())["run"] == 2


def test_an_existing_gate_result_is_never_overwritten(tmp_path):
    write_gate_result({"pass": False}, tmp_path, "council")
    (tmp_path / "council-run-001.json").rename(tmp_path / "council-run-002.json")

    with pytest.raises(FileExistsError):
        write_gate_result({"pass": True}, tmp_path, "council")
    assert json.loads((tmp_path / "council-run-002.json").read_text())["pass"] is False
