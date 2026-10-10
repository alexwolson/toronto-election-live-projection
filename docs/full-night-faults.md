# Full-night fault schedule

The Mock Feed's Full-night fault script (#48; #17 § Rehearsal plan, Fault script), for the
Full-night Rehearsal checklist (#53). Deploy the Mock Feed with `faults: full-night`, speed 1, and a
start at 19:50 local time, so the times below are both the night clock and the wall clock.

Each row gives the fault (its `kind` in `FULL_NIGHT`, `src/election_night/mockfeed/feed.py`), the
expected reader state, and what the payload, store and alerts should show. Every data fault's state is
tested in `tests/test_mockfeed_full_night.py` with the real Night Bundle, where all three levels are
live. The races are fixed, except the 100% race, which is chosen from the arrival order (the race
given is for the default `--seed 0`).

Reader wording is #43's: a Withdrawal reads "No projection for this race right now. The count is as
the City reports it.", hidden Reporting Progress reads "Voting areas: not available", and a race with
no figures reads "No figures from the City for this race right now".

## Timeline

| When (EDT) | Fault | Expected reader state | Payload, store and alerts |
|---|---|---|---|
| 19:50–20:00 | Sept 28 repeat (built in) | "Before results" and the REHEARSAL bar, despite live-looking counts | `state: before_results`, `rehearsal: true` |
| 20:00–20:10 | none | Counting starts | |
| 20:10–20:25 | the per-race faults below, all at once | each race as listed; every other race is unaffected | |
| 20:25–20:30 | none | All races are back to normal | Withdrawals lift |
| 20:30–20:40 | `zeros`: both files regenerated as the zeroed test files, with current `seq`s | Every race shows zero votes ("no voting areas in") | Citywide decrease: `count-decrease` sounds once; every race and ward is recorded in `count_decreases`. Alex may test the page pause here |
| 20:40 | none | The counts return, higher than before | |
| 20:45–21:15 | `stall`: a long 304 run | The count holds; "City count as of 8:45 p.m."; no banner | Heartbeats stay fresh |
| 21:20–21:30 | `stalled-seq`: 200s with advancing counts and both `seq`s frozen at 21:20 | The page holds the first count it took at the 21:20 pair; no banner | The store rejects the equal pairs. **The pipelines may archive different payloads for the 21:20 pair**, so the byte-identical check excepts that pair. Exact tallies: the stored payload matches one of `reference`'s entries for the pair |
| 21:30 | none | The count jumps forward | |
| 21:35–21:45 | `5xx`: 503 on both files | The banner shows from about 21:40 | The pairs are rejected, so no heartbeat; `reader-path` goes stale and sounds once at about 5 minutes; `pipeline-*` keep pinging, since every tick completes |
| 21:50–22:00 | `throttle`: 403 on both files | As for 5xx | |
| 22:05–22:15 | `timeout`: responses held 25 s, past the pipeline's 20 s timeout | As for 5xx | |
| 22:20–22:30 | `truncated`: half the all-office body | As for 5xx: the pair is rejected | |
| 22:35–22:45 | `renamed`: the ward-by-ward `candidate` key renamed | As for 5xx | |
| 22:50–23:00 | `one-file`: ward-by-ward 503, all-office fine | As for 5xx: a good file is never paired with an older copy of the other | |
| 23:37 | none: the main count ends with 4 units held back | | |
| 23:37–01:37 | `all-in`: `councillor-13` shows `pollsReceived = polls` | "All voting areas in", no range, and the votes still rise at 01:07 and 01:37 | `state: all_units_in`, `projection: null`, no Withdrawal |
| 00:07, 00:37, 01:07, 01:37 | the near-silent tail: one unit at each (wards 24, 9, 13, 13) | Small changes, with 304s between | Files regenerate only at arrivals |
| from 01:37 | none | The count is complete | Night Close may be declared after two quiet hours (03:37 or later) |

## Per-race faults (20:10–20:25)

| Fault | Race | What the feed does | Expected reader state | Machine reason |
|---|---|---|---|---|
| `row-unreadable` | `councillor-4` | a candidate's `votesReceived` is `"-"` | "No figures from the City for this race right now" | `fault: row_unreadable` |
| `race-missing` | `tcdsb-3` | the row is dropped | "No figures from the City for this race right now" | `fault: race_missing` |
| `received-above-polls` | `councillor-6` | `pollsReceived` = `polls` + 1 | tally shown, "Voting areas: not available", no range | `withdrawal: polls_received_above_polls` |
| `polls-zero` | `tdsb-5` | `polls` = 0 (2022's MonAvenir fault in a TDSB area) | as above; every other trustee race keeps its range | `withdrawal: polls_zero` |
| `polls-differ` | `councillor-7` | `polls` one more than the bundle's | as above | `withdrawal: polls_differ_from_bundle` |
| `votes-mismatch` | `councillor-8` | `votesReceived` one more than the candidates' sum | tally shown (shares from candidate votes), no range | `withdrawal: votes_received_mismatch` |
| `above-expected` | `councillor-10` | the leader gains twice the ward's electors | tally shown, no range | `withdrawal: count_above_expected` |
| `unknown-name` | `councillor-12` | the last-listed candidate is renamed "Rehearsal Unknown" | the feed name as written; the range continues | none |
| `race-not-in-bundle` | `councillor-26` | an extra council row, "Rehearsal Ward" | nothing: the race is ignored | none |
| `ward-votes-counted` | `mayor` | Ward 5's `votesCounted` is one more than its candidates' sum, in every repeat | mayor tally shown, no Estimated Range | `withdrawal: ward_votes_counted_mismatch` |
| `count-decrease` | `councillor-14` | the race's count from 10 minutes earlier (zero at 20:10) | the lower count, as served | ward-scope entry in `count_decreases`, badge only, no sound |

Projection numerics (NaN, or a band outside 0–100%) can't come from a City file, so they aren't in
the script. `tests/test_checks.py` covers them by patching the model (#43).

## Exact tallies

The reference is what the Mock Feed actually served, faults included:
`MockFeed.reference(a_seq, w_seq)` returns each race's candidate votes as served under that `seq` pair
(`None` for an unreadable row), read with plain `json` rather than the pipeline's reader. It returns one entry
per pair, except under the stalled `seq`, which has ten. Build the feed with the deployed start,
speed, seed and `full-night` script. A published Live Tally passes if it equals one entry exactly.
Races the payload doesn't carry (`councillor-26`) and races that are `None` or missing (`tcdsb-3`
during its fault) have no tally to compare.
