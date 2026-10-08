# The payload, schema version 1

The payload is the one citywide JSON file each pipeline publishes per Count Snapshot pair
(#17 § Payload). It is a pure function of the City's two files and the Night Bundle
(`election_night.payload.build_payload`): the same inputs give the same bytes. It is UTF-8,
compact, with keys in the order below. The Frontend validator pins `schema_version`; a change to
this layout bumps it.

Fields marked *v0 null* are in the layout now and filled by later tickets (#46 forecast,
#33/#36/#41 projections).

## Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `model_version` | string | The Night Bundle's model version. `"stub-v0"` while projections are stubs. |
| `forecast_release_tag` | string or null | The pinned Backend release of the final forecast. *v0 null* |
| `seq` | object | `{"all_office": int, "ward_by_ward": int}`: each file's `seq` (epoch ms). "City count as of" is the older one. |
| `election_desc` | string or null | The all-office file's `electionDesc` as written |
| `rehearsal` | bool | True when either file's `electionDesc` contains `REHEARSAL`: raise the "Rehearsal: not real results" bar |
| `state` | string | `"before_results"` while either `seq` is before the bundle's opening time, whatever the files hold; otherwise `"results"` |
| `levels` | object | Each level's projection status, below |
| `races` | array | Every race in the bundle, in ballot order: mayor, councillor 1–25, TDSB, TCDSB, Viamonde, MonAvenir |

`levels` has keys `mayor`, `council`, `trustee` (TDSB and TCDSB) and `french_trustee`. Each is
`{"projection": status}`, and mayor also has `"variant"` for the forecast-weighted variant.
Statuses: `"stub"` (deterministic stub bands, not a projection) and `"none"` (the level never has
one). Later tickets add the gated statuses.

## Race

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `mayor`, `councillor-N`, `tdsb-N`, `tcdsb-N`, `viamonde-N`, `monavenir-N` |
| `level` | string | `mayor`, `council`, `trustee` or `french_trustee` |
| `num` | string | The feed's `num`: `"0"` for mayor, else the ward or area number |
| `name` | string or null | The ward's name; null for school-board areas |
| `state` | string | Below |
| `progress` | object or null | Reporting Progress, `{"received": int, "total": int}` (the feed's `pollsReceived` and `polls`). Null before results or with no figures. |
| `candidates` | array | Below. Before results: the bundle's candidates in ballot order, without votes. Otherwise the feed's candidates by votes, descending, ties in ballot order. |
| `projection` | object or null | `{"stub": bool, "bands": {variant: {key: {"low", "mid", "high"}}}}`, shares in percent. Present only while the race is `counting` at a projected level. Mayor has `count_only` and `forecast_weighted`; council and trustee have `count_only`. |
| `withdrawal` | object or null | A Withdrawal: `{"reason": string}`, the machine reason a check withheld the race's projection while its Live Tally stands. Always null in v0; the per-race checks (#43) fill it. Readers never see the reason. |
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
`progress`, `votes_counted` and `votes` are null.

Until the per-race checks (#43) land, a row the City publishes with impossible figures shows as
published: the `council-counting-2022` golden carries MonAvenir 4 at 539 of 0 units.

## What the function guarantees

- The mayor card reads only the ward-by-ward file. The all-office mayor row is never read.
- Every count is parsed from a string of digits. A count written any other way makes its race's
  row unreadable. School-board `totalVoters` are never read.
- Counts that go down are published as they are.
- Stub bands are seeded from both `seq`s and the model version.
- A pair is rejected (`UnreadableFile`) only when a file is not JSON or misses a structural key:
  `seq`, `office`, the ward or candidate arrays. A response status other than 200 or 304 is
  rejected by `check_status` before the body is read.

Golden payloads for each reachable state are in `goldens/payload/`, emitted by
`uv run election-night goldens` from the real City files in `tests/fixtures/feed/`.
