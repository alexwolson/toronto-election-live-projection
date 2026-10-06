# Joining feed candidate names to people and display names

**Research date:** 2026-10-06 · **Ticket:** [#14](https://github.com/alexwolson/toronto-election-live-projection/issues/14) · **Status:** findings only. This note decides nothing.

**Question.** Can every candidate name in the City's 2026 zeroed test files join to exactly one 2026
candidacy in the upstream canonical dataset, and from there to a `person_id` and a display name? It
covers per-office match counts in both directions, what normalisation a name join must handle,
where display names could come from, and how a late change to a name or to the field would show up
on the night.

**Labels.** **OBSERVED** means I computed or read it from the cited file or page. **INFERRED** means
I reasoned it from observed facts. Every source was read only. The scripts are throwaway files in
the session scratchpad (`…/scratchpad/r06/scripts/join.py` and others) and are not part of any repo.
The per-candidate table is [`06-feed-name-joins.csv`](06-feed-name-joins.csv) (one row per feed
candidate).

"Withdrawal" in `CONTEXT.md` means a projection withheld on the night. This note says
**withdrawing a nomination** for a candidate leaving the race, to keep the two apart.

**Path shorthands**

- `RES` = `~/code/personal/toronto-election-results` (the upstream canonical dataset)
- `CAN` = the canonical tables at `RES` commit `53e00fc` (`RES/data/out/` on `main`; details below)
- `FEED` = the City's zeroed test files `unofficialresult.json` and `unofficialresult-wardbyward.json`, downloaded fresh for this note
- `REG` = the City's candidate registry JSON (`mayorCandidates_2026.json`, `councilorCandidates_2026.json`, `trusteeCandidates_2026.json`), downloaded fresh for this note
- `FE` = `toronto-election-poll-tracker/` (the frontend); `FE/.release-data/` is its local copy of the published release feeds
- `BE` = `toronto-election-poll-tracker-backend/`

**Inputs as read** (all OBSERVED):

| Input | Version |
|---|---|
| `FEED` all-office | Downloaded 2026-10-06 12:15:40 UTC. 48,961 B, sha256 `f5a140e0…adf1f1e`, ETag `"293a85745e2a871b265a1259ff32de8a"`, Last-Modified Tue, 29 Sep 2026 02:04:42 GMT, `seq` 1790647481807 (2026-09-28 22:04:41.807 EDT). Same ETag as note 01's Oct 5 fetch. |
| `FEED` ward-by-ward | Same time. 294,674 B, sha256 `4e9e8fc0…88049775`, ETag `"83a35b2c5ca89cf94777647cfdb9c659"`, same Last-Modified. |
| `REG` | Downloaded 2026-10-06 12:16:52 UTC. Last-Modified Tue, 06 Oct 2026 12:04:05 GMT, `seq` 1791287580751 (2026-10-06 07:53 EDT). sha256 mayor `dc9e7495…`, councillor `93a4f658…`, trustee `4984b281…`. |
| `CAN` | `RES` `main` = `origin/main` = GitHub `main` = `53e00fc2a2401b99ccab78e271cabf9757b30601` (2026-09-30), the source commit of the latest release `results-2026-09-30.2`. Read with `git show 53e00fc:data/out/…`. The `RES` working copy is checked out on branch `add-katie-campaign-website` at `c9c6578` (4 commits behind `main`, clean). Its 2026 rows have the same 361 `candidacy_id`s, names, raw names, districts, `person_id`s and outcomes as `main`. |
| Vendored copy | `BE/data/raw/canonical/election_results.csv`: 5,488 rows, all `final`, **no 2026-10-26 rows** (its latest 2026 rows are 18 MP rows dated 2026-04-13). Not used further. |
| `FE` release feeds | `FE/.release-data/` resolved 2026-10-03: `backend-2026-10-02.3` (Backend, latest release) and `results-2026-09-30.2` (Results). File hashes match `FE/public/data/source-manifest.json`. |

---

## Bottom line

| Office | Feed names | Exact match | Only after normalisation | Ambiguous (>1) | No match | Canonical 2026 with no feed name | With `person_id` | Without `person_id` | Last word is not the surname | Hand-curated display name |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Mayor | 53 | 53 | 0 | 0 | 0 | 0 | 49 | **4** | 0 | 5 |
| Councillor (25 wards) | 190 | 190 | 0 | 0 | 0 | 0 | 134 | **56** | 7 | 0 |
| TDSB (12) | 77 | 77 | 0 | 0 | 0 | 0 | 60 | **17** | 3 | 0 |
| TCDSB (12) | 31 | 31 | 0 | 0 | 0 | 0 | 25 | **6** | 5 | 0 |
| Viamonde (3) | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| MonAvenir (2) | 6 | 6 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| **Total** | **361** | **361** | 0 | 0 | 0 | 0 | **278** | **83** | **15** | **5** |

All OBSERVED (`join.py`, `final_csv.py`).

- **Every feed name joins to exactly one 2026 candidacy, on the exact string, within its race.** No
  name needs normalisation, none is ambiguous, and no canonical 2026 candidacy lacks a feed name.
- **83 of those candidacies have no `person_id`** (4 mayor, 56 council, 17 TDSB, 6 TCDSB). A join
  that goes through `person_id` cannot reach them. All 361 have a `candidacy_id`.
- **The match is exact because all three sources copy the same City registry fields.** The feed
  name, the registry's `firstName + " " + lastName`, and the canonical `candidate_name` are the same
  string for all 361 candidates (OBSERVED). The agreement shows the sources are in sync today. It
  does not show the join would survive a change (INFERRED).
- **No source holds a curated display name beyond five mayoral candidates.** Every frontend
  `display_name` is the feed name verbatim. No feed or table holds a short label or surname field.
  The frontend derives surnames by taking the last word, which is wrong for 15 names.

---

## 1. Does each feed name match exactly one 2026 candidacy?

**Method.** Each feed race was keyed to a canonical contest: office `id` 1 with `num` `"0"` to the
mayor contest (`official_district_id` `city`); office 2 with `num` N to `ward-N`; offices 3–6 to the
TDSB, TCDSB, Viamonde and MonAvenir contests with `official_district_id` N. All 55 feed races found
their contest (OBSERVED). Within each race the feed `candidate.name` was compared with `CAN`
`candidate_name`: first byte for byte, then after successively looser normalisation (whitespace and
NFC, then case, then accents and punctuation, then the reordered raw name, then token sets).

**Results (all OBSERVED).**

- All 361 feed names equal exactly one `candidate_name` in their own contest at the first, exact
  step. No canonical candidacy is matched twice, and none is left over.
- The ward-by-ward file's 53 mayor names are identical, and in the same order, to the all-office
  mayor list.
- Feed names are also unique citywide: no name appears in two races.
- The feed equals `REG` in every one of the 55 races, both as a set and in zero-vote order. Note 01
  checked mayor and council only; this extends it to all four school boards.
- The canonical builds `candidate_name` from the registry's `firstName` and `lastName`, joined by a
  space after NFKC normalisation and whitespace collapsing (`RES/src/toronto_election_results/pending_candidates.py`, `_candidate_row`). That is why the strings agree.

**The other canonical name column does not match.** `CAN` `candidate_name_raw` is the registry's
`name` field, in `"Last, First"` form. Reordering it to `"First Last"` reproduces the feed name for
350 candidates. For the other 11, the registry's `name` field has dropped accents, apostrophes or
hyphens that its `firstName`/`lastName` fields keep (OBSERVED, `REG`):

| Race | Feed name | `candidate_name_raw` |
|---|---|---|
| Ward 1 | Ala'a Adib | Adib, Alaa |
| Ward 10 | Andi Hoàng-Lefranc | Hoang Lefranc, Andi |
| Ward 14 | Caryma Sa'd | Sad, Caryma |
| Ward 19 | Nate Erskine-Smith | Erskine Smith, Nate |
| Ward 20 | Ariel-Rachel Karokis | Karokis, Ariel Rachel |
| Ward 23 | John-Mark Oleh | Oleh, John Mark |
| Ward 25 | Kannan S'ree Jr | Sree Jr, Kannan |
| TCDSB 6 | Frank D'Amico | DAmico, Frank |
| Viamonde 3 | Jean-François L'Heureux | LHeureux, Jean Francois |
| Viamonde 3 | Anna-Karyna Ruszkowski | Ruszkowski, Anna Karyna |
| Viamonde 4 | Geneviève Oger | Oger, Genevieve |

Only one raw name equals its feed name as written: `Nisha Kumari`, the single-name candidate.

**Candidacies without a `person_id` (83, all OBSERVED from `CAN` `candidacy_person_links.csv`).**
The canonical links only confirmed identities. The 83 unlinked candidacies are the ones whose name
matches an earlier Person but whose identity has not been confirmed:

- **59 are `proposed`.** A machine name match (`exact_normalized_name_review`) is waiting for
  review. These are 4 mayor and 55 council candidacies.
- **24 are `unresolved`.** All 17 TDSB and 6 TCDSB ones were reviewed and closed for insufficient
  evidence. The remaining one is Han Dong (Ward 23), closed as `multiple_authoritative_continuity_clusters`.

They are:

- **Mayor (4):** Jamie Atkinson, Paul Collins, Joseph Osuji, Gus Prokos. None is in the forecast's named field.
- **Council (56):**
  - W1 Abraham Abbey, Joseph Martino, Kristian Santos
  - W3 Anthony Internicola, Ted Opitz
  - W4 Nadia Guerrera, Debbie King, Adam Pham, Steve Yuen
  - W5 Daniel Di Giorgio, Chiara Padovani
  - W7 Amanda Coombs
  - W8 Liz Grade, Domenico Maiolo, Daniel Trayes
  - W9 Neil Simon
  - W10 Husain Neemuchwala
  - W11 Mike Layton, Huy Lieu, Diana Yoon
  - W12 Jenny Kalimbet, Bob Murphy
  - W13 Norman MacLeod, Cleveland Marshall, Nicki Ward
  - W14 Michael Connor, Peter De Marco, Sara Ehrhardt, Mary Fragedakis, John Kladitis, Michael Mitchell, Jason Stevens, Denise Walcott
  - W15 Sheena Sharp
  - W17 Sabrina Zuniga
  - W18 Hamid Shakeri
  - W19 Nate Erskine-Smith, Kevin Morrison, Mohammad Shabani, Adam Smith, Jennie Worden
  - W20 Naser Kaid, Luigi Lisciandro, Kevin Rupasinghe
  - W21 Stella Kargiannakis, Willie Reodica
  - W22 Serge Khatchadourian, Dan Lovell, Donny Morgan
  - W23 Shaun Chen, Han Dong, Piravena Sathiyanantham
  - W25 Shawn Allen, Ashan Fernando, Zakir Patel, Dianna Robinson
- **TDSB (17):**
  - TDSB 1 Antonius Clarke
  - TDSB 5 David Gulyas, Andrew Massey, Gus Stefanis
  - TDSB 6 John Vassal
  - TDSB 7 Axel Arvizu
  - TDSB 8 Imran Khan, Christine McGirr
  - TDSB 9 Bill Wu
  - TDSB 10 Malik Ahmad, Azim Dewan, Jocelyne Poirier, Marisa Sterling
  - TDSB 11 Angus Grant, Dameon Halstead
  - TDSB 12 Darren Frake, Gary McBean
- **TCDSB (6):**
  - TCDSB 5 Gianfranco Cristiano
  - TCDSB 7 Celine DiNova
  - TCDSB 9 Rosina Bonavota, Renato Fallico
  - TCDSB 10 Sal Piccininni, Paul Salvatori

Some are well known. For example, Mike Layton's proposed match is a Person with council candidacies
in 2010, 2014 and 2018 (OBSERVED, `CAN`). Every one of the 278 linked people has
`identity_status = active`, and no `person_id` is shared by two feed names (OBSERVED).

---

## 2. What the join has to handle

### What the 2026 names contain

All OBSERVED from `FEED` (per-office lists in `join.py` output):

- **Characters.** Only letters, spaces, ASCII apostrophes (5 names) and ASCII hyphens (6 names)
  appear. There are three non-ASCII letters, `à`, `ç` and `è`, in Andi Hoàng-Lefranc, Jean-François
  L'Heureux and Geneviève Oger. All are precomposed (NFC).
- **Absent.** There are no periods, commas, quotes, parentheses, digits, initials or nicknames. There
  are no double, leading or trailing spaces. No curly apostrophes appear.
- **Format.** The feed and `candidate_name` use `"First Last"`. `REG` `name` and `candidate_name_raw`
  use `"Last, First"`. The historical certified workbooks use `"Last First"` (note 03 §6).
- **Internal capitals (16 names).** Examples: Sarah McVie, Norman MacLeod, Celine DiNova, Frank
  D'Amico, Jean-François L'Heureux.
- **Lower-case particles.** Matias de Dovitiis (TDSB 1) and Markus de Domenico (TCDSB 2).
- **Suffixes.** Dewitt Lee III (TDSB 8) and Kannan S'ree Jr (Ward 25). In both, the suffix is part
  of the registry `lastName`.
- **One single name.** Nisha Kumari (Ward 21) has a blank registry `firstName`. Her whole name is the
  `lastName`.
- **Multi-word given names (11).** Odessa Paloma Parker and Kuo Yu Tong (mayor); Diana Chan McNally
  (W4), Jethro Adir Kavod (W17), Hassan Mubarak Noor Mohamed (W17), Syeda Jaana Ali (W19) and
  Mohammad Ali Reza (W20); Amberley Ryan Henry (TDSB 1), Md Sazibul Islam (TDSB 10) and Abdul Azeem
  Mohammed (TDSB 11); Mary Cury Paul (TCDSB 8).

### Where a naive join breaks

**Surname by last word (the "Di Francesco" problem).** Taking the last word gives the wrong surname
for 15 names. The table compares that word with the registry's `lastName` (OBSERVED):

| Race | Feed name | Last word | Registry surname |
|---|---|---|---|
| W5 | Daniel Di Giorgio | Giorgio | Di Giorgio |
| W13 | Walied Khogali Ali | Ali | Khogali Ali |
| W14 | Peter De Marco | Marco | De Marco |
| W15 | Rachel Chernos Lin | Lin | Chernos Lin |
| W17 | Hassan Mubarak Noor Mohamed | Mohamed | Noor Mohamed |
| W21 | Nisha Kumari | Kumari | Nisha Kumari |
| W25 | Kannan S'ree Jr | Jr | S'ree Jr |
| TDSB 1 | Matias de Dovitiis | Dovitiis | de Dovitiis |
| TDSB 8 | Dewitt Lee III | III | Lee III |
| TDSB 9 | Carey De Pass | Pass | De Pass |
| TCDSB 1 | Jennifer Di Francesco | Francesco | Di Francesco |
| TCDSB 2 | Markus de Domenico | Domenico | de Domenico |
| TCDSB 3 | Ida Li Preti | Preti | Li Preti |
| TCDSB 3 | Susel Munoz Plasencia | Plasencia | Munoz Plasencia |
| TCDSB 10 | Stephanie Loor Ruiz | Ruiz | Loor Ruiz |

**Surname as "everything after the first word".** This rule is wrong for 12 names: the 11 with
multi-word given names, plus Nisha Kumari. Two names defeat both rules: Hassan Mubarak Noor Mohamed
and Nisha Kumari. No whitespace rule on the display string recovers every surname (OBSERVED).

- The registry's structured `lastName` is the only source that gives all 361 surnames.
- `CAN` does not publish given name and surname separately. Splitting `candidate_name_raw` at the
  comma gives the surname, but it loses characters in 6 of them: Hoang Lefranc, Sad, Erskine Smith,
  Sree Jr, DAmico and LHeureux (OBSERVED).

**Surname-only joins collide.** All OBSERVED, within one race:

- **Same surname.** Mayor: Braeden Chow and Olivia Chow; Henoke Yohannes and Leila Yohannes.
- **Hyphens turned into spaces.** Ward 19 then has Adam Smith and Nate Erskine-Smith sharing
  "Smith". Splitting on whitespace alone keeps `Erskine-Smith` as one word, so the collision only
  appears with this normalisation.
- **Surname within one edit.** Mayor: Chow and Choy (Olivia and Braeden Chow against Logan Choy),
  Gong and Tong (Edward Gong, Kuo Yu Tong), Tang and Tong (Weizhen Tang, Kuo Yu Tong). Ward 16:
  Didi Moffat and Stacey Moffatt. Ward 23: Shaun Chen and Ronald Phen.
- **Same first word.** Mayor: Laura Dean and Laura Ellis; Jack Hartley and Jack Weenen. Ward 14:
  Michael Connor and Michael Mitchell. This matters only if a label used given names.

**Full-name fuzzy matching has headroom today, but little.** The most similar pair of full names in
any race is Henoke Yohannes and Leila Yohannes (ratio 0.69, Python `difflib`, after case and accent
folding). No pair within a race reaches 0.70, and no pair across races reaches 0.85 (OBSERVED).

**Case.** Case-folding creates no collision in any race (OBSERVED). Re-capitalising does damage,
though. The canonical's historical `candidate_name` values, derived from the certified workbooks,
flatten internal capitals and mis-split multi-word surnames. Against the archived live feeds:

- `Jim Mcmillan` for the feed's `Jim McMillan` (2018 mayor)
- `Celine Dinova` for `Celine DiNova` (2022 TCDSB)
- `Preti Ida Li` for `Ida Li Preti` (2018 and 2022)
- `Ali Walied Khogali` for `Walied Khogali Ali` (2018)

All OBSERVED (`histjoin.py`, [WB-2018], [WB-2022]). The 2026 rows do not have this problem, because
they come from the structured registry fields.

**Accents, apostrophes and hyphens.**

- A join on `candidate_name` must keep them. A join on `candidate_name_raw` must fold them, for the
  11 names in §1.
- The canonical's own candidacy ledger locates a 2026 candidacy by contest plus `candidate_name_raw`,
  so its locator is the folded form (OBSERVED, `RES/src/toronto_election_results/candidacy_ledger.py`;
  ledger rows such as `"Cunningham, Ian"`).
- The Backend's council matcher keeps only `[a-z]` after lower-casing, so it would split
  `Geneviève` into `genevi` and `ve` (OBSERVED, `BE/backend/model/council_race.py` `_name_tokens`;
  INFERRED effect).

**Joining without the contest key.** Inside 2026 this is safe today, because the 361 names are
distinct. Outside 2026 it is not (all OBSERVED):

- **Against `CAN` `people.csv` `preferred_name` (case-folded).**
  - 343 names hit one row.
  - 15 also hit a `deprecated` redirect row. Olivia Chow and Chris Alexander are examples.
  - 3 hit two different active people: Thomas Hall (mayor), Kevin Morrison (W19) and Frank D'Amico
    (TCDSB 6).
- **Against every canonical candidacy of every year.** 89 feed names map to more than one identity.
  Most are an unlinked 2026 candidacy plus an older Person with the same name.
- **Against the Results release asset `person_aliases.json`.** This is the canonical's name-to-Person
  crosswalk. Its `normalized_name` is case-folded with whitespace collapsed, and keeps accents and
  punctuation (checked on all 6,541 entries).
  - It never names a different person from a confirmed link.
  - It publishes 4 feed names as ambiguous, with a null `person_id`: Thomas Hall, Ahmed Kamal (W12),
    Kevin Morrison and Frank D'Amico.
  - It returns a Person for 82 of the 83 unlinked candidacies. For 81 of them this is exactly the
    Person that the canonical's own link history proposed or reviewed and left unresolved. For Han
    Dong, the canonical recorded no target.
  - So a name lookup asserts identities the canonical has declined to confirm.
- **Stale overlays.** `toronto-election-poll-tracker-data/data/raw/candidates/challengers.csv` (last
  changed 2026-08-11) matches 90 of its 101 rows exactly. Of the other 11:
  - 2 are variants of feed names: `Andi Hoang-Lefranc` (no accent) and `Jaana Syeda Ali` (word
    order).
  - 2 names now appear in another race: Gregory Rodriguez, W17 there, is TCDSB 7 in the feed; Malik
    Ahmad, W20 there, is TDSB 10.
  - 7 are not in the feed at all, for example Dana Fisher and Gabe Blanc.

**Nicknames.** None appear in the feed. Other sources do use them. The canonical's alias curations
record Forum's "David DiGiorgio" for the registry's Daniel Di Giorgio, and "Gabe Blanc" for a Person
whose `preferred_name` is `GABRIEL BLANC` (OBSERVED, `RES/data/reference/person_alias_curations.csv`).
Gabriel Blanc is not in the 2026 field.

---

## 3. Where display names could come from

### (a) The frontend (`FE`)

| Source | What it holds | Offices | 2026 candidates covered | Equal to feed name |
|---|---|---|---|---|
| `FE/src/lib/candidates.ts` `REGISTRY` | Hand-entered `name` plus a colour `slug`, keyed by `person_id` (and legacy slugs). Unknown ids fall back to a title-cased id. | Mayor | **5**: Olivia Chow (`chow`), Brad Bradford (`bradford`), Chris Alexander (`alexander`), Sarah McVie (`mcvie`), Odessa Paloma Parker (`parker`) | 5 / 5 |
| `FE/src/lib/mayoral-forecast.ts` `surnameOf` | Short label computed as the last whitespace word. Used in the forecast hero and the uncertainty labels. | Mayor (forecast views) | Computed, not stored | — |
| `mayoral_candidates.json` (Results release) | `display_name`, `person_id`, `candidacy_id`, sorted by surname | Mayor | 53 | 53 / 53 |
| `council_race_cards.json` (Backend release) | `display_name`, `candidate_id`, `candidacy_id` | Council | 190 | 190 / 190 |
| `trustee_race_cards.json` (Backend release) | `display_name`, `person_id`, `candidacy_id`; the board-level `short_name` is a board label, not a candidate label | TDSB 77, TCDSB 31, Viamonde 4, MonAvenir 6 | 118 | 118 / 118 |
| `mayoral_forecast.json` (Backend release) | `candidate_id` (a `person_id`) and `display_name` for 3 named candidates, plus 2 `named_in_polls`; a residual pool of 50 | Mayor | 5 | 5 / 5 |

All OBSERVED. The feeds reach the frontend through GitHub releases resolved into the gitignored
`FE/.release-data/` (`FE/src/lib/feed-source.ts`). `FE/fixtures/` and `FE/fixtures-preview/` are dev
copies (`FE/fixtures/README.md`).

Trustees are covered by `trustee_race_cards.json`. But every `display_name` there, as in the other
feeds, is the canonical `candidate_name` copied through:

- Council: `BE/backend/model/council_race.py` `load_registered_field`.
- Trustees: built from Results' certified trustee artifact (`FE/fixtures/README.md`).

**So the frontend adds curation for five mayoral candidates only.** No feed carries a candidate
short label (OBSERVED).

One more divergence (OBSERVED): `council_race_cards.json` gives a person id to 37 of the 56 unlinked
council candidacies. In all 37 it is the canonical's still-unconfirmed `proposed` target, found by
the Backend's own name-token match. For those candidates, "the person id" differs between `CAN` and
the council cards.

**How the final mayoral forecast names candidates (OBSERVED).**

- **Hard-coded names.** The Backend hard-codes them: `CURRENT_FIELD` = Olivia Chow, Brad Bradford,
  Chris Alexander, and `EXTRA_2026` = Sarah McVie, Odessa Paloma Parker
  (`BE/backend/model/compact_mayoral/readings.py`).
- **Ids by name match.** It resolves each to an id by matching the names against the Results
  `mayoral_candidates.json` `display_name`, with case-folding and hyphens turned into spaces
  (`_normalize`). The id is `person_id`, falling back to `candidacy_id` when a candidacy is unlinked
  (`certified_candidates`).
- **Current release.** In `backend-2026-10-02.3` all five ids are `person_id`s. All five feed names
  join exactly to candidacies carrying those ids.
- **Residual pool.** The other 48 mayoral candidates sit in the pool (`candidate_count` 50 includes
  McVie and Parker) and are not listed by id.

### (b) The canonical (`CAN`)

- **`people.csv`.** Its columns are `person_id`, `preferred_name`, `identity_status`,
  `redirect_to_person_id` and `created_release`. `preferred_name` is the only display-like field.
  For all 278 linked 2026 candidates it equals the feed name exactly. The 83 unlinked have none.
- **`election_results.csv`.** It carries `candidate_name` (equal to the feed name) and
  `candidate_name_raw` (the folded `"Last, First"`). It has no short, preferred or surname column.
- **`person_aliases.json`.** This release asset maps names to persons, not to display strings.

All OBSERVED.

### (c) A new curated column

What it would have to cover, per office (OBSERVED counts):

| Office | Feed names | Have any `display_name` today (all = feed name) | Hand-curated name today | Need a curated entry if every name gets one | Stored short label today | Last word ≠ surname | After-first-word ≠ surname | No `person_id` (unreachable by a `person_id` key) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Mayor | 53 | 53 | 5 | 48 | 0 | 0 | 2 | 4 |
| Councillor | 190 | 190 | 0 | 190 | 0 | 7 | 6 | 56 |
| TDSB | 77 | 77 | 0 | 77 | 0 | 3 | 3 | 17 |
| TCDSB | 31 | 31 | 0 | 31 | 0 | 5 | 1 | 6 |
| Viamonde | 4 | 4 | 0 | 4 | 0 | 0 | 0 | 0 |
| MonAvenir | 6 | 6 | 0 | 6 | 0 | 0 | 0 | 0 |
| **Total** | **361** | **361** | **5** | **356** | **0** | **15** | **12** | **83** |

A table keyed by `candidacy_id` reaches all 361. One keyed by `person_id` reaches 278 (INFERRED from
the counts above).

---

## 4. How late changes would show up

### Withdrawing a nomination

The deadline was Aug 21, 2026 at 2 p.m. Primary sources (all OBSERVED):

- [CAND] (modified Sept 2, 2026): file the "Withdrawal of Nomination form in-person on or before
  August 21, 2026 at 2 p.m. Candidates cannot withdraw after the nomination period has closed."
- [NOM] (Aug 20, 2026): "The deadline to file or withdraw a nomination … is tomorrow, Friday,
  August 21 at 2 p.m."
- [BAC] slide 17: "Candidates have until 2:00 p.m. on August 21, 2026 to withdraw their nomination
  such that their name will not appear on the ballot."

The data agree. `REG` on Oct 6 lists 361 candidates, all `Active`, with `dateNomination` from
01-May-2026 to 21-Aug-2026, and they match the feed exactly (OBSERVED). A candidate who stops
campaigning now stays on the ballot and in the feed (INFERRED).

### A candidate who dies after nomination day

There is a precedent. On Oct 21, 2022, the City announced that Ward 23 councillor-candidate Cynthia
Lai had died. "The ballots for election day have already been printed and cannot be changed". Votes
for her "will not be counted", and the election continued, under s. 39(a) of the Municipal
Elections Act (OBSERVED, [LAI]).

How it showed up:

- On the night, the live feed kept her with `votesReceived` `"0"` and `percentage` `"0.00"`, while
  Ward 23 had 10,369 votes at 21:46 (OBSERVED, [WB-2022]).
- The certified 2022 workbook lists only the other three candidates.
- `CAN` has no 2022 row for her (OBSERVED, `RES/data/interim/results/2022/2022_Toronto_Poll_By_Poll_Councillor.xlsx`, sheet `Ward 23`).

So the precedent shape is a feed name that stays at zero all night and has no certified candidacy
afterwards. Until a refresh, the 2026 canonical would still hold the pending candidacy (INFERRED).

### Ballot name and legal name

The nomination paper asks for the "Name as it is to appear on the ballot paper: (subject to the
agreement of the City Clerk)". It has First Name and Last Name boxes, or a Single Name for people
with a legally registered single name. The declaration of qualification carries the name separately
(OBSERVED, [NOMPAPER]).

