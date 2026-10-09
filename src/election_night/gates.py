"""The pre-registered gates (spec #17 § Pre-registered gates; ticket #23).

`gates/preregistration.json` is frozen before the first replay (ADR 0005, ADR 0030). This module
reads it back, and computes the one number in it that comes from data: the wrong-forecast stress
test's shift (S3), from the held-out 1-day forecasts (S4).
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HOLDOUT_FORECASTS = ROOT / "data" / "forecasts" / "holdout-1d"

# Every section #17 § Pre-registered gates asks for.
SECTIONS = (
    "nights",
    "fitting",
    "arrival_orders",
    "checkpoints",
    "real_captures",
    "baseline",
    "scores",
    "pass_criteria",
    "forecast_weighted_variant",
    "forecast_density",
    "stress_test_shift",
    "ward_aggregate_paths",
    "gate_result",
)


def load_preregistration(path: Path) -> dict:
    """The parsed file. Fails if a section is missing, so a partial file can't be used."""
    prereg = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [s for s in SECTIONS if s not in prereg]
    if missing:
        raise ValueError(f"pre-registration is missing {', '.join(missing)}")
    return prereg


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Holdout:
    """One campaign's held-out forecast draws, with its certified result."""

    campaign: str
    full_ballot: np.ndarray  # draws x named candidates, shares of valid votes
    candidate_ids: list[str]
    actual_shares: dict[str, float]  # candidate_id -> certified share of valid votes


def forecast_pair(full_ballot: np.ndarray) -> tuple[int, int]:
    """The forecast's leader and challenger: its top two by win probability (S2).

    Production's rule (Backend `compact_mayoral_feed.py`): each draw's winner is its largest
    share; ties in win probability go to the earlier column.
    """
    wins = np.bincount(full_ballot.argmax(axis=1), minlength=full_ballot.shape[1])
    order = sorted(range(full_ballot.shape[1]), key=lambda i: (-wins[i], i))
    return order[0], order[1]


def forecast_margin(full_ballot: np.ndarray) -> tuple[int, int, float]:
    """The forecast's pair and its median leader-minus-challenger margin, in points."""
    leader, challenger = forecast_pair(full_ballot)
    margins = 100.0 * (full_ballot[:, leader] - full_ballot[:, challenger])
    return leader, challenger, float(np.median(margins))


def s3_shift(holdouts: list[Holdout]) -> tuple[float, list[dict]]:
    """The 90th percentile (linear interpolation) of the absolute errors in the held-out
    forecasts' median leader-minus-challenger margin, in points (S3). Returns the shift and a
    row per campaign."""
    rows = []
    for h in holdouts:
        leader, challenger, median = forecast_margin(h.full_ballot)
        lead_id, chal_id = h.candidate_ids[leader], h.candidate_ids[challenger]
        actual = 100.0 * (h.actual_shares[lead_id] - h.actual_shares[chal_id])
        rows.append(
            {
                "campaign": h.campaign,
                "leader_candidate_id": lead_id,
                "challenger_candidate_id": chal_id,
                "median_margin_points": median,
                "actual_margin_points": actual,
                "absolute_error_points": abs(median - actual),
            }
        )
    errors = [r["absolute_error_points"] for r in rows]
    return float(np.percentile(errors, 90, method="linear")), rows


def read_forecasts(forecasts_dir: Path) -> list[tuple[str, list[str], np.ndarray]]:
    """The vendored held-out draws (`data/forecasts/holdout-1d/`): per campaign, its
    `candidate_ids` and `full_ballot`, checked against the manifest's sha256."""
    forecasts = []
    for manifest in sorted(Path(forecasts_dir).glob("toronto_*.json")):
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        npz = manifest.parent / meta["npz"]
        if sha256(npz) != meta["npz_sha256"]:
            raise ValueError(f"{npz.name} does not match its manifest's sha256")
        with np.load(npz, allow_pickle=False) as arrays:
            ids = [str(c) for c in arrays["candidate_ids"]]
            full = np.asarray(arrays["full_ballot"], dtype=float)
        forecasts.append((meta["campaign"], ids, full))
    return forecasts


def read_holdouts(forecasts_dir: Path, outcomes_csv: Path) -> list[Holdout]:
    """The held-out draws joined by `candidate_id` to the Backend's certified mayoral outcomes
    (`data/raw/elections/mayoral_outcomes.csv`)."""
    with open(outcomes_csv, encoding="utf-8", newline="") as f:
        outcomes = list(csv.DictReader(f))
    return [
        Holdout(
            campaign,
            full,
            ids,
            {
                r["candidate_id"]: float(r["share"])
                for r in outcomes
                if r["election_cycle_id"] == campaign
            },
        )
        for campaign, ids, full in read_forecasts(forecasts_dir)
    ]


def s3_record(forecasts_dir: Path, outcomes_csv: Path, outcomes_source: dict) -> dict:
    """The `stress_test_shift` block of the pre-registration file: result, inputs and sources.

    `outcomes_source` names where the outcomes file came from (`repo`, `path`, `commit`); the
    file is the Backend's and is not vendored here.
    """
    shift, rows = s3_shift(read_holdouts(forecasts_dir, outcomes_csv))
    forecasts = Path(forecasts_dir).resolve()
    return {
        "id": "S3",
        "rule": (
            "90th percentile (linear interpolation) of the absolute errors in the 1-day held-out "
            "forecasts' median leader-minus-challenger margin, over all seven historical "
            "campaigns; leader and challenger are the forecast's top two by win probability"
        ),
        "applied_as": "a location shift of every forecast margin draw against the eventual winner",
        "shift_points": round(shift, 6),
        "campaigns": [
            {k: round(v, 6) if isinstance(v, float) else v for k, v in r.items()} for r in rows
        ],
        "sources": {
            "command": (
                "uv run election-night s3-shift --outcomes <backend>/"
                + outcomes_source["path"]
                + " --outcomes-commit "
                + outcomes_source["commit"]
            ),
            "forecasts_dir": forecasts.relative_to(ROOT).as_posix(),
            "forecasts": {p.name: sha256(p) for p in sorted(forecasts.glob("toronto_*.json"))},
            "outcomes": {**outcomes_source, "sha256": sha256(outcomes_csv)},
        },
    }
