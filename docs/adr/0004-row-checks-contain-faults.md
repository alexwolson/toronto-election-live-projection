# 0004 — Row checks contain faults instead of withdrawing; the Possible Range always shows

**Status:** accepted (Alex, 2026-10-11) · **Ticket:** #97 · **Amends:** ADR 0002 (the Possible
Range's electors), ADR 0003 (where the badge is absent), #43's "any failed check withdraws"

## Decision

Every row check was an exact comparison, and any failure withdrew the race's projection. For the
mayor, one ward's row withdrew the citywide projection, and a hidden ward progress dropped the
Possible Range and every badge. A one-vote discrepancy was enough. Failures are now tiered:

1. **A vote-sum mismatch never withdraws:** `votes_received_mismatch`,
   `ward_votes_counted_mismatch`, `wards_differ_from_office`. The model and the shares read the
   candidates' votes, never the row totals, and the candidates' sum stands wherever a total is
   used.
2. **A Reporting Progress fault is contained to its row:** `polls_zero`,
   `polls_received_above_polls`, `polls_differ_from_bundle`, and their `ward_` forms for the
   mayor. The progress stays hidden, and the model treats that row's units in as unknown: every
   count from none to all of them is a hypothesis under a flat prior, each count's combinations
   normalised. For the mayor only that ward widens; the Possible Range counts it as not fully
   reported, still bounded by its electors less its counted votes.
3. **A file that contradicts itself withdraws:** `ward_fields_differ`. So do the model's own
   checks, `count_above_expected` and `projection_numerics`, and an unreadable or missing row
   still has no figures.

Tiers 1 and 2 become **check notes** for the operator: a store hash `check_notes`, one field per
race and reason, listed by night status, with no sound and no reader text.

**The Possible Range shows whenever a race is counting.** For the mayor this follows from tier 2.
**The French-language boards get one** from each row's own `totalVoters`, their supporters (in
the City's real 2022 file, e.g. Viamonde 2: 2,498), if above zero, at least the votes counted,
and no more than the electors of the City wards the area covers. A row that fails gets no range,
for that race only. The badges follow the range (ADR 0003). There is still no French projection.
There is no cap on how many mayoral wards can be unknown at once (Alex).

## Why

- **How much a fault costs, not how often it happens.** Measured on every real City capture on
  disk (16 snapshots, 462 rows, 2018–2024), the mayor checks never fired, but there are only two
  ward-by-ward snapshots, so that can't show they are rare. The only real faults were 2022's
  French rows (`polls_zero` all night). The likeliest 2026 fault, the bundle's voting areas from
  the pre-night test file differing from the night's, is untestable on past captures. One bad row
  out of 25 shouldn't withdraw a citywide projection the other 24 support.
- **Bounds stay exact.** A hidden progress only widens the model's band; the Possible Range's
  bound is still every remaining elector.

## Consequences

- The model version moves (`payload.py`, `feed.py`, `count_extension.py`): new Gate Results for
  every level, and the mayor's approval renewed (ADR 0002), before the Deploy Freeze.
- The Replays carry none of these faults, so their scores test only "no harm". The new path is
  scored by no pre-registered gate; its evidence is a reported fault-injection replay (#97).
- The 2026 test file's French `totalVoters` are ward electors, so a Rehearsal can't show realistic
  French ranges; the real values arrive on the night.
- The Full-night fault script's `councillor-6`, `tdsb-5`, `councillor-7`, `councillor-8` and
  mayoral Ward 5 faults no longer withdraw (docs/full-night-faults.md).