The registry's `firstName`/`lastName` look like those ballot-name boxes. For example, Nisha Kumari's
blank `firstName` fits the Single Name box (INFERRED). The feed carries the same strings (OBSERVED).
So a gap between a legal name and a ballot name would not show up as a join failure. Both the feed
and the canonical would carry the ballot name (INFERRED).

### Name corrections and field changes

- **The registry is regenerated.** Note 01 saw registry `seq` 2026-10-05 17:38 UTC. Today's file is
  `seq` 2026-10-06 11:53 UTC with Last-Modified 12:04 GMT (OBSERVED). The cadence is not documented.
- **No change between Sept 28 and Oct 6.** The test feed (`seq` Sept 28), the canonical snapshot
  (Sept 30) and `REG` (Oct 6) hold the same 361 names (OBSERVED).
- **The feed has no candidate key.** The spec's candidate structure is `name`, `votesReceived` and
  `percentage` only. The ward-by-ward file adds `ward[]` (OBSERVED, [SPEC] pp. 6, 8).
  - A corrected spelling would show up as a feed name that matches no candidacy in its race, plus a
    candidacy with no feed name (INFERRED).
  - An added or removed candidate would show up as a change in a race's candidate count against the
    canonical (INFERRED).
  - The two cannot be told apart from the feed alone (INFERRED).
