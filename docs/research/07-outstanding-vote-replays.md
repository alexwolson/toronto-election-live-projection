# The projection's Outstanding Vote, scored on the Replays

**Research date:** 2026-10-20 · **Ticket:** [#128](https://github.com/alexwolson/toronto-election-live-projection/issues/128) · **Status:** findings, and Alex's decision not to publish an Outstanding Vote estimate (#128 and #131 closed).

**Question.** #128 chose to publish the count-extension projection's own Outstanding Vote (each
draw's final total less the votes counted), from the draws behind the Estimated Range. Before
running the gates, does that figure match the true remaining vote on held-out Replays?

**Labels.** **OBSERVED** means computed from the Replays. **INFERRED** means reasoned from those
figures. Code ran on a branch, now discarded, that added `draw_final_votes` and the payload's
`outstanding`. The scripts were throwaway files in the session scratchpad. The bands on that branch
were byte-identical to `main` in all 11 goldens, so the shares below are the shipped model's.

## Method

Each Replay night (2022, 2023) uses its own fold's bundle (`replay_bundle`, ADR 0029), so it is held
out. For each pre-registered timing pattern (early, interleaved, late; orders 0 and 1), snapshots
are taken at 25, 50, 75 and 90% of Reporting Units in. The truth at a snapshot is the race's final
count less its count at that snapshot. The estimate is the count-only draws' middle tick, and the
range is their central 90%.

## Findings

**1. The mayor's estimate is biased, and its sign follows the arrival pattern (OBSERVED).**
The table gives the error of the middle tick against the truth. `*` marks the truth inside the 90% range.

| Night | Pattern | Order | 25% in | 50% in | 75% in | 90% in |
|---|---|---|---|---|---|---|
| 2022 | early | 0 | +70% | +50% | +76% | +145% |
| 2022 | early | 1 | +58% | +49% | +73% | +138% |
| 2022 | interleaved | 0 | −15% | +5%* | +41% | +102% |
| 2022 | interleaved | 1 | −26% | +6%* | +23% | +72% |
| 2022 | late | 0 | −38% | −36% | −32% | +2%* |
| 2022 | late | 1 | −36% | −31% | −31% | −1%* |
| 2023 | early | 0 | +48% | +39% | +43% | +90% |
| 2023 | early | 1 | +48% | +38% | +56% | +86% |
| 2023 | interleaved | 0 | −21% | +0%* | +12% | +63% |
| 2023 | interleaved | 1 | −28% | −7%* | +19% | +69% |
| 2023 | late | 0 | −37% | −29% | −32% | −7%* |
| 2023 | late | 1 | −42% | −32% | −34% | −15% |

The 90% range holds the truth in 8 of 48 cells. In 2022 interleaved at 90% in, the page would have
said about 107,000 votes still to count when about 53,000 remained.

**2. Council and trustee are similar (OBSERVED, 2022 interleaved order 0, 59 races).** The summed
estimate against the summed truth is +2% at 10% in and +10% at 50%, then +41% at 75% and +102% at
90%. Each race's 90% range holds its truth in 95% of races at 25 and 50% in, falling to 78% at 75%
and 64% at 90%.

**3. The expected sizes are right (OBSERVED).** Held out, the advance and mail aggregates' expected
sizes total 137,255 against 133,697 true in 2022, and 155,777 against 157,765 in 2023. The two
advance codes are each about 15% off in opposite directions (98 high, 99 low).

**4. The cause is which Ward Aggregates the model believes are in (OBSERVED).** This is the mayor's
citywide turnout-level posterior and its identification of aggregates in, order 0:

| Night | Pattern | At | Level, posterior mean | True level | Aggregates in (true) | Mean \|E[in] − true\| per ward |
|---|---|---|---|---|---|---|
| 2022 | early | 25% / 50% / 90% | 0.413 / 0.350 / 0.324 | 0.291 | 75 / 75 / 75 | 1.47 / 1.50 / 1.43 |
| 2022 | interleaved | 25% / 50% / 90% | 0.259 / 0.300 / 0.321 | 0.291 | 24 / 41 / 69 | 0.50 / 0.60 / 1.24 |
| 2022 | late | 25% / 50% / 90% | 0.209 / 0.228 / 0.292 | 0.291 | 0 / 0 / 37 | 0.78 / 1.17 / 0.94 |
| 2023 | early | 25% / 50% / 90% | 0.499 / 0.446 / 0.414 | 0.384 | 75 / 75 / 75 | 1.36 / 1.48 / 1.46 |
| 2023 | interleaved | 25% / 50% / 90% | 0.324 / 0.385 / 0.408 | 0.384 | 18 / 42 / 70 | 0.75 / 0.73 / 1.28 |
| 2023 | late | 25% / 50% / 90% | 0.274 / 0.320 / 0.379 | 0.384 | 0 / 0 / 37 | 1.15 / 1.48 / 0.61 |

- **Early arrival:** with every aggregate in, the model credits about half of them. It reads their votes as election-day units at a higher turnout, so it expects too much still to come.
- **Late arrival:** with none in, it credits about one per ward. It reads election-day votes as aggregates at a lower turnout, so it expects too little.
- **Late in the night:** it still holds about 1.3 aggregates per ward out after most are in. That is the source of the large overestimates at 90%.

This is the identification problem of [#70](https://github.com/alexwolson/toronto-election-live-projection/issues/70), measured on #36.

**5. Why the gates never saw it (INFERRED).** The gates score final shares. A misidentified
aggregate moves the expected total far more than it moves the split, so shares stay calibrated
while totals do not. The Outstanding Vote is the first output that depends on the total.

## Decision

Alex, 2026-10-20: no Outstanding Vote estimate is published. #128 and #131 are closed. The only
known fix is an arrival-timing prior, #70. It was closed on 2026-10-19 because the City Clerk did not
say when advance and mail results are loaded, and a 2022/2023 timing prior made 2023 worse (#36).
The shipped model, its gates and the Night Bundle are unchanged.

**What this does not cover.** Only the count-only draws were scored for the mayor. The
forecast-weighted weights reweight on shares, so they are not expected to repair totals, but they
were not measured. The Possible Range is unaffected: it bounds the outstanding votes by every
remaining elector, with no model.
