# Historical counts for the Election-Night Projection replays

**Research date:** 2026-10-05 · **Ticket:** [#4](https://github.com/alexwolson/toronto-election-live-projection/issues/4) · **Status:** findings only. This note decides nothing.

**Question.** Which historical poll-by-poll counts can the replays use for mayor, councillor, TDSB and
TCDSB in 2014, 2018, 2022 and the 2023 mayoral by-election? It covers file locations, coverage, how
special subdivisions are coded, polls per ward against the 2026 feed, ward comparability, joins to
canonical identities, defects, and how many independent races each level gets.

**Labels.** **OBSERVED** means I computed or read it from the cited file. **INFERRED** means I
reasoned it from observed figures. Every source was read only. The parsing scripts are throwaway
files in the session scratchpad (`…/scratchpad/r03/parse_all.py` and others) and are not part of
any repo.

**Path shorthands**

- `RES` = `~/code/personal/toronto-election-results`
- `CAN` = `toronto-election-poll-tracker-backend/data/raw/canonical/election_results.csv` (the vendored canonical)
- `FEED` = the zeroed 2026 test files `unofficialresult.json` and `unofficialresult-wardbyward.json` in the session scratchpad

---

## Bottom line

| Level | Independent races, 2014–2023 | Without 2014 | Races decided by under 5 pts (all / no 2014) | Election nights (clusters) |
|---|---:|---:|---:|---:|
| Mayor | **4** (2014, 2018, 2022, 2023 by-election) | **3** | 1 / 1 (2023: 4.7 pts; 2014 was 6.5 pts) | 4 / 3 |
| Council | **94** (44 + 25 + 25) | **50** | 12 / 7 | 3 / 2 |
| Trustee (TDSB + TCDSB) | **102** ((22 + 12) × 3) | **68** | 15 / 10 | 3 / 2 |

All figures are OBSERVED from the parsed workbooks (`races.py`). No council, TDSB or TCDSB race in
these years was acclaimed or uncontested. Six council by-elections also have poll-by-poll files in
`RES/data/raw/byelection/` (2016 W2, 2017 W42, 2021 W22, 2023 W20, 2024 W15, 2025 W25). They would
add 6 races, or 4 without the 44-ward era. They are not counted above.

**Caveat on "independent" (INFERRED).** Races on the same night share a composite ballot, the same
subdivisions, the same reporting process and the same citywide swing. Their projection errors will
be correlated. The effective sample for any pass/fail gate is therefore much closer to the number
of election nights (3 or 4) than to the race count. Gates should be scored clustered by election.

---

## 1. File locations and formats

| Year | Office | File (sheet layout) | Name format |
|---|---|---|---|
| 2014 | Mayor / Councillor / TDSB / TCDSB | `RES/data/interim/results/2014/{MAYOR, COUNCILLOR, TORONTO DISTRICT SCHOOL BOARD, TORONTO CATHOLIC DISTRICT SCHOOL BOARD}.xls`. Legacy `.xls` (needs `xlrd`). One sheet per ward (`Ward1`…`Ward44`). Trustee sheets hold one block per City ward, each with its own `Subdivision` header. | `SURNAME GIVEN` |
| 2018 | same four | `RES/data/interim/results/2018/2018_Toronto_Poll_By_Poll_{Mayor, Councillor, Toronto_District_School_Board, Toronto_Catholic_District_School_Board}.xlsx`, plus a `Notice` sheet in each | `Surname Given` |
| 2022 | same four | `RES/data/interim/results/2022/2022_Toronto_Poll_By_Poll_{Mayor, Councillor, Toronto_District_School_Board, Toronto_Catholic_District_School_Board, All_Offices}.xlsx` and `Readme.txt` | `Surname Given` |
| 2023 | Mayor (by-election) | `RES/data/raw/byelection/2023_office_of_the_mayor.xlsx`. Has a `Read Me` sheet plus `Ward 1`…`Ward 25`. | `Surname Given` |

Supporting sources:

- **Voter statistics:** `RES/data/raw/voter_stats/` (`2014-voter-statistics.xls`, `2018-voter-statistics.zip`, `2022_voter_turnout_statistics_final.xlsx`, `2023-mayoral-by-election-voter-statistics-1.xlsx`).
- **Subdivision polygons:** `RES/data/raw/subdivisions/voting-subdivisions-{2014,2018,2022,2023}-4326.geojson`.
- **Trustee crosswalk:** `RES/data/reference/trustee_ward_crosswalks.csv`.

All observations below are OBSERVED unless labelled otherwise.

- Every sheet has the same shape: candidates in rows, subdivision codes as numeric column headers, then a trailing `Total` column.
- Every block ends in a ward totals row: `Ward N Totals` in 2014, `City Ward N Totals` from 2018 on.
- The `RES/data/interim/results/<year>/` files are byte-identical (md5) to `RES/data/raw/results/extracted/<year>/` for 2014, 2018 and 2022.
- The 2022 zip entries are dated 2022-10-27, the certification date (`unzip -l RES/data/raw/results/2022-results.zip`).
- `2022_…_All_Offices.xlsx` repeats the four single-office files. All 73,729 (ward × subdivision × candidate) cells are identical, so it adds nothing.
- **No workbook carries a timestamp or a reporting order.** They hold final per-subdivision counts only.

## 2. Coverage

Parsed with `parse_all.py`. Every candidate row is summed per subdivision and checked against the
block's totals row. All 21,859 block × subdivision cells reconcile exactly, and every row's `Total`
cell equals the sum of its subdivisions (OBSERVED).

| Year | Office | Contests | Candidacies | Regular subdivisions | Special units (≥96) | Valid votes |
|---|---|---:|---:|---:|---:|---:|
| 2014 | Mayor | 1 | 65 | 1,679 | 88 | 981,054 |
| 2014 | Councillor | 44 | 358 | 1,679 | 88 | 931,336 |
| 2014 | TDSB | 22 | 127 | 1,679 | 88 | 661,731 |
| 2014 | TCDSB | 12 | 42 | 1,679 | 88 | 172,323 |
| 2018 | Mayor | 1 | 35 | 1,700 | 100 | 755,493 |
| 2018 | Councillor | 25 | 242 | 1,700 | 100 | 749,427 |
| 2018 | TDSB | 22 | 156 | 1,700 | 100 | 534,447 |
| 2018 | TCDSB | 12 | 53 | 1,700 | 100 | 126,296 |
| 2022 | Mayor | 1 | 31 | 1,460 | 75 | 551,890 |
| 2022 | Councillor | 25 | 163 | 1,460 | 75 | 539,312 |
| 2022 | TDSB | 22 | 129 | 1,460 | 75 | 393,430 |
| 2022 | TCDSB | 12 | 40 | 1,460 | 75 | 90,584 |
| 2023 | Mayor (by-election) | 1 | 102 | 1,351 | 100 | 724,638 |

Further coverage facts:

- **Same units for every office (OBSERVED).** In every City ward, the councillor, TDSB and TCDSB blocks carry exactly the same set of subdivision codes as the mayor sheet: 44/44 wards in 2014 and 25/25 in 2018 and 2022.
- **Trustee wards are whole City wards (OBSERVED).** In 2014, 2018 and 2022, every TDSB and TCDSB trustee ward is an exact union of whole City wards. No City ward is split, and the membership matches `trustee_ward_crosswalks.csv` exactly.
- **2023 total matches the City (OBSERVED).** The 2023 total of 724,638 equals the certified candidate sum quoted in `toronto-election-poll-tracker-backend/docs/research/advance-voting-and-forecast-target.md`.
- **Zero-vote units (OBSERVED).** A few subdivisions have zero votes in trustee races: 37 in 2014 TCDSB and 65 in 2022 TCDSB. The mayor and council files have almost none (0–2 per year).

Regular subdivisions per race (min / median / max) for council and trustee, OBSERVED (`races.csv`):

| | 2014 | 2018 | 2022 | 2026 feed `polls` |
|---|---|---|---|---|
| Council | 18 / 35.5 / 85 | 51 / 65 / 95 | 35 / 56 / 91 | 37 / 56 / 82 |
| TDSB | 45 / 72.5 / 148 | 51 / 64.5 / 178 | 35 / 55 / 161 | 86 / 112.5 / 208 |
| TCDSB | 54 / 115.5 / 332 | 52 / 111.5 / 346 | 44 / 87 / 313 | 45 / 86.5 / 288 |

## 3. Special subdivision codes, by year

Codes 90–95 in the 2018, 2022 and 2023 files are ordinary geographic subdivisions in the two
largest wards, not special units. Each has a polygon in that year's geojson (`AREA_LONG_CODE`;
2018 sub max = 95), and the 2022 polygons cover every code below 96 (OBSERVED). Special units are
codes 96–99 only. Each special code appears **once per ward**, as a ward-wide aggregate.

