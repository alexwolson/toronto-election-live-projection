# 0002 — The mayor's projection is approved on the evidence, with a Possible Range beside it

**Status:** accepted (Alex, 2026-10-09) · **Tickets:** #44, #45 · **Supersedes:** for the mayor
only, #17's "no manual override" and the mayoral ladder's fall back to the tally

## Decision

The mayor's forecast-weighted variant goes live on election night, although both mayoral Gate
Results failed (`gates/results/mayor-count-only-run-001.json`,
`gates/results/mayor-forecast-weighted-run-001.json`). This is Alex's approval on the evidence,
not a pass. The Gate Results stand unchanged as the pre-registered record, and the pre-registration
is not edited.

The mayor card shows each candidate:

- **Estimated Range:** the forecast-weighted variant's central 90% final-share range, and only
  that. Below the ESS floor (1,000 of 10,000 draws), or with the forecast off for the night, that
  refresh shows **no Estimated Range**: the count and the Possible Range only (Alex, 2026-10-09).
  Count-only failed its own gate and is not covered by this approval, so its range is never shown.
- **Possible Range:** the final share that is still mathematically possible, from none of the
  outstanding votes going to the candidate up to all of them. The outstanding votes are bounded by
  **every remaining elector** (Alex, 2026-10-09): in each City ward not fully reported, its
  electors less its votes counted, floored at 0; 0 in a ward fully reported. With R that bound
  summed over the wards, V the votes counted and v a candidate's votes, the range is v / (V + R)
  to (v + R) / (V + R). It is strictly possible but wide early in the night, by design.
- **No win probability**, ever, and no chance-to-win or race-call wording (#17).
- **A plain statement** that the model did worse than expected on the 2023 by-election and very
  well on the regular elections it was tested on (2014, 2018, 2022).

Council and trustee passed their Gate Results and go live as pre-registered, with their Estimated
Ranges. **They get a Possible Range too** (Alex, 2026-10-09), bounded the same way: a council
race by its ward's electors, a trustee area by the electors of the City wards it covers (each City
ward lies in exactly one area on each board), less the race's votes counted. The French-language
boards show the count only, as before.

**The electors** are each City ward's registered electors, the ward-by-ward file's `totalVoters`,
recorded in the Night Bundle from the City's test file. The school-board rows' own `totalVoters`
are never used (#17). In 2018 the feed's figure equals the City's voter statistics in every ward,
and in 2023 it is within 2%; the highest ward turnout on either night was about 50% of it, so the
floor at 0 is a guard, not a case expected to arise (`tests/test_possible_range.py`).

## The evidence

From the decisive run (#44; model version `13021e79805d`; 4 nights, 4,561 cases per variant).

The forecast-weighted variant:

| Check | All four nights | Without 2023 (reported only) |
|---|---|---|
| 1. Margin CRPS vs the Tally Baseline (points) | 2.03 vs 2.78 ✓ | 1.26 vs 1.85 |
| 2. Nights beating the tally | 4 of 4 ✓ | 3 of 3 |
| 3. Winner Brier vs the tally | 0.111 vs 0.156 ✓ | 0.012 vs 0.009 (worse) |
| 4. G1, confident calls | 1.000 ✓ | 1.000 |
| 5. G2, margin range coverage | 0.846 ✗ (bar 0.85) | 0.967 |
| 6. The Bailão check (2023 20:26) | 0.746 ✗ (bar under 0.65) | n/a |
| Beats count-only | 2.03 vs 2.15, 3 of 4 nights ✓ | |
| Stress test: G1 / Bailão check | 0.979 ✓ / 0.810 ✗ | |

Per night, its margin CRPS against the tally's absolute error: 2014 2.02 vs 2.98, 2018 0.75 vs
0.98, 2022 1.02 vs 1.58, 2023 4.34 vs 5.58. It beat the tally on every night, including 2023. The
forecast weights never fell below the ESS floor, so the card would never have switched.

## Why

- **2023 is unlike anything before it.** Its early vote differed from its election-day vote far more
  than on any other night (shift spread 0.103 against 0.003–0.033, ADR 0001). The fold that scores
  2023 has to leave 2023 out (Backend ADR 0029), so it never saw such a shift. The failures in criteria 5
  and 6 are that one night: without it, range coverage is 0.967.
- **The model is sound where the record can test it.** On the regular nights it beats the tally in
  margin on each night, and its confident calls were always right.
- **Criterion 3 scores what the page never shows.** It grades win probabilities, which the page
  never shows. On landslide nights the tally's certainty costs nothing, so honest caution scores
  worse (0.012 against 0.009 without 2023). With 2023 included, caution pays and the variant
  passes it.
- **The Possible Range carries the caution the model lacks on a 2023-like night.** It assumes
  nothing about how the outstanding votes will split, so it holds whatever the early vote does.
  Readers see both what the model estimates and what is still possible.

## What this is not

- **Not a pass, and not a gate change.** No criterion, threshold or night is altered after the
  run. Anything that cites these Gate Results must say that both mayoral versions failed and that
  the mayor is live by Alex's approval.
- **Not a model change.** Each approval holds for the one model version it scored. A later change
  to the model code needs its own Replays and its own approval. It binds the way a Gate Result
  does: checked against the running version at pipeline start (#45). One file per approved
  version sits in `gates/approvals/`.

## Approvals

| Model version | Gate Result | Basis |
|---|---|---|
| `13021e79805d` | run 1 | The evidence above (Alex, 2026-10-09). |
| `0b812b0bf91c` | run 2 | #45 changed the payload code, so the version moved. Alex approved again on condition that run 2 matched run 1 within simulation noise. The band was fixed before run 2's variant result landed, from how much council, trustee and count-only moved between the runs (at most 0.0009 pooled, 0.004 on the Bailão check). It allowed pooled scores within 0.005 of run 1 or better, the Bailão checks within 0.015 or better, night counts not lower, and no criterion that passed in run 1 failing. Run 2 was within it on every value: CRPS 2.031 (2.031), G2 margin 0.845 (0.846), Bailão 0.751 (0.746), stress G1 0.981 (0.979), stress Bailão 0.814 (0.810), still beating count-only on 3 of 4 nights. Council and trustee passed run 2. |
| `1e51d5e37d82` | run 3 | #43 and #46 changed the model code and added the night's frozen parameters (`gates/params/night.json`), so the version moved. The Replays' inputs were unchanged, so the draws differ only through their seed. Alex approved again on the same condition, that run 3 match run 2 within simulation noise. The same band was fixed before run 3 started (2026-10-10 11:17Z). Run 3 was within it on every value: CRPS 2.031 (2.031), G2 margin 0.845 (0.845), Bailão 0.759 (0.751), stress G1 0.979 (0.981), stress Bailão 0.821 (0.814), still beating count-only on 3 of 4 nights. Council and trustee passed run 3. |
- **No hidden claim.** The page states that the model did worse than expected on 2023, as above.
  Its wording is drafted with the rest of the on-night wording and approved by Alex (#54).

## For the implementing tickets

- **Payload and page** (#45, schema 3). The approval is `gates/approvals/mayor-forecast-weighted.json`,
  read into the Night Bundle's `gates` with every Gate Result. The payload publishes only the band
  it shows, and each counting race's Possible Range.