- **How the canonical would react.** Its candidacy ledger "deliberately closed [existing Contests]
  to implicit inventory changes. Name corrections retain visible history; unsupported additions or
  retractions fail closed for explicit curator recovery" (OBSERVED, module docstring of
  `RES/src/toronto_election_results/candidacy_ledger.py`). So a renamed or removed registry entry
  would stop the next canonical refresh until a curator records it (INFERRED).

### Test file and live file

All OBSERVED:

- **Same URL and filename.** "Will the election results be available at the exact same URL for both
  testing and election night? Yes", and "The filename will not change on election night"
  ([MEDIA FAQ], page modified Sept 21, 2026).
- **Candidates in every file.** Both the Sept 17 zeroed files and the Sept 28 test "will have list
  of candidates and all races" ([PRES] slide 10).
- **Only polls and voters are flagged.** The only values the City says may change are `polls` and
  `totalVoters`: "Both values are subject to change as we approach election day" ([MEDIA FAQ]).
- **Nothing promises names or keys.** No source says whether candidate names, the candidate set, or
  office and ward keys may change between the test file and the live file. Spec v1.1 (dated
  2026-09-01, PDF modified 2026-09-16) has a version history but no promise of notice before a
  change ([SPEC] p. 2).
- **No history to check against.** No zeroed or test file from any past election is archived. The
  Wayback CDX for `mediaresults.toronto.ca/results/*` holds only captures of the 2018 final, 2022
  night, 2023 mayoral by-election and 2023 Ward 20 files ([WB CDX]). So name stability between test and live cannot
  be checked historically.