| Year | Code | Meaning | Evidence | Label |
|---|---|---|---|---|
| 2014 | 99 (all 44 wards) | Advance vote | Voter statistics give 156,942 voters in 99 (`RES/data/raw/voter_stats/2014-voter-statistics.xls`, `Sub`, `Number Voted`). It carries 15.9% of mayoral votes. | OBSERVED figures; meaning INFERRED |
| 2014 | 97 (all 44 wards) | Probably a second advance channel, such as vote-anywhere | 4,231 voters. 97 + 99 = 161,173, against the City's 2014 advance figure of 161,147 (`backend/docs/research/advance-voting-and-forecast-target.md`). Its mayor-valid/voted ratio (0.9955) equals 99's (0.9954). Neither the 2014 zip nor the voter statistics carry a readme or building names. No 98. Mail voting did not exist. | INFERRED |
| 2018 | 97, 98, 99 | Advance vote | `2018_Voter_Turnout_Statistics_FINAL.XLSX` (inside `RES/data/raw/voter_stats/2018-voter-statistics.zip`), sheet `Notes`: "Advance Vote locations are assigned subdivision #97, 98 & 99". `elections-voter-statistics-readme.xlsx` says the same. In the voter statistics, 97's `Building Name` is "Toronto City Hall - Vote Anywhere" in all 25 wards. 97 + 98 + 99 = 8,830 + 62,577 + 52,892 = **124,299**, exactly the City's 2018 advance figure. | OBSERVED |
| 2018 | 96 (all 25 wards) | Second reporting unit of the City Hall vote-anywhere location | It is in the results workbooks (0.60% of mayoral votes) but has **no row** in the 2018 voter statistics. Per ward, results (96 + 97) ÷ voter-statistics 97 has mean 0.99 and range 0.94–1.00. 96 and 97 correlate at 0.996 across wards. | INFERRED (strong) |
| 2022 | 97 | Mail | Voter statistics readme: "Subdivision 97 for each Ward is designated for Mail In Voting". `Building Name` is "Mail in Voting". 19,926 voters, the City's mail figure. | OBSERVED |
| 2022 | 98, 99 | Advance | Same readme. 61,034 + 54,865 = 115,899, the City's final advance figure. | OBSERVED |
| 2023 | 96 | Long-term care and retirement residences | `2023_office_of_the_mayor.xlsx` `Read Me` lists **94** LTC and retirement locations "shown as subdivision 96 for each ward". Voter statistics `Building Name` is "LTC - Results". 2,606 voters. | OBSERVED |
| 2023 | 97 | Mail | Read Me and voter-statistics readme. "Vote by Mail". 28,117 voters (the City reports 28,143). | OBSERVED |
| 2023 | 98, 99 | Advance | Read Me and voter-statistics readme. 68,796 + 60,852 = 129,648 (the City reports 129,745). | OBSERVED |

