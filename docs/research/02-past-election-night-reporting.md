# How past Toronto election nights reported (2018, 2022, 2023)

Research date: 2026-10-05. Ticket: [#3](https://github.com/alexwolson/toronto-election-live-projection/issues/3).
Times are Toronto local time (EDT) unless marked UTC. Polls closed at 8 p.m. each night.

Labels: **OBSERVED** means I fetched the artifact and read the value myself. **INFERRED** means I
reasoned from observed values. "Secondary" marks a claim taken from news coverage.

## Answer

- **Real election-night feed snapshots exist.** The Wayback Machine holds 11 genuine in-window
  captures of the City's JSON feed: 6 from 2022 and 5 from 2023. It holds none for 2018. The captures
  are sparse checkpoints taken whenever the crawler happened to visit, so they do not give a complete
  arrival order. (OBSERVED)
- **The pattern was a fast burst, then a long tail.** The feed was a zeroed file until about 8:10–8:15.
  After that, 84–93% of polls landed within 26–70 minutes of close. The last few polls landed no
  later than 3.6 hours (2023), 4.2 hours (2018) and 6.7 hours (2022) after close. (OBSERVED, from the
  snapshots and the City's own reports)
- **Advance and mail aggregates are the main source of drift.** In 2023 most of them arrived after the
  first wave of election-day polls. Advance and mail voters strongly favoured Chow, so the early count
  showed Bailão ahead (36.1% to 35.2% at 20:26, with 84% of polls in). Chow finished 4.7 points ahead.
  Election-day polls showed no detectable link between arrival time and candidate support.
  (OBSERVED, by exact reconstruction against poll-by-poll results)
- **"Polls reported" is a poor stand-in for "votes counted," and it can err in either direction.** In
  2023 at 20:26, 84% of polls held only 73% of the votes. In 2022 at 21:09, 93% of polls already held
  99% of the votes. (OBSERVED)
- **Verdict: replays need both.** A complete arrival order has to be simulated. The real snapshots
  should serve as fixed checkpoints, both to validate the simulator and as real test cases for the
  projection. The 2023 20:26 state, where the leader was wrong, is the strongest such case. See
  [What a simulation must reproduce](#what-a-simulation-must-reproduce).

## What I searched

Wayback CDX API (read-only, sequential requests):

| Query | Result |
|---|---|
| `url=mediaresults.toronto.ca/*`, 2014–2026, collapse by urlkey | Only the two feed paths, plus crawler noise |
| `url=mediaresults.toronto.ca/results/unofficialresult.json` (all captures) | 7 captures; 2 in-window (2022-10-25T01:46:28Z, 2023-06-27T01:24:26Z) |
| `url=mediaresults.toronto.ca/results/unofficialresult-wardbyward.json` | 4 captures; 1 in-window (2023-06-27T00:26:39Z) |
| `url=electionresults.toronto.ca` matchType=domain, 2014–2026 (3,084 rows) | The City's public results app. It reads `results/unofficialresult.json` from its own host. Election-night copies: 5 for 2022 and 4 for 2023 (one exact duplicate state) |
| Both hosts, prefix queries for 2018-10-20 to 2018-10-28 | **No feed captures for 2018** |
| `url=toronto.ca` matchType=domain, election-night windows | 2018: 496 rows, crawler noise, no results data. 2022 returned HTTP 502; 2023 returned empty |
| `www.toronto.ca/city-government/elections/*` | Media-info pages: the 2018 version was captured; no 2022 or 2023 election-period capture exists |
| archive.today timemaps for the feed URLs and the app root | Feed URLs: none. App root: **one capture, 2018-10-23 00:51:42 UTC (20:51 EDT)**, but it sits behind a CAPTCHA (HTTP 429) and I could not read it |
| Memento aggregator (timetravel.mementoweb.org) for the feed URLs | No non-Wayback mementos |
| `gh search code` for both feed hosts | Only Alex's own `toronto-election-live-projection` repo |

I did not search older general elections (2014, which also used modem tabulators) or the 2023–2025
council by-elections for in-window captures.

**Feed format check (OBSERVED).** The 2018 media page names the same two URLs as 2026
([2018 media page, archived](https://web.archive.org/web/20180920222404/https://www.toronto.ca/city-government/elections/general-information/election-results/live-results-information-for-media/)).
The 2018 JSON spec defines `seq` as "a value derived from the timestamp when this file is generated.
Different seq values indicate JSON files were generated at different times, but the report contents may
be the same"
([2018 spec .docx](https://web.archive.org/web/2018id_/https://www.toronto.ca/wp-content/uploads/2018/09/9656-Media_JSON_Results_File_Specifications.docx)).
In every capture, `seq` is Unix-epoch milliseconds and falls 5–27 s before the capture time. So `seq`
dates each snapshot, and a final file's `seq` is the last time the file was regenerated. It is an
upper bound on when the last poll arrived, not the arrival time itself (INFERRED). The 2018 briefing
says files were produced "every 30-60 seconds", with results arriving from tabulator modems and call
centre data entry
([2018 media presentation](https://web.archive.org/web/2018id_/https://www.toronto.ca/wp-content/uploads/2018/09/8f73-Results_Media_Presentation.pdf)).

**What a "poll" is in the feed (OBSERVED).** `polls` counts subdivisions, including one ward-wide
aggregate per special code. In the poll-by-poll workbooks, each ward's subdivision count equals the
feed's per-ward `polls` exactly:

| Year | Feed `polls` | Regular subdivisions | Special codes per ward |
|---|---|---|---|
| 2018 | 1,800 | 1,700 | 96, 97, 98, 99 |
| 2022 | 1,535 | 1,460 | 97, 98, 99 |
| 2023 | 1,451 | 1,351 | 96, 97, 98, 99 |

The 2023 workbook's Read Me defines 97 as mail-in, 98/99 as advance vote, and 96 as long-term-care
and retirement homes (OBSERVED). The 2022 workbooks do not define the codes. The 2022 reading (97
mail, 98/99 advance) and the 2018 reading (97–99 advance, 97 = City Hall "Vote Anywhere"; 96
probably a second City Hall reporting unit, INFERRED) are established from the City's
voter-statistics files in [03-historical-replay-counts.md](03-historical-replay-counts.md); the 2022
vote sizes fit (97: 19,797; 98 + 99: 113,900 valid mayoral votes). (Edited 2026-10-05: this paragraph
previously leaned on a note in the abandoned `toronto-election-live-projection` repo.)
Source workbooks are in `~/code/personal/toronto-election-results/data/raw/`:
`byelection/2023_office_of_the_mayor.xlsx` and `results/extracted/{2018,2022}/*Poll_By_Poll*.xlsx`.

All snapshots are tabulated in [02-feed-snapshots.csv](02-feed-snapshots.csv), with a Wayback URL for
each row.

## 2023 mayoral by-election (June 26)

| Time (feed `seq`) | Polls in | % polls | Votes (% of final) | Chow | Bailão | Source |
|---|---|---|---|---|---|---|
| 20:06:39 (capture) | 0 | 0 | 0 | – | – | Public app; zero file with seq 09:12 that morning |
| ~20:15 | – | – | – | – | – | "results began appearing at 8:15 p.m." (Globe live blog; secondary) |
| **20:26:22** | 1,221 / 1,451 | 84.1 | 525,703 (72.6%) | 35.16 | **36.14** | Media ward-by-ward file |
| 20:30–20:32 | ~1,277 | ~88 | – | 36.21 | 34.66 | Globe: Chow "took the lead just after 8:30"; 8:32 entry (secondary) |
| 20:56:21 | 1,383 | 95.3 | 703,027 (97.0%) | 37.20 | 32.43 | Public app |
| 21:00 | – | – | – | – | – | Globe calls the race (secondary) |
| 21:24:21 | 1,411 | 97.2 | 716,814 (98.9%) | 37.14 | 32.52 | Media all-office file |
| 22:27:52 | 1,444 | 99.5 | 722,875 (99.8%) | 37.17 | 32.46 | Public app |
| 23:37:21 (last regeneration) | 1,451 | 100 | 724,638 | 37.17 | 32.45 | Final file's `seq` |

Rows sourced to the feed are OBSERVED; Globe rows are from
[Globe and Mail live updates](https://www.theglobeandmail.com/canada/toronto/article-toronto-mayor-election-2023-live-updates/).
The last poll landed between 22:28 and 23:37 (OBSERVED bounds). The City's 2023 report says only that
results "were continuously available and updated on the City's website"
([2023 supplementary report](https://www.toronto.ca/wp-content/uploads/2023/12/8bb4-Final-for-web-2023-Mayor-ByElection-Report.pdf)).

**Which polls were still out at 20:26 (OBSERVED, by exact reconstruction).** The ward-by-ward file
gives each ward's per-candidate partial votes and its count of outstanding polls. For each ward, an
integer program found the subset of final subdivisions whose per-candidate votes equal "final minus
partial."

- The fit is exact in 23 of 25 wards and within 1 vote in the other 2.
- The next-best alternative subset is off by at least 11 votes in every ward.
- So the identification is unique.

Results are in [02-outstanding-subdivisions.csv](02-outstanding-subdivisions.csv). The 230 polls still
out were:

| Kind | Still out at 20:26 | Final votes still out | Chow / Bailão share of those votes |
|---|---|---|---|
| Advance aggregates (98/99) | 39 of 50 | 96,752 of 129,648 | 46.5 / 14.9 |
| Mail aggregates (97) | 25 of 25 | 28,117 | 50.8 / 11.5 |
| Long-term-care aggregates (96) | 25 of 25 | 2,606 | 36.8 / 21.6 |
| Election-day subdivisions | 141 of 1,351 | 71,458 | 34.1 / 37.8 |
| *Already in: election-day subdivisions* | *1,210* | *492,809* | *34.4 / 37.6* |
| *Already in: advance aggregates* | *11* | *32,896* | *47.1 / 14.5* |

- Advance votes were already in for wards 1, 2, 10, 12 and 13 (both aggregates) and for ward 9's
  aggregate 99. Advance arrival was therefore interleaved, but heavily skewed late. (OBSERVED)
- Advance, mail and long-term-care aggregates made up 64% of the outstanding votes. This composition
  alone explains the leader flip. Outstanding election-day polls voted almost exactly like reported
  ones (Chow 34.1 vs 34.4; Bailão 37.8 vs 37.6). (OBSERVED)
- Between 20:26 and 20:56, about 177,000 votes arrived in 162 polls. A best-fit reconstruction of the
  later citywide-only snapshots puts all advance and mail aggregates in by 20:56, with all 25
  long-term-care aggregates among the last 40 polls at 21:24. (INFERRED, moderate confidence.)
  - With every 96 forced in, the best fit is off by 305–493 votes at 20:56 and 21:24, against 20
    votes unconstrained.
  - Forcing any advance or mail aggregate to still be out raises the error from 20 to 70–75 votes.
  - With only candidate totals to match against, this is not a unique identification.

**Geography (OBSERVED).** At 20:26 the outstanding election-day polls clustered by ward:

- Wards 5, 15, 19 and 9 each had 11–12 outstanding; wards 1 and 21 had 1 each.
- Outstanding polls were somewhat larger (507 vs 407 votes per poll).
- Ward reporting completeness was not correlated with candidate support. Spearman correlation between
  the share of a ward's election-day votes already in and the ward's final share: −0.06 for Chow,
  −0.11 for Bailão (n = 25).

## 2022 general election (October 24)

| Time (feed `seq`) | Mayor polls in | % polls | Votes (% of final) | Tory | Councillor races at 100% polls | Source |
|---|---|---|---|---|---|---|
| 20:13:46 (capture) | 0 | 0 | 0 | – | 0 | Public app; zero file, seq Oct 22 11:09 |
| 20:20 | – | – | – | – | – | CP24 declared Tory "just minutes after the polls closed" (CTV live blog 8:20 p.m. entry; secondary) |
| 21:00 | – | ">96% of voting places" | – | – | – | City 2022 report |
| **21:09:00** | 1,423 / 1,535 | 92.7 | 544,041 (98.6%) | 61.97 | **0 / 25** | Public app |
| 21:46:01 | 1,426 | 92.9 | 545,156 (98.8%) | 61.99 | 0 / 25 | Media all-office file |
| 23:01:01 | 1,429 | 93.1 | 546,762 (99.1%) | 62.00 | 0 / 25 | Public app |
| 23:55:30 | 1,517 | 98.8 | 549,305 (99.5%) | 62.01 | 18 / 25 | Public app |
| 02:42:30 Oct 25 (last regeneration) | 1,535 | 100 | 551,890 | 62.00 | 25 / 25 | Final file's `seq` |

Sources:
[CTV 2022 live blog (archived 22:16 EDT)](https://web.archive.org/web/20221025021603/https://toronto.ctvnews.ca/election-results-expected-soon-as-polls-close-across-ontario-1.6122477).
The City's
[2022 report](https://www.toronto.ca/wp-content/uploads/2023/09/9025-2022-Municipal-Election-ReportAODAFINAL.pdf),
p. 31, says "More than 96% of total voting places successfully reported election results by 9 p.m.",
with a phone-in call centre as back-up. The same CTV blog lists more than ten voting places with hours
extended to 8:05–8:25 p.m.

- **Shape: a burst, a plateau, then a batch.** By 21:09 the burst was over: 93% of polls, holding
  98.6% of votes. Then almost nothing happened for two hours (+6 polls by 23:01). Between 23:01 and
  23:55, 88 polls arrived at once. The last 18 arrived between 23:55 and 02:42. (OBSERVED)
- **Advance and mail were all in by 21:09 (OBSERVED, by exact reconstruction).** I ran the same
  per-ward reconstruction on the councillor race in each ward. All 112 polls still out at 21:09 were
  election-day subdivisions; none of the 75 advance or mail aggregates was among them.
  - The fit is exact or within 3 votes in 24 wards. Ward 4 is off by 7 votes.
  - The reconstruction cannot show whether the advance and mail aggregates arrived before or among the
    election-day polls before 21:09.
- **The tail polls were tiny.** The outstanding polls had a median of 21 votes (the 5th percentile of
  poll size) and a median electorate of 128 voters, against 1,541 for all subdivisions. Half of all
  subdivisions with 100 or fewer voters were in the tail. 12 tail polls have no geometry. Every ward
  had 2–7 outstanding. (OBSERVED) These are likely institutional or care-home voting places, plus late
  phone-ins and the extended-hours places. (INFERRED)
- **Drift after 21:09 was negligible (OBSERVED).**
  - Tory's share moved 0.03 points.
  - Every councillor leader at 21:09 was the final winner.
  - The largest councillor-margin change was 0.62 points.
  - The two closest races were stable: ward 5 went from 0.33 to 0.44 points, and ward 11 from 0.54 to
    0.51.
- **"All polls reported" came before the final count (OBSERVED).** At 23:55, councillor wards 6, 11,
  13 and 22 and four trustee areas showed `pollsReceived == polls`, yet their votes rose afterwards.
  Ward 11 (University–Rosedale) showed 77/77 polls with Saxe ahead by 130. After that, 102 more votes
  arrived, and the final margin was 123. In wards 3 and 10, polls were marked received without their
  votes. A per-race "Elected (unofficial)" rule triggered at 100% of polls would have fired early in
  four wards.
- **Other feed quirks (OBSERVED).**
  - MonAvenir ward 4 reported `polls: 0` with `pollsReceived` of 537–578.
  - Uncontested French-board races carried 0 votes. The 2022 Readme says those races were acclaimed or
    voided.
  - Deceased candidate Cynthia Lai stayed listed with 0 votes. The final poll-by-poll file omits her.

## 2018 general election (October 22)

No feed snapshot from election night survives in the Wayback Machine (OBSERVED). What exists:

- The elections homepage, captured at 22:43, says "View the real-time unofficial election results,
  starting at 8:15 p.m." and links to `electionresults.toronto.ca`
  ([capture](https://web.archive.org/web/20181023024329/https://www.toronto.ca/city-government/elections/)).
  (OBSERVED)
- "CP24 declared his victory at 8:24 p.m., just minutes after the first batch of results started to
  filter in"
  ([CTV, archived 01:51 Oct 23](https://web.archive.org/web/20181023055117/https://toronto.ctvnews.ca/let-s-get-to-it-john-tory-after-winning-second-term-1.4145133)).
  (secondary)
- The City's [2018 Election Report](https://www.toronto.ca/wp-content/uploads/2019/07/96b2-2018-Election-Report.pdf),
  p. 27 (OBSERVED, report text):
  - "90% of election results were received by modem transmission within minutes of polls closing with
    the remaining received by telephone before 9 p.m."
  - "98% of all results were processed and posted publicly by 9 p.m."
  - "All results were later verified by uploading the data directly from each of the tabulator memory
    cards."
- The final file was last regenerated at 00:13:01 on Oct 23, so the last poll landed by 00:13 at the
  latest. (OBSERVED)
- The 2018 poll-by-poll workbook carries a correction notice. Tabulators at 10 of 1,700 subdivisions
  had been delivered to the wrong voting place in the right ward, so on election night their counts
  were reported under another subdivision. Ward totals were unaffected. (OBSERVED) Subdivision-level
  night data can therefore differ from the certified poll-by-poll files.

## Cross-election findings

1. **First results.** The feed stayed a pre-results zero file until after 20:06 (2023) and 20:13
   (2022). The first data appeared around 8:15 in all three years. (OBSERVED for the zero files and
   the 2018 "starting at 8:15" notice; secondary for the 2023 time.)
2. **Speed.** Most polls landed within the first hour. (OBSERVED)
   - 2018: 90% within minutes and 98% by 9 p.m. (City report).
   - 2022: 92.7% of feed polls by 21:09. The City reports more than 96% of voting places by 9 p.m.;
     voting places are not the same unit as feed subdivisions.
   - 2023: 84% by 20:26 and 95% by 20:56.
3. **Tail.** The last 1–7% of polls took until 23:37 (2023), 02:42 (2022) and about 00:13 (2018),
   with flat stretches and batch jumps along the way. (OBSERVED)
4. **Advance and mail timing varied by election.** In 2023 they were mostly late and partly
   interleaved: 11 of 50 advance aggregates were in at 20:26, and none of the mail. In 2022 they were
   all in by 21:09, with earlier timing unknown. 2018 is unknown. (OBSERVED)
5. **What correlated with arrival.**
   - Vote mode: strongly, in 2023, because the modes differed politically. (OBSERVED)
   - Candidate support among election-day polls: no detectable correlation in 2023. (OBSERVED, one
     snapshot)
   - Ward and size: some ward clustering, and size effects in opposite directions (2023's late polls
     were larger; 2022's tail was tiny). (OBSERVED)

## Conclusion: real order, simulated order, or both

**Both.** A real chronological replay is impossible: no election has more than five populated
in-window states, 2018 has none, and only one snapshot (2023 at 20:26) has ward-level mayoral detail.
2022 has ward-level council and trustee detail at four times. (OBSERVED)

The real snapshots are still valuable:

- **As a projection test case.** The 2023 20:26 ward-by-ward state is genuine. At 84% of polls the
  leader was wrong. Any qualifying mayoral projection must not have called Bailão favoured at that
  point.
- **As calibration targets for a simulator.** The 2022 sequence shows the plateau and tail, and
  provides council-level checkpoints.

### What a simulation must reproduce

1. A zeroed file until about 8:10–8:15, then a burst: roughly 85–93% of polls within 25–70 minutes,
   and 98% by about 9 p.m.
2. Advance and mail aggregates as separate large blocks. In 2023 an advance aggregate held 870–5,300
   votes and a mail aggregate 390–2,200; the 75 blocks together held 22% of all votes. Their timing should be drawn from at least three regimes: early,
   interleaved, and after the first burst (the 2023 pattern). Their candidate skew should be a
   parameter, not a constant: Chow 47/51% among advance/mail voters vs 34% on election day was
   specific to that race.
3. A long tail of small election-day polls and institutional or care-home aggregates. The last poll
   should land 2.5–6.7 hours after close (the observed bounds), with flat stretches and batch jumps
   along the way (2022: +6 polls in 2 hours, then +88 in under an hour).
4. A random order for election-day polls with respect to candidate support. Ward clustering and
   poll-size effects should be sensitivity cases, not the baseline.
5. Reporting Progress decoupled from vote completeness. The feed counts each special aggregate as one
   poll and does not say which outstanding units are aggregates. The model sees "49/52 polls" and
   cannot tell whether the missing 3 are 3,000-vote advance blocks or 20-vote institutional polls.
6. Feed artifacts: races reaching 100% of polls before their final votes; offices with `polls: 0`;
   uncontested races at 0 votes; withdrawn or deceased candidates listed at 0 votes.

## Unknown / not found

- **2018 election-night data.** No feed capture exists on either host. The single archive.today
  capture of the public app at 20:51 EDT, <https://archive.ph/20181023005142/https://electionresults.toronto.ca/>,
  might show the 20:51 state. It returned a CAPTCHA (HTTP 429) to every automated request, so only a
  person can open it in a browser.
- **2022 before 21:09.** There is no capture between the 20:13 zero file and 21:09. When the advance
  and mail aggregates landed in 2022 is unknown, except that it was before 21:09.
- **Exact last-poll times.** I have only bounds: 22:28–23:37 in 2023, 23:55–02:42 in 2022, and no
  later than 00:13 in 2018. Under the spec, files regenerate whether or not content changed.
- **Which polls made up the late tail in 2023.** After 20:26 I have only citywide totals, so the
  long-term-care finding is a best fit, not a unique identification.
- **The 2022 and 2023 media-info pages and specs.** No Wayback capture was found. The 2018 versions
  were read instead.
- **Whether the media host and the public-app host were fed by the same generator.** Their format and
  `seq` semantics match, and their snapshots form one consistent sequence. (INFERRED)
- **Not searched:** the 2014 general election; council and school-board by-elections; Wayback captures
  of media live blogs beyond those cited; CBC and CP24 pages (which returned 403 to my fetches).
- **Contradicts an earlier note.** This finding supersedes the "no genuine chronological election-night
  snapshot archive" result in `alexwolson/toronto-election-live-projection`
  `docs/research/historical-replay-evidence.md` (2026-10-05). That search was explicitly bounded and
  did not query the Wayback CDX for the feed hosts.

## Self-critique (what could make these numbers misleading)

- **Final results versus night data.** The reconstructions match against certified poll-by-poll
  results, not the night's own subdivision data. The 2018 misattribution notice shows the two can
  differ. The 2023 fits are exact and unique, and the 2022 fits are nearly so, so ward-level
  conclusions are robust. Individual subdivision IDs could still be wrong where the residual is not
  zero.
- **The sampling is the crawler's.** Snapshot times were set by when the Wayback crawler visited, not
  by any event. They show states, not rates between states.
- **"Advance late" rests on one election.** It comes from 2023, a mayor-only by-election with one race
  per ballot. 2026 is a general election, with six offices on the feed and several races per ballot,
  so counting and transmission may run differently. 2022's evidence fits either early or
  late-before-21:09 arrival.
- **The mode skew was race-specific.** The 2023 advance/mail lean to Chow arose because Bailão surged
  after advance voting closed. In 2026, mode skew could be zero or reversed. The simulation must vary
  it, not hard-code it.
- **"No correlation" is a single test.** It rests on one snapshot and a 25-ward rank correlation with
  wide uncertainty. Within-ward geographic order is untested.

## Reproduction

Scripts and raw captures are in the scratchpad
`/private/tmp/claude-501/-Users-alex-code-personal-toronto-election/c2bd7f14-220a-43c2-9de5-30308dc5313c/scratchpad/t02/`:

- `caps/`: the downloaded Wayback payloads.
- `cdx_*.txt`: the CDX listings.
- `ilp.py`, `id2023.py`, `id2022.py`, `city2023*.py`: the reconstructions. They need
  `uv run --with scipy`.
- `mkcsv.py`, `mkout.py`: build the two CSVs here.

Every Wayback payload URL is in [02-feed-snapshots.csv](02-feed-snapshots.csv) and can be fetched
again.