### The canonical's 2026 source and refresh

All OBSERVED:

- **Source.** The City Clerk's candidate-list JSON, the same three `REG` URLs, parsed by
  `RES/src/toronto_election_results/pending_candidates.py`.
  - Only `Active` entries are kept.
  - `candidate_name` is built from `firstName` and `lastName`; `candidate_name_raw` is `name`.
  - The four trustee acclamations (TCDSB 6 and 12, Viamonde 2 and 4) are hard-coded from the City's
    Declaration of Acclamation PDF.
- **Refresh.** It is manual. Running `uv run python -m toronto_election_results.pipeline`
  re-downloads the rosters. The `--refresh-candidates` flag, added on Sept 30 in `ec09f7d` and
  merged in `53e00fc`, re-downloads only the rosters when used with `--skip-download`. The repo has no CI workflow.
- **Last refresh.** The rosters were retrieved 2026-09-30 16:22 UTC (`CAN` `build_manifest.json`
  `sources`, `pending_candidate_snapshot_through` "2026-09-30"). That release changed only campaign
  URLs. "Candidate membership, names, and acclamation status match the previous rosters"
  (`RES/docs/research/candidate-roster-refresh-2026-09-30.md` on `main`).
- **Stale text on the checked-out branch.** The working copy's `README.md` and `build_manifest.json`
  still say "as of 2026-08-27", and its data dictionary says 2026-08-21. `main` says 2026-09-30.

