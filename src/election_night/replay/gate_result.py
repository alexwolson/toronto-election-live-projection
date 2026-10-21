"""Gate Results and the model version they hold for (`gates/preregistration.json` § gate_result).

The model version is a sha256 over the model's code and its frozen parameters: the payload
function, the feed reader and the per-race checks it calls, the projection package and
`gates/params/`. Code outside the model (the command, the pipeline shell, the Replay harness) and
the final forecast, an input, are left out, so neither changes the version a Gate Result holds
for.

A Gate Result is written once and never overwritten. Each level's results are numbered by run,
and every run is kept.
"""

import hashlib
import json
from pathlib import Path

MODEL_CODE = (
    "src/election_night/payload.py",
    "src/election_night/feed.py",
    "src/election_night/checks.py",
    "src/election_night/projection",
)
FROZEN_PARAMS = "gates/params"


def model_files(root: Path) -> list[Path]:
    """Every file the model version hashes, sorted; missing paths are skipped."""
    files = []
    for name in (*MODEL_CODE, FROZEN_PARAMS):
        path = root / name
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files += [
                p
                for p in path.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            ]
    return sorted(files)


def model_version(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def write_gate_result(result: dict, out_dir: Path, level: str) -> Path:
    """Write `result` as the level's next run. Raises FileExistsError rather than overwrite."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = len(list(out_dir.glob(f"{level}-run-*.json"))) + 1
    path = out_dir / f"{level}-run-{run:03d}.json"
    body = json.dumps({**result, "run": run}, ensure_ascii=False, indent=1, sort_keys=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write(body + "\n")
    return path


def gate_records(
    results_dir: Path, approvals_dir: Path, carryovers_dir: Path | None = None
) -> dict[str, dict]:
    """Each level's latest Gate Result as the Night Bundle carries it (#45): pass, model version
    and run, and whether Alex approved that run's model version (ADR 0002). Each approval names
    one level and one version; an approval of any other version approves nothing.

    A carryover (ADR 0005) is Alex's signed record that a model change no gate scores leaves
    the results unchanged: a result at its `from_version`, with any approval of it, holds for
    its `to_version`, marked `carried_from`."""
    latest: dict[str, dict] = {}
    for path in sorted(Path(results_dir).glob("*-run-*.json")):
        level = path.name.rsplit("-run-", 1)[0]
        result = json.loads(path.read_text(encoding="utf-8"))
        if level not in latest or result["run"] > latest[level]["run"]:
            latest[level] = result
    approved: set[tuple[str, str]] = set()  # (level, model version), one per approval file
    for path in sorted(Path(approvals_dir).glob("*.json")):
        approval = json.loads(path.read_text(encoding="utf-8"))
        approved.add((approval["level"], approval["model_version"]))
    carried: dict[str, str] = {}  # from version -> to version
    if carryovers_dir is not None:
        for path in sorted(Path(carryovers_dir).glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            carried[record["from_version"]] = record["to_version"]
    records = {}
    for level, r in sorted(latest.items()):
        record = {
            "pass": bool(r["pass"]),
            "model_version": r["model_version"],
            "run": r["run"],
            "approved": (level, r["model_version"]) in approved,
        }
        if r["model_version"] in carried:
            record["model_version"] = carried[r["model_version"]]
            record["carried_from"] = r["model_version"]
        records[level] = record
    return records
