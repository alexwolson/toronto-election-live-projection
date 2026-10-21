# 0005 — The Estimated Range is the central 99%; a carryover holds Gate Results across an unscored change

**Status:** proposed (Alex, 2026-10-20; awaiting Alex's carryover record) · **Amends:** ADR 0002
(the Estimated Range's mass)

## Decision

The Estimated Range the payload publishes is each candidate's **central 99%** final-share range
(`count_extension.BAND = (0.5, 50.0, 99.5)`), for the count-only and forecast-weighted variants.
The reader's wording follows: "99% confidence interval".

The gates are unchanged. G2 still holds the central **90%** range to 85% coverage at the
pre-registered `interval_mass: 0.9`, computed from the draws. No gate reads `BAND`.

**Carryovers.** The model version hashes `projection/`, so this change moves it, and a version
mismatch pauses every level. A Gate Result can now be carried to a new version by Alex's record in
`gates/carryovers/` (`from_version`, `to_version`, the change, the evidence, his sign-off).
`gate_records` reports a carried result at the new version, marked `carried_from`. A carryover is
only for a change no gate scores, backed by a replay showing identical results at a pinned version.

## Evidence

Smoke replays (`--smoke`, the latest night) of `mayor-forecast-weighted` and `council` at the 99%
code, with the model version pinned to `04a507b4`, match the 90% code's results on every field but
timing (2026-10-20). Unpinned, the draws reseed with the version (`payload._seed`), and the values
differ only by simulation noise.

## Caveats

- The 99% label is not itself tested. Run 4 shows the 90% range covers at least 85%, a little
  under its nominal mass; a 99% range covers more, but nothing measures whether it reaches 99%.
- The new version reseeds the night's draws. The carried results were scored on another stream of
  the same model; a fresh run would differ by simulation noise only, as the run-4 approval under
  ADR 0002 already allows.