---

## Unknown / gaps

- **Whether the live file's names will be byte-identical to the test file's.** The City does not
  say. No historical test file exists to compare.
- **Whether a 2026 death or disqualification would be handled like 2022.** The 2022 shape is known,
  but how the canonical would record such a case is not documented.
- **The registry's regeneration cadence**, and whether the City would correct a ballot name this
  late.
- **Whether the canonical will be refreshed again before Oct 26**, and whether any of the 59
  `proposed` links will be confirmed. Either would change the `person_id` coverage above.
- **The final pre-election forecast release** may change which mayoral candidates are named. This
  note reflects `backend-2026-10-02.3`.
- **The Municipal Elections Act text** (withdrawal deadline, s. 39) could not be read directly.
  e-Laws renders client-side and CanLII returned 403. The City's own pages are cited instead.

## Self-critique

- **The exact match is by construction.** Feed names, the registry's `firstName`/`lastName`, and the
  canonical `candidate_name` come from the same City data. 361/361 shows they agree today. It is not
  evidence that a name join is robust to a change.
- **This is the zeroed test file, not the live one.** The live file is generated on the night by the
  same system (INFERRED from [PRES] slide 5), but nothing guarantees identical strings. Unicode
  form, for example, is NFC today, and that is not promised.
- **The "display name" coverage overstates curation.** Every frontend `display_name` is the feed
  string copied through, so "all 361 covered" says nothing about labels.
