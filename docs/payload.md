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
one). Later tickets add the gated statuses (#45). Until then council and trustee keep `"stub"`
here even when their races carry the model's bands; the race's own `projection.stub` says which.
Mayor likewise keeps `"variant": "stub"` until #41, while a modelled mayor race carries only
`count_only` bands.

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
| `projection` | object or null | `{"stub": bool, "bands": {variant: {key: {"low", "mid", "high"}}}}`, shares in percent. Present only while the race is `counting` at a projected level. Stub mayor bands have `count_only` and `forecast_weighted`; a modelled mayor has `count_only` until #41 adds `forecast_weighted`. Council and trustee have `count_only`. |
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
- A pair is rejected (`UnreadableFile`) only when a file is not JSON or misses a structural key:
  `seq`, `office`, the ward or candidate arrays. A response status other than 200 or 304 is
  rejected by `check_status` before the body is read.

Golden payloads for each reachable state are in `goldens/payload/`, emitted by
`uv run election-night goldens` from the real City files in `tests/fixtures/feed/` and, for
`replay-counting-2022`, from a short Replay of the certified 2022 counts (#28), with council and
trustee projected by the model fitted without 2022 (#33). Replay payloads
key candidates by the workbooks' Ballot Names (`Tory John`) and carry no registry fields.
