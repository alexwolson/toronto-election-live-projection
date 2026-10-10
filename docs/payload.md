# The payload, schema version 3

The payload is the one citywide JSON file each pipeline publishes per Count Snapshot pair
(#17 § Payload). It is a pure function of the City's two files and the Night Bundle
(`election_night.payload.build_payload`): the same inputs give the same bytes. It is UTF-8,
compact, with keys in the order below. The Frontend validator pins `schema_version`; a change to
this layout bumps it.

Fields marked *v0 null* are in the layout now and filled by later tickets (#46 forecast,
#45 gated statuses).

## Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | `3` (2 added a modelled mayor's `projection.variant`, #41; 3 added the gated `levels`, `projection.shown` and each race's `possible`, #45) |
| `model_version` | string | The Night Bundle's model version. `"stub-v0"` while projections are stubs. |
| `forecast_release_tag` | string or null | The pinned Backend release of the final forecast. *v0 null* |
| `seq` | object | `{"all_office": int, "ward_by_ward": int}`: each file's `seq` (epoch ms). "City count as of" is the older one. |
| `election_desc` | string or null | The all-office file's `electionDesc` as written |
| `rehearsal` | bool | True when either file's `electionDesc` contains `REHEARSAL`: raise the "Rehearsal: not real results" bar |
| `state` | string | `"before_results"` while either `seq` is before the bundle's opening time, whatever the files hold; otherwise `"results"` |
| `levels` | object | Each level's projection status, below |
| `races` | array | Every race in the bundle, in ballot order: mayor, councillor 1–25, TDSB, TCDSB, Viamonde, MonAvenir |

`levels` has keys `mayor`, `council`, `trustee` (TDSB and TCDSB) and `french_trustee`. Each is
`{"projection": status}`. Mayor is `{"projection", "variant", "approved"}`: `projection` is the
mayor's overall status, `variant` the forecast-weighted variant's own, and `approved` true while
the variant is live on Alex's approval rather than a pass (ADR 0002).

| Status | When | The level's races |
|---|---|---|
| `live` | its Gate Result passed, or Alex approved it, for the running model version | carry the shown band |
| `gate_failed` | its Gate Result failed for the running version, with no approval | the tally only |
| `version_mismatch` | its Gate Result (or approval) names another model version | the tally only |
| `gate_missing` | the Night Bundle holds no Gate Result for it | the tally only |
| `stub` | the bundle has no fitted parameters for it | deterministic stub bands, not a projection |
| `ungated` | the bundle carries no Gate Results at all: the Replays and the historical goldens | every band, ungated |
| `none` | never projected (the French-language boards) | the tally only |

The bundle's `gates` (`election_night.replay.gate_result.gate_records`) holds each level's latest
Gate Result as `{"pass", "model_version", "run", "approved"}`. The mayor is `live` if either
version is; the forecast-weighted variant comes first, then count-only (the ladder).

## Race

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `mayor`, `councillor-N`, `tdsb-N`, `tcdsb-N`, `viamonde-N`, `monavenir-N` |
| `level` | string | `mayor`, `council`, `trustee` or `french_trustee` |
| `num` | string | The feed's `num`: `"0"` for mayor, else the ward or area number |
| `name` | string or null | The ward's name; null for school-board areas |
| `state` | string | Below |
| `progress` | object or null | Reporting Progress, `{"received": int, "total": int}` (the feed's `pollsReceived` and `polls`). Null before results, with no figures, or when the row's Reporting Progress fails its check (below). |
| `candidates` | array | Below. Before results: the bundle's candidates in ballot order, without votes. Otherwise the feed's candidates by votes, descending, ties in ballot order. |
| `projection` | object or null | `{"stub": bool, "bands": {variant: {key: {"low", "mid", "high"}}}, "shown": variant or null}`, shares in percent: the Estimated Range. Present only while the race is `counting` and its level is projected (`live`, `stub` or `ungated`); null when the level shows the tally. `shown` is the band the page draws, and on a gated night `bands` holds only that one: council and trustee `count_only`; the mayor `forecast_weighted` while it is in effect, else `count_only` only if count-only is itself live, else none (`shown` null, `bands` empty: ADR 0002). Ungated (the Replays) every band stays. Stub mayor bands have `count_only` and `forecast_weighted`. A modelled mayor also has `"variant"` (below). |
| `possible` | object or null | The Possible Range (ADR 0002): `{key: {"low", "high"}}`, each candidate's final share in percent from none to all of the outstanding votes, bounded by every remaining elector. Mayor: the electors of each City ward not fully reported, less its `votes_counted`; council: its ward's electors; trustee: the electors of the City wards it covers (the bundle's `city_wards`); less the race's votes counted, floored at 0. From the bundle's `electors`, each City ward's `totalVoters` in the City's test file. Present while the race is `counting` at mayor, council or trustee, whatever its gate: it is arithmetic on the count, not a projection. Null otherwise, or without the electors. |
| `withdrawal` | object or null | A Withdrawal: `{"reason": string}`, the machine reason a per-race check withheld the race's projection while its Live Tally stands (below). Recorded at mayor, council and trustee whatever the level's gate; null for the French-language boards, which are never projected. Readers never see the reason. |
| `fault` | object or null | `{"reason": string}`, why a race has no figures: `row_unreadable` or `race_missing`. Readers never see the reason. |
| `wards` | array | Mayor only: each City ward's mayoral vote from the ward-by-ward file, below. Empty when the mayor race has no figures. |

Race states:

| `state` | When | Reader wording |
|---|---|---|
| `before_results` | the payload is before results | "Results from 8 p.m." |
| `no_units_in` | `pollsReceived` is 0 | "No voting areas have reported yet" |
| `counting` | some but not all units in | "N of M voting areas in" |
| `all_units_in` | `pollsReceived` equals `polls` | "All voting areas in" |
| `acclaimed` | the bundle lists one candidate | "acclaimed: the only candidate, so there is no vote." |
| `no_figures` | the race's row is unreadable or missing | "No figures from the City for this race right now" |

A modelled mayor's `projection.variant` is `{"in_effect", "ess", "off_reason"}`:

| Field | Type | Meaning |
|---|---|---|
| `in_effect` | string | `"forecast_weighted"` or `"count_only"`: the band in effect at this refresh, before any gate or switch (#45 applies those) |
| `ess` | number or null | The Kish effective sample size of the forecast weights, of 10,000 draws, to 1 dp; null when the forecast weighted nothing |
| `off_reason` | string or null | Null while the variant is in effect. `low_ess`: the ESS is below 1,000, so this refresh uses count-only (no hysteresis). `forecast_missing`, `forecast_corrupt`, `forecast_unmatched`: the variant is off all night, decided once at pipeline start; `forecast_unmatched` also for a refresh whose names miss the forecast's pair or don't match the bundle's |

## Candidate

| Field | Type | Meaning |
|---|---|---|
| `key` | string | The Ballot Name exactly as the feed writes it; unique within the race |
| `full_name` | string | The Ballot Name as written, for display |
| `short_label` | string or null | The registry `lastName`, or the full Ballot Name when there is none or it repeats in the race. Null only for a name the bundle doesn't hold |
| `candidacy_id` | string or null | The canonical results' `candidacy_id`. Null only for a name the bundle doesn't hold |
| `candidate_id` | string or null | The forecast's `candidate_id`, on the final forecast's leader and challenger only (its `pairwise_margin`: today Chow and Bradford); null on every other row |
| `votes` | int or null | Counted votes; null before results |
| `share` | number or null | 100 × votes / the race's summed candidate votes, 2 dp; null before results or with no votes |

## Mayoral ward

`{"num", "name", "progress", "votes_counted", "votes"}`: the ward's Reporting Progress, the feed's
`votesCounted`, and `votes` as `{key: int}` in the race's candidate order. Before results,
`progress`, `votes_counted` and `votes` are null. A ward whose Reporting Progress fails its check
has `progress` null.

## Per-race checks and Withdrawals

Bad data fails closed race by race, never level by level (#43; #17 § Per-race checks and
Withdrawals, #9; `src/election_night/checks.py`). A failed check withdraws only its own race's
projection, stub bands included, and leaves its Live Tally, with shares always from the
candidates' votes. The first failing check, in this order, is the `withdrawal.reason`:

| Reason | Failure in the race's row | Tally |
|---|---|---|
| `polls_zero` | `polls` is 0 | shown, `progress` null |
| `polls_received_above_polls` | `pollsReceived > polls` | shown, `progress` null |
| `polls_differ_from_bundle` | `polls` differs from the bundle's | shown, `progress` null |
| `votes_received_mismatch` | the row's `votesReceived` is not its candidates' sum | shown |
| `ward_fields_differ` | mayor: a ward's fields differ between the candidates that repeat them | shown |
| `ward_votes_counted_mismatch` | mayor: a ward's `votesCounted` is not its candidates' sum | shown |
| `wards_differ_from_office` | mayor: the wards' `polls`, `pollsReceived`, `votesCounted` or a candidate's votes don't sum to the office's | shown |
| `ward_` + a progress reason | mayor: a ward's Reporting Progress fails (against the bundle's ward `polls`) | shown, that ward's `progress` null |
| `count_above_expected` | the counted votes exceed the race's expected total at the top of the turnout grid | shown |
| `projection_numerics` | a band is NaN, out of order or outside 0–100%, or the ESS isn't finite | shown |

A race whose Reporting Progress fails reads `counting`, or `no_units_in` with nothing received:
never `all_units_in`. The mayor's checks read only the ward-by-ward file, and any ward-row
failure withdraws the whole mayoral projection; the Possible Range stays, as arithmetic on the
count, unless a ward's progress is hidden. A feed name not in the bundle, or a bundle name missing
from the feed, is no Withdrawal: the name shows as written (`short_label` null) and count-only
continues, but the mayor's variant is off for that refresh (`off_reason` `forecast_unmatched`).
An unreadable row or a missing race has no figures (`fault`), and a race in the feed but not in
the bundle is ignored. 2022's MonAvenir 4 (539 of 0 units, 411 votes and no candidates) keeps
its tally with `progress` null in the `council-counting-2022` golden. `withdrawals-2022` carries
one fault each for `polls_zero`, `polls_received_above_polls`, `votes_received_mismatch`,
`count_above_expected` and the mayor's `ward_votes_counted_mismatch`, and an unknown feed name;
`tests/test_checks.py` covers every check.

## What the function guarantees

- The mayor card reads only the ward-by-ward file. The all-office mayor row is never read.
- Every count is parsed from a string of digits. A count written any other way makes its race's
  row unreadable. School-board `totalVoters` are never read.
- Counts that go down are published as they are.
- Stub bands are seeded from both `seq`s and the model version.
- **Council and trustee projections** (#33): when the Night Bundle carries a level's fitted
  parameters (`projection.params`) and a race's expected-total inputs (`races[].expected`), a
  `counting` race gets the count-extension model's bands, `"stub": false`, variant `count_only`
  (`src/election_night/projection/count_extension.py`). Each candidate's band is the 5th, 50th and
  95th percentile of 10,000 draws of their final share. Each race draws from its own stream, seeded
  by both `seq`s, the model version and the race's place in the bundle. Inputs that don't add up to
  the race's `polls`, or a count no hypothesis fits, leave the race with no projection: the count
  stands. A bundle without these inputs keeps the stub bands; the 2026 bundle gains them in #46.
- **Mayor projection** (#36): the same family, read from the ward-by-ward file alone, with one unit
  per City ward (`expected.wards`, one entry per ward) summed to the citywide result, under the
  `mayor` parameters (`kappa`, `size_cv`, `tau`, `omega_city`, `omega_ward`, `omega_city_nu`;
  2023 weighted at 50%, docs/adr/0001). The turnout level is
  citywide, shared by every ward. Each draw takes one early-vote shift per candidate, applied in
  every ward with ward-level noise; a ward with no election-day unit counted is centred on the
  citywide counted shares. Inputs whose wards or per-ward units don't match the file's wards and
  their `polls` leave the mayor with no projection.
- **Mayor's forecast-weighted variant** (#41): the count-only draws, each weighted by the final
  Mayoral Forecast's density at its own final margin between the forecast's pair (S2: a Gaussian
  KDE over the forecast's leader-minus-challenger margin draws, Silverman's rule-of-thumb
  bandwidth 0.9 min(sd, IQR/1.34) n^(-1/5), exact in log space;
  `src/election_night/projection/forecast_weighted.py`). Its band is the weighted 5th, 50th and
  95th percentile (the inverse of the weighted CDF) of the same draws, so the count-only band is
  unchanged by it. The pinned draws are read once at pipeline start from the bundle's
  `forecast` pointer (`{"release_tag", "npz", "npz_sha256"}`, the npz beside the bundle): a
  missing file, a sha256 or shape mismatch, a non-finite draw, shares not summing to 1, or a pair
  not on exactly one mayoral row each turns the variant off for the night without failing the
  start.
- A pair is rejected (`UnreadableFile`) only when a file is not JSON or misses a structural key:
  `seq`, `office`, the ward or candidate arrays. A response status other than 200 or 304 is
  rejected by `check_status` before the body is read.

Golden payloads for each reachable state are in `goldens/payload/`, emitted by
`uv run election-night goldens` from the real City files in `tests/fixtures/feed/` and, for
`replay-counting-2022`, from a short Replay of the certified 2022 counts (#28), with council and
trustee projected by the model fitted without 2022 (#33). Replay payloads
key candidates by the workbooks' Ballot Names (`Tory John`) and carry no registry fields.