- **The fuzzy figures depend on the measure.** Similarity uses `difflib` after case and accent
  folding. Another measure would give other numbers. The collisions listed are the concrete ones a
  surname or edit-distance rule would hit.

## Sources

- **[FEED]** City of Toronto zeroed test files, same URLs as live:
  <https://mediaresults.toronto.ca/results/unofficialresult.json> and
  <https://mediaresults.toronto.ca/results/unofficialresult-wardbyward.json>, downloaded 2026-10-06
  12:15:40 UTC. Versions are in the inputs table above.
- **[REG]** City candidate registry JSON, downloaded 2026-10-06 12:16:52 UTC:
  <https://www.toronto.ca/data/elections/candidate_list/mayorCandidates_2026.json>,
  <https://www.toronto.ca/data/elections/candidate_list/councilorCandidates_2026.json>,
  <https://www.toronto.ca/data/elections/candidate_list/trusteeCandidates_2026.json>.
- **[SPEC]** *2026 Toronto Municipal Election JSON Unofficial Result Files: Data Specifications*, v1.1,
  <https://www.toronto.ca/wp-content/uploads/2026/09/96f1-MediaJSONUnofficial-ResultsDataSpecificationsFor-Web.pdf>
  (sha256 `58646ed0…`, downloaded 2026-10-06).
