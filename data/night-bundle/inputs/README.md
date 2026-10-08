# Night Bundle name inputs

What the bundle build names the 2026 candidates from (#16, #27). Written by

```bash
uv run election-night name-inputs --backend-release <the pinned forecast's Backend release>
```

and read by `uv run election-night bundle`. `sources.json` records where each file came from and
when.

| File | From | Kept |
|---|---|---|
| `registry/*.json` | The City registry: `https://www.toronto.ca/data/elections/candidate_list/{mayor,councilor,trustee}Candidates_2026.json` | Its layout, `seq`, and each candidate's `name`, `office`, `status`, `firstName`, `lastName`. Contact fields are dropped. `sources.json` has each original's `seq` and sha256. |
| `canonical-2026.csv` | `election_results.csv` in the Results release the forecast was built from (the Backend release manifest's `dependencies.results`) | The 2026-10-26 municipal rows: `candidacy_id`, `person_id`, office, district and `candidate_name`. `sources.json` has the full asset's sha256. |
| `mayoral_forecast_draws.json` | The pinned Backend release | As published: the forecast's named mayoral `candidate_id`s. |

The build fails unless, in every race, the City test file's names, the registry's Ballot Names
(`firstName lastName`) and the canonical's `candidate_name`s match one to one, and unless each
forecast `candidate_id` sits on exactly one mayoral row by `person_id` or `candidacy_id`.

`name-inputs` refetches all of these. Names are never refreshed by the forecast-only release
(#16), so that release's procedure must not rerun it for the registry.
