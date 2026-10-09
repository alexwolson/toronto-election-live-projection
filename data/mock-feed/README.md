# Mock Feed inputs

What the Mock Feed scenario (`election_night.mockfeed.scenario`, #34) reads besides the City's 2026
test files and the vendored historical workbooks.

| File | From | Kept |
|---|---|---|
| `trustee_wards_2026.csv` | `data/reference/trustee_ward_crosswalks.csv` in [toronto-election-results](https://github.com/alexwolson/toronto-election-results) at `385bef19078be0a32763dfd75f3e4c1867adf50f`, itself from the City's [2026 school-board ward reference chart](https://www.toronto.ca/wp-content/uploads/2026/04/9600-2026-School-board-ward-reference-chart.pdf) (2026-04-23) | The header and the 30 rows whose `boundary_regime` ends `-trustee-wards-2026`, unchanged |

Each row names one 2026 trustee area (`office_code`, `ward_id`) and its member City wards
(`city_wards`, `;`-separated). Every area is a union of whole City wards, and its member wards'
`polls` sum to the area's `polls` in the zeroed test file (research 03 § 4, OBSERVED).