- **[PRES]** *2026 Toronto Municipal Election Media Technical Briefing*, Sept 16, 2026,
  <https://www.toronto.ca/wp-content/uploads/2026/09/96ed-2026Unofficial-ResultsMediaPresentationfor-Web.pdf>
  (sha256 `aab55549…`).
- **[MEDIA FAQ]** *Live Results Information for Media*, "Date modified: September 21, 2026", fetched
  2026-10-06,
  <https://www.toronto.ca/city-government/elections/election-results-reports/election-results/live-results-information-for-media/>.
- **[CAND]** *Become a Candidate*, "Date modified: September 2, 2026", "Withdrawing a Nomination",
  <https://www.toronto.ca/city-government/elections/candidates-third-party-advertisers/candidate-information/become-a-candidate/>.
- **[NOM]** *Municipal election candidate nominations close tomorrow*, Aug 20, 2026,
  <https://www.toronto.ca/news/municipal-election-candidate-nominations-close-tomorrow/>.
- **[BAC]** *Becoming a Candidate, 2026 Municipal Election* presentation, slide 17,
  <https://www.toronto.ca/wp-content/uploads/2026/05/9056-Becoming-a-Candidate-Presentation.pdf>.
- **[NOMPAPER]** *2026 Municipal Election Nomination Paper* (CAND309), p. 1,
  <https://www.toronto.ca/wp-content/uploads/2026/04/9046-CAND309-Nomination-Paper-with-Trustee-Final.pdf>.