The 94 LTC subdivisions still have 2023 polygons but no result column. There are exactly 94
geo-only codes in 2023 (OBSERVED), so their votes are folded into ward-level 96.

Of the council by-elections, only 2025 W25 has 96. 2021 W22, 2023 W20 and 2024 W15 have 97–99,
and 2016 W2 and 2017 W42 have only 99 (OBSERVED, `byel.py`).

**Weight of the special units (OBSERVED, mayor, per ward medians):**

| Year | One regular subdivision | One 98 or 99 unit | 97 | All special units in a ward |
|---|---|---|---|---|
| 2014 | 1.9% of ward votes | 15.8% (99) | 0.3% | 5.3% of units, 16.0% of votes (range 9.5–23.7%) |
| 2018 | 1.1% | 7.8% / 6.6% | 0.3% | 5.8% of units, 15.6% of votes |
| 2022 | 1.2% | 11.2% / 9.3% | 3.5% | 5.1% of units, **24.5%** of votes (range 16.6–31.4%) |
| 2023 | 1.4% | 9.2% / 8.5% | 3.5% | 7.1% of units, 22.6% of votes |

**The modes vote differently (OBSERVED, mayor shares by mode).**

- In 2023, Bailão led the election-day subdivisions (37.6 to Chow's 34.3). Chow won on the advance vote (46.6 vs 14.8) and the mail vote (50.8 vs 11.5).
- In 2014, Ford took 35.2 on election day but 26.5 in 99.
- In 7 of the 200 races, the election-day leader was not the final winner: 2023 mayor, council 2018 W25, 2022 W5 and W11, TDSB 2014 W17 and 2022 W18, and TCDSB 2022 W1.

## 4. Polls per ward compared with the 2026 feed

These figures come from `FEED`. Both files report **1,431** polls citywide.

- Mayor-by-ward `polls` equals Councillor `polls` in all 25 wards, and the `totalVoters` values also match (OBSERVED).
- Every trustee area's `polls` equals the sum of its member City wards' `polls` under the 2026 crosswalk, for all four boards (OBSERVED).

| Ward | Feed 2026 | 2018 regular | 2022 regular | 2022 all | 2023 regular | 2023 all |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 46 | 60 | 52 | 55 | 48 | 52 |
| 2 | 67 | 80 | 69 | 72 | 63 | 67 |
| 3 | 82 | 88 | 83 | 86 | 78 | 82 |
| 4 | 67 | 73 | 67 | 70 | 61 | 65 |
| 5 | 62 | 67 | 62 | 65 | 58 | 62 |
| 6 | 50 | 55 | 50 | 53 | 48 | 52 |
| 7 | 45 | 57 | 44 | 47 | 42 | 46 |
| 8 | 61 | 68 | 61 | 64 | 58 | 62 |
| 9 | 53 | 52 | 51 | 54 | 50 | 54 |
| 10 | 80 | 95 | 91 | 94 | 86 | 90 |
| 11 | 72 | 85 | 74 | 77 | 66 | 70 |
| 12 | 58 | 73 | 61 | 64 | 57 | 61 |
| 13 | 78 | 93 | 87 | 90 | 84 | 88 |
| 14 | 48 | 53 | 49 | 52 | 42 | 46 |
| 15 | 49 | 56 | 52 | 55 | 49 | 53 |
| 16 | 62 | 67 | 59 | 62 | 55 | 59 |
| 17 | 60 | 76 | 58 | 61 | 52 | 56 |
| 18 | 56 | 87 | 56 | 59 | 52 | 56 |
| 19 | 53 | 63 | 54 | 57 | 48 | 52 |
| 20 | 61 | 64 | 58 | 61 | 52 | 56 |
| 21 | 49 | 65 | 47 | 50 | 42 | 46 |
| 22 | 47 | 64 | 47 | 50 | 44 | 48 |
| 23 | 37 | 51 | 35 | 38 | 33 | 37 |
| 24 | 48 | 55 | 48 | 51 | 43 | 47 |
| 25 | 40 | 53 | 45 | 48 | 40 | 44 |
| **Total** | **1,431** | **1,700** | **1,460** | **1,535** | **1,351** | **1,451** |

"Regular" means codes below 96. "All" adds the special units. Feed minus history per ward: against
2022 regular, mean −1.2 (range −11 to +3); against 2023 all, mean −0.8 (range −10 to +5). The
correlations are 0.97 and 0.96 (OBSERVED, `perward.py`).

**Does the feed's `polls` include advance and mail units?** INFERRED: **the counts cannot tell.**

- 1,431 is within 2% of two different readings: "geographic subdivisions only", like 2022's 1,460, and "geographic plus 4 special units per ward", like 2023's 1,451.
- If 3 specials per ward (97–99) were included, 2026 would have 1,356 geographic subdivisions. That is close to 2023's 1,351 and continues the 1,700 → 1,460 → 1,351 decline.
- The City's own 2018 notice speaks of "10 out of 1700 voting subdivisions" (`Notice` sheet of every 2018 workbook). 1,700 is the count of regular units only, so in 2018 the City used "voting subdivisions" to exclude the advance units (OBSERVED).
- Against that, the voter-statistics files list 96–99 as ordinary `Sub` rows (OBSERVED). The spec defines `polls` as "Total number of subdivisions in this ward", which does not settle it.
- No 2026 voting-subdivision dataset is published. A live CKAN `package_show?id=elections-subdivisions` on 2026-10-05 lists 2006–2023 only (OBSERVED).

This should be settled from the 2026-09-28 live test or the City ([#2](https://github.com/alexwolson/toronto-election-live-projection/issues/2)). It matters a great
deal: one advance unit carries 8–16% of a ward's votes, so `pollsReceived / polls` can understate
or overstate vote progress badly.

**Feed defect (OBSERVED).** In the zeroed test file, every trustee area's `totalVoters` equals the
`totalVoters` of the City ward with the same number. For example, TDSB 1, which covers City wards
1 and 7, shows 78,411, the figure for City ward 1 alone. It is never the area's sum, except for
TCDSB 1 and 2, which are single wards. This holds for all four boards and should be passed to
tickets 01 and 08.

## 5. Ward comparability with 2026

- **Council.** 2014 used the 44-ward map. 2018, 2022 and 2026 use the 25-ward map. The canonical gives all three years the same 25 `district_id`s (`RES/data/out/contests.csv`, OBSERVED). That the boundaries are physically identical is the canonical's assertion, which I did not check geometrically (INFERRED). The numbering is not comparable across 2014 and 2018 (`RES/docs/adr/0001-raw-wards-no-reprojection.md`).
- **2014 cannot be cleanly remapped to 25 wards.** 560 of the 1,767 subdivision codes in 2014 have no polygon: 88 special units plus 472 regular ones, probably institutional. 2018 has 619 such codes (103 special, 516 regular). From 2022 every regular code has a polygon (OBSERVED, `geo2.py`). The backend's defeatability crosswalk handles this for electorates with raking plus area weighting (`backend/research/defeatability-index/docs/adr/0002-2018-cross-era-electorate-crosswalk.md`). It is lossy for votes. INFERRED: replay 2014 on its own 44 wards rather than reprojecting it.
- **Mayor-by-ward.** Every year has mayoral results per ward sheet: 44 units in 2014 and 25 from 2018. These match the feed's live mayor-by-ward unit from 2018 on (OBSERVED).
- **Trustees.** TCDSB's 12-ward map is identical in 2018, 2022 and 2026 (OBSERVED, crosswalk). **TDSB changes from 22 wards to 12 in 2026.** In 2018 and 2022, 19 of 22 TDSB wards were single City wards and 3 covered two. In 2026 each ward is 2–3 City wards (OBSERVED, crosswalk). This is confirmed by `RES/docs/research/2026-trustee-map-boundary-verification.md` and the feed's 12 TDSB areas. 2026 TDSB races will therefore be about twice the historical size (median 112.5 polls against 55 in 2022), with more candidates per race (77 candidates across 12 areas).
- **2026 acclamations.** Two TCDSB areas (6 and 12) and two Viamonde areas (2 and 4) appear in the feed with a single candidate. The upstream canonical records these four as `acclamation`/`final`, leaving 10 TCDSB contests and 1 Viamonde contest pending (`RES/data/out/contests.csv`). Both OBSERVED.

## 6. Joins to canonical identities

The workbook candidate names were joined to `CAN` `candidate_name_raw` within each contest
(`join.py`):

- **100% of workbook candidate rows join on the exact raw string** for every year and office, and every candidate's summed votes equal the canonical `votes` (OBSERVED). Mayor and councillor contests key on `official_district_id` (`ward-N`), trustees on the trustee-ward number. The canonical's own trustee and municipal adapters read these same workbooks (`RES/src/toronto_election_results/trustees.py`, `parse_results.py`), so the agreement is expected rather than independent.
- **Share of candidacies with a `person_id`** (OBSERVED):

  | | 2014 | 2018 | 2022 | 2023 |
  |---|---|---|---|---|
  | Mayor | 0.89 | 0.74 | 0.87 | 0.84 |
  | Council | 0.90 | 0.80 | 0.87 | — |
  | TDSB | 0.94 | 0.81 | 0.81 | — |
  | TCDSB | 0.95 | 0.85 | 0.78 | — |

  Among each race's top two finishers the share is 0.83–1.00. Every elected candidate has one except the 2022 TDSB Ward 1 winner (Hastings Dennis).
- **The vendored `CAN` has 5,488 rows, all `final`.** It omits the 243 pending 2026 candidacies that the upstream `RES/data/out/election_results.csv` carries (OBSERVED).
- **The three sources format names three ways.** Historical workbooks use `Chow Olivia` (2014: `CHOW OLIVIA`). Upstream canonical pending rows use `Chow, Olivia`. The feed uses `Olivia Chow` (OBSERVED). So feed-to-identity mapping is a separate problem (the map's "Not yet specified" item). Replays do not need it, because they stay inside one workbook.

## 7. Gaps and known defects

All OBSERVED unless marked.

1. **Totals rows.** Every block ends in a `(City) Ward N Totals` row. A parser that does not match rows to candidate names will double-count. Excluding rows that contain "total" reconciles exactly, and no candidate name contains "total".
2. **2018 poll-level correction.** The 2018 `Notice` sheet (dated 2018-11-30) says tabulators at 10 subdivisions reported to the wrong subdivision on election night: Ward 4 subs 23, 26, 27, 28; Ward 14 subs 1, 3, 26, 27; Ward 24 subs 13, 14. The files carry the corrected allocation. Ward and race totals are unaffected.
3. **2018 code 96 is undocumented.** It has no voter-statistics row and no readme mention. Treat it as part of the City Hall vote-anywhere advance channel (INFERRED, §3).
4. **2014 code 97 is undocumented.** There is no readme and there are no building names (INFERRED meaning, §3).
5. **Subdivision numbers have gaps.** For example, 2022 Ward 1 has no sub 4. Count the columns, never the maximum code.
6. **2023 LTC folding.** The 94 LTC subdivisions report only through ward-level 96.
7. **Mail exists only from 2022.** 2014 and 2018 have no mail channel, and 2022 has no LTC channel. The set of special units differs every year (2, 4, 3 and 4 per ward).
8. **No reporting order or timestamps** in any workbook. Arrival order on the night must come from elsewhere (ticket 02) or be simulated.
9. **Format drift.** 2014 needs `xlrd`. Some years have `Notice` or `Read Me` sheets. 2014 trustee sheets stack City-ward blocks. openpyxl warns about headers and footers on the 2023 file, which is harmless.
10. **Polygons are missing** for 472 (2014) and 516 (2018) regular subdivisions (§5).

## 8. Adversarial notes for the qualification-gate ticket (INFERRED)

- **Mayor races are too few for a statistical gate.** Two of the 3–4 races were landslides: 2018 by 39.9 pts and 2022 by 44.2 pts. Only 2023 (4.7) and 2014 (6.5) are close. A mayor gate will turn on one or two nights.
- **Council and trustee pass rates will be inflated by easy races.** The median winning margin is 11–39 pts by year. A large pass rate can come from landslides. Report results separately for the close races (12 council and 15 trustee under 5 pts, 7 and 10 without 2014).
- **2014 differs structurally from 2026.** It has 44 smaller wards (median 35.5 polls), no mail, two special codes, and the 22-ward TDSB. Including it nearly doubles the council and trustee races. Excluding it leaves 2 nights for those levels.
- **Mode composition shifts between years.** Special units were 16% of the vote in 2014 and 2018 and 22–25% in 2022 and 2023, and they lean in different directions (§3). A replay that reveals subdivisions in random order will not reproduce a night where advance units arrive as a block. The reveal order is a modelling assumption that must be pre-registered alongside the pass criteria.

## Unknown / gaps

- **Whether 2026 `polls` counts the special units.** The counts do not settle it (§4). This is ticket 01.
- **Whether 2026 will use code 96 for long-term care.** It was used in 2023 and 2025 W25, but not in the 2022 general election.
- **When the special units are reported on the night**, whether first, last or interleaved, and how they enter `pollsReceived`. This is tickets 01 and 02.
- **The meaning of 2014 code 97 and 2018 code 96.** Both are INFERRED from sums. City election reports would confirm them.
- **Geometric identity of the 25-ward boundaries from 2018 to 2026.** This rests on the canonical's district identity. I did not verify it.
- **Council by-elections** (6 races) were inspected for structure only. I did not check their coverage or canonical joins.