- **[LAI]** *Impact of the passing of Councillor Cynthia Lai on the Scarborough North (Ward 23)
  election*, Oct 21, 2022,
  <https://www.toronto.ca/news/impact-of-the-passing-of-councillor-cynthia-lai-on-the-scarborough-north-ward-23-election/>.
- **[WB CDX]** <https://web.archive.org/cdx/search/cdx?url=mediaresults.toronto.ca/results/*&output=json>,
  queried 2026-10-06. **[WB-2018]** capture `20181029172648`. **[WB-2022]** capture `20221025014628`
  (`seq` 2022-10-24 21:46 EDT). **[WB-2023]** capture `20230627150743`. URL pattern:
  `https://web.archive.org/web/<ts>id_/https://mediaresults.toronto.ca/results/unofficialresult.json`.
- **Canonical (`RES`, `main` `53e00fc`).**
  - Tables: `data/out/election_results.csv`, `people.csv`, `candidacy_person_links.csv`,
    `build_manifest.json`, and `data/reference/person_alias_curations.csv`.
  - Code: `src/toronto_election_results/pending_candidates.py`, `candidacy_ledger.py`, `pipeline.py`.
  - Docs: `docs/data-dictionary.md`, `docs/research/candidate-roster-refresh-2026-09-30.md`.
  - Release asset: `person_aliases.json` from release `results-2026-09-30.2` (`gh release download`).
- **Frontend (`FE`, commit `9964021`).** `src/lib/candidates.ts`, `src/lib/mayoral-forecast.ts`,
  `src/lib/feed-source.ts`, `src/types/feeds.ts`, `fixtures/README.md`, `public/data/source-manifest.json`,
  and `.release-data/{mayoral_candidates,council_race_cards,trustee_race_cards,mayoral_forecast}.json`.
- **Backend (`BE`, commit `20f4c11`).** `backend/model/compact_mayoral/readings.py`,
  `backend/model/compact_mayoral_feed.py`, `backend/model/mayoral_candidate_ids.py`,
  `backend/model/council_race.py`, and `data/raw/canonical/election_results.csv`.
- **Data repo (`toronto-election-poll-tracker-data`, commit `18d52fa`).**
  `data/raw/candidates/challengers.csv`.
- Prior notes: [01-city-feed-guarantees.md](01-city-feed-guarantees.md) (feed fields, name format,
  ordering, withdrawals for mayor and council) and
  [03-historical-replay-counts.md](03-historical-replay-counts.md) §6 (historical name formats and joins).
