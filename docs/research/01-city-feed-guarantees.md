# What the City's election-night media feed promises

Research note for [#2](https://github.com/alexwolson/toronto-election-live-projection/issues/2). Written 2026-10-05.

Every load-bearing claim is labelled **OBSERVED** (seen in the source or file) or **INFERRED**
(reasoned from observations). Source keys in square brackets are listed under "Sources" at the end.

## Summary

- **Two files, fixed URLs, HTTPS only, no CORS.** `unofficialresult.json` holds all six offices.
  `unofficialresult-wardbyward.json` holds mayor by ward. Test and live use the same URLs, and the
  filenames do not change on the night. **OBSERVED** [MEDIA FAQ], [SPEC p4], [HDR].
- **Every number is a JSON string** (`"polls" : "1431"`). The one exception is office `id`, which
  is an integer. **OBSERVED** [TEST-A], [TEST-W].
- **`percentage` is 0–100, has two decimals, and is a string.** It equals 100 × candidate
  `votesReceived` / race `votesReceived`, and its denominator is valid votes for candidates only.
  The spec's example is ambiguous; archived live files from 2018, 2022 and 2023 settle it.
  **OBSERVED** [WB-2018], [WB-2022], [WB-2023b].
- **`polls` counts every reporting subdivision, special ones included.** Each ward's advance
  places (98, 99), mail-in (97) and, when used, the long-term-care aggregate (96) count as one
  poll each. In 2018, 2022 and 2023 the feed's per-ward `polls` equalled exactly the number of
  subdivision columns in the certified poll-by-poll file. **OBSERVED** [PBP-2018], [PBP-2022],
  [PBP-2023].
- **An advance or mail aggregate is one "poll" that carries many votes**, about 6–8 regular polls'
  worth (2022 and 2023). It increments `pollsReceived` by 1 when it lands, and nothing in the feed
  marks it as an aggregate. In the 2023 by-election these aggregates landed interleaved with
  regular polls, not as a block. **OBSERVED** (sizes), **INFERRED** (arrival order, from a
  subset-sum reconstruction).
- **Candidates are re-sorted by votes, descending, on every refresh**, with ties broken by name.
  Before any votes arrive they appear in surname order. **OBSERVED** [MEDIA FAQ], [TEST-A],
  [WB-*].
- **The only scheduled live-data test is already over** (Sept 28, 8–10 p.m.). No further test is
  documented before Oct 26. **OBSERVED** [PRES slide 10].
- **At the end of the count the file freezes and stays at the same URL.** The 2018 final file was
  still being served in Nov 2019. **OBSERVED** [WB CDX]. The City gives no end time and says
  nothing about a final or "official" file. **OBSERVED** [MEDIA FAQ].
- **A test-file anomaly to watch:** in the 2026 files, every school-board area's `totalVoters` is
  copied from the City ward with the same number. In 2018 and 2022 the boards carried their own
  elector counts. **OBSERVED** [TEST-A], [WB-2018], [WB-2022].

## 1. Files, URLs and transport

| Item | Finding | Label | Source |
|---|---|---|---|
| All-office file | `https://mediaresults.toronto.ca/results/unofficialresult.json`: Mayor, Councillor, TDSB, TCDSB, Conseil scolaire Viamonde, Conseil scolaire catholique MonAvenir | OBSERVED | [SPEC p4], [TEST-A] |
| Mayor-by-ward file | `https://mediaresults.toronto.ca/results/unofficialresult-wardbyward.json` | OBSERVED | [SPEC p4], [TEST-W] |
| Update cadence | "updated every 60 seconds" ([SPEC p4]); "On October 26 after 8 p.m., files updated every 60 seconds" ([PRES slide 6]); "approximately every 60 seconds" ([MEDIA FAQ]) | OBSERVED | as cited |
| Same URL for test and live | "Yes" | OBSERVED | [MEDIA FAQ] |
| Filename stable on the night | "The filename will not change on election night." | OBSERVED | [MEDIA FAQ] |
| HTTPS only | Plain HTTP returns `301` to the HTTPS URL | OBSERVED | [MEDIA FAQ], [HDR] |
| CORS | "Cross-origin requests to the results endpoint are not supported." No `Access-Control-Allow-Origin` header is returned, even when an `Origin` header is sent. The response also sets `cross-origin-resource-policy: same-origin`. | OBSERVED | [MEDIA FAQ], [HDR] |
| Intended architecture | "Consumers should retrieve the results file from their own infrastructure, process the data as required, and publish it through their own applications" | OBSERVED | [MEDIA FAQ] |
| Hosting | Files are pushed from the City's results servers to AWS (CloudFront, `server: CloudFront`) | OBSERVED | [PRES slide 5], [SPEC p4], [HDR] |
| Auth | None; a plain `curl` works | OBSERVED | [HDR] |
| Encoding | UTF-8 with non-ASCII names (`Geneviève Oger`, `Andi Hoàng-Lefranc`). No BOM. The header is `content-type: application/json` with no charset. | OBSERVED | [TEST-A], [HDR] |
| Size | All-office file 48,961 B (4.9 KB gzipped). Ward-by-ward file 294,674 B (3.4 KB gzipped, while zeroed). The 2023 by-election ward-by-ward file with live numbers was 580,690 B (10.8 KB gzipped). | OBSERVED | [TEST-A], [TEST-W], [WB-2023a] |
| On-night support | "No technical support will be available on October 26." Critical messages are posted on the media page. | OBSERVED | [MEDIA], [PRES slide 9] |

## 2. Field by field

### `unofficialresult.json` (all offices)

| Path | Meaning | Label | Source |
|---|---|---|---|
| `electionDesc` | `"2026 Municipal Election"` | OBSERVED | [TEST-A] |
| `seq` | Epoch milliseconds when the file was generated. "Different seq values indicate JSON files were generated at different times, but the report contents may be the same." The current test value `1790647481807` decodes to 2026-09-28 22:04:41.807 EDT. | OBSERVED | [SPEC p4], [TEST-A] |
| `office[]` | Six offices, ids 1–6 in fixed order: Mayor, Councillor, TDSB, TCDSB, Viamonde, MonAvenir | OBSERVED | [SPEC p4–5], [TEST-A] |
| `office[].id` | Integer, not a string | OBSERVED | [TEST-A] |
| `office[].ward[]` | One entry per race, sorted by `num` ascending. **Mayor has a single pseudo-ward `{"name":"City-wide","num":"0"}`**, which the spec does not mention. Councillor has 25 wards. TDSB has 12 areas and TCDSB 12. Viamonde has 3 (nums 2, 3, 4) and MonAvenir 2 (nums 3, 4). | OBSERVED | [TEST-A] |
| `ward.name` | Ward name. **The key is absent for school-board areas**, not null. The spec says "There is no name for schoolboard wards." | OBSERVED | [SPEC p6], [TEST-A] |
| `ward.num` | String. City ward number (1–25), school-board area number, or `"0"` for the mayor's citywide row. | OBSERVED | [TEST-A] |
| `ward.polls` | "Total number of subdivisions in this ward", including the special subdivisions (§3). For every office, the per-race values sum to the citywide 1,431. | OBSERVED | [SPEC p6], [TEST-A] |
| `ward.pollsReceived` | "Total number of subdivisions received in this ward" | OBSERVED (definition) | [SPEC p6] |
| `ward.totalVoters` | Spec: "Total number of voters in this ward". In practice it is the number of electors on the voters' list, not turnout. 2026 mayor: 2,143,771, against the fact sheet's "Approximately 2.14 million eligible voters". 2022 Ward 1: 70,479 in the feed, against 70,485 "Total Electors" in the City's 2022 statistics. | OBSERVED (values), INFERRED (meaning) | [SPEC p6], [TEST-A], [FACT], [VS-2022], [WB-2022] |
| `ward.votesReceived` | Spec: "Total number of votes received in this ward". In practice it is the **sum of the candidates' votes in that race**: valid votes only, excluding rejected, declined and blank ballots. This held exactly for every race in the 2018, 2022 and 2023 files. Each office has its own denominator: at 21:46 on 2022 election night, mayor stood at 545,156 and councillor at 533,004. | OBSERVED | [WB-2018], [WB-2022], [WB-2023b] |
| `ward.candidate[]` | Candidates in the race (§5 covers ordering) | OBSERVED | [SPEC p6] |
| `candidate.name` | Display name, `"First Last"` (§5) | OBSERVED | [TEST-A] |
| `candidate.votesReceived` | Candidate's votes in this race | OBSERVED | [SPEC p6] |
| `candidate.percentage` | `100 × candidate.votesReceived / ward.votesReceived`, rounded to 2 dp, as a string, e.g. `"63.49"` for Tory in 2018. It is `"0.00"` when the race has no votes. All 2018 and 2022 values matched the recomputation to within 0.006. | OBSERVED | [WB-2018], [WB-2022], [WB-2023b] |

### `unofficialresult-wardbyward.json` (mayor by City ward)

| Path | Meaning | Label | Source |
|---|---|---|---|
| `office` | **A single object, not an array.** The spec (p7) agrees; presentation slide 8 wrongly shows `"office" : [ … ]`. | OBSERVED | [SPEC p7], [PRES slide 8], [TEST-W] |
| `office.polls`, `.pollsReceived`, `.totalVoters`, `.votesReceived` | Citywide mayor totals, identical to the mayor's `City-wide` row in the all-office file. `office.pollsReceived` = the sum of ward `pollsReceived` (2023: 1,221 = Σ wards). | OBSERVED | [TEST-W], [WB-2023a] |
| `office.candidate[]` | All mayoral candidates. In the test files the names and their order exactly match the all-office mayor list (53 candidates). Sorted by citywide votes, descending (2023: Bailão first at 20:26). | OBSERVED | [TEST-W], [WB-2023a] |
| `candidate.votesReceived` | Candidate's citywide votes | OBSERVED | [SPEC p8] |
| `candidate.ward[]` | All 25 City wards, `num` 1–25 ascending | OBSERVED | [TEST-W], [WB-2023a] |
| `candidate.ward[].polls`, `.pollsReceived`, `.totalVoters`, `.name` | Ward-level, repeated identically under every candidate. They match the Councillor row with the same `num` in the all-office file. | OBSERVED | [TEST-W] (0 mismatches over 53 × 25), [WB-2023a] |
| `candidate.ward[].votesCounted` | **Total mayoral votes counted in the ward**, all candidates combined, repeated under every candidate. In 2023 it equalled Σ candidates' ward `votesReceived` in all 25 wards. | OBSERVED | [SPEC p9], [WB-2023a] |
| `candidate.ward[].votesReceived` | This candidate's votes in this ward | OBSERVED | [SPEC p9], [WB-2023a] |
| No `percentage` | The ward-by-ward file has no percentage field | OBSERVED | [SPEC p8–9], [TEST-W] |

**Pairing the two files:** their `seq` values differ by milliseconds (`…481807` against `…481787`),
so they are generated separately and an equal `seq` cannot pair a Count Snapshot. **OBSERVED**
[TEST-A], [TEST-W]. Both files can therefore be fetched at slightly different counts. **INFERRED**

## 3. What `polls` counts

- **Subdivision codes (City definitions).** "Subdivision 97 for each Ward is designated for Mail In
  Voting. Subdivisions 98 & 99 for each Ward are designated Advance Vote locations" (2022 readme).
  The 2023 by-election readme adds "94 Long Term Care & Retirement Residence locations shown as
  subdivision 96 for each ward". The 2026 media FAQ restates that advance places are 98 and 99.
  **OBSERVED** [VS-2022 readme], [PBP-2023 Read Me], [MEDIA FAQ].
- **The feed's `polls` includes them.** Per ward, `polls` equals the count of subdivision columns
  in the certified poll-by-poll file, special codes included:
  - 2018: 1,800 in total, with 96–99 present in every ward and 90–99 in wards 10 and 13;
  - 2022: 1,535 in total, 1,460 regular plus 97/98/99 in all 25 wards;
  - 2023: 1,451 in total, 1,351 regular plus 96/97/98/99 in all 25 wards.

  **OBSERVED** [PBP-2018], [PBP-2022], [PBP-2023] against [WB-2018], [WB-2022], [WB-2023c].
- **2026: 1,431 in total.** The fact sheet promises "More than 1,350 election day voting places" and
  "50 advance voting places … two in each of the 25 wards". Mail-in voting exists (DS950
  tabulator; packages due Oct 14 noon). 1,431 − 75 (97/98/99 in each ward) = 1,356, which fits
  ">1,350". Adding 96 as well would give 1,331, which does not. So 2026 is most likely 97, 98 and
  99 per ward with no separate 96 aggregate, but the feed itself cannot confirm this.
  **OBSERVED** (inputs) [FACT], [TEST-A]; **INFERRED** (composition).
- **Special subdivisions are large.** Advance (98+99) made up 20.6% of mayoral votes in 2022 and
  17.9% in 2023; mail (97) made up 3.6% and 3.9%. The median advance subdivision held about 2,200
  votes in 2022 and 2,500 in 2023, against a median regular subdivision of 270 and 386.
  **OBSERVED** [PBP-2022], [PBP-2023].
- **School boards:** for each board, the per-area `polls` values sum to all 1,431 City
  subdivisions, the French boards included. 2018 and 2022 behaved the same way. **OBSERVED**
  [TEST-A], [WB-2018].

## 4. How the advance and mail aggregates enter the count

- **City statement:** "Advance voting results will be released following the close of polls on
  election night. On election night, these unofficial results will be reported as aggregate
  ward-wide totals and will not identify results from individual voting places, including the
  advance voting places." **OBSERVED** [MEDIA FAQ].
- **Mechanism:** the feed has no subdivision-level detail and no flag for "advance reported". Each
  of 97, 98 and 99 is one of the ward's `polls`. Its arrival adds 1 to `pollsReceived` and its votes
  to `votesReceived`/`votesCounted`. **OBSERVED** (no such field in [SPEC]/[TEST-*]); **INFERRED**
  (increment behaviour, from the §3 equality).
- **Timing (2023 by-election, ward-by-ward capture at 20:26 EDT).** For each ward I compared the
  feed's missing polls and missing votes (certified total minus `votesCounted`) against the
  certified per-subdivision totals. I then tested by subset-sum whether 98 or 99 could be among the
  unreported subdivisions.
  - Ward 13's 98 and 99, and the 99s in Wards 1 and 2, **must already have reported** by 20:26.
  - Ward 4's 98, both of Wards 20 and 21, and the 99s in Wards 14, 17 and 22 **must still have been
    out**.
  - Other wards are undetermined.

  So the aggregates arrive **interleaved** with election-day polls, ward by ward, not as a first
  or last block. **INFERRED**: the analysis assumes the election-night per-subdivision tallies
  equal the certified ones. The 2023 final feed total (724,638) did equal the certified total
  exactly ([WB-2023c], [PBP-2023]). [#3](https://github.com/alexwolson/toronto-election-live-projection/issues/3) owns the full arrival-order question.
- **Consequence of the size gap:** `pollsReceived / polls` overstates vote progress. At 20:26 in
  2023, 84% of polls but only 72.5% of the final mayoral votes were in (1,221/1,451 polls;
  525,703/724,638 votes). The early leader also flipped: Bailão led by about 5,000 at 20:26, and
  Chow won by about 34,000. **OBSERVED** [WB-2023a], [WB-2023c].
- **Mail (97):** the 2026 counting time is not stated. Mail ballots were inside the 2023
  election-night final (the feed total equalled the certified total, 97 included). **OBSERVED**
  [WB-2023c], [PBP-2023]. When 97 lands on 2026's night is not stated. **Unknown.**

## 5. Candidate names, ordering, withdrawn and acclaimed candidates

- **Format: `"<firstName> <lastName>"`** from the City's candidate registry, in mixed case, with
  accents kept and no padding. The spec's `" John Doe "` example is not literal. For mayor and all
  25 councillor races, the feed's names and their zero-vote order equal exactly the registry's
  `firstName + " " + lastName` and its order. **OBSERVED** [TEST-A], [REG] (fetched 2026-10-05,
  registry seq 2026-10-05 17:38 UTC).
  - Suffixes are kept: `Dewitt Lee III`, `Kannan S'ree Jr`. **OBSERVED**
  - Apostrophes and hyphens: `Ala'a Adib`, `Jean-François L'Heureux`. **OBSERVED**
  - Multi-word surnames are not recoverable from the display string: `Walied Khogali Ali`
    (surname `Khogali Ali`), `Jennifer Di Francesco`. **OBSERVED** [REG].
  - One candidate has no first name: registry `firstName:""`, `lastName:"Nisha Kumari"`, shown as
    `Nisha Kumari` and sorted under N. **OBSERVED** [REG], [TEST-A].
  - The certified poll-by-poll files use `"Last First"` (`Abdulsalam Bahira`), a different format
    from the feed. **OBSERVED** [PBP-2023].
- **Same surname in the mayoral race:** `Braeden Chow` / `Olivia Chow` and `Henoke Yohannes` /
  `Leila Yohannes`. No name repeats within a race or across races. **OBSERVED** [TEST-A].
- **Ordering:** "It will reorganize based on total votes received. If two or more candidates have
  the same number of votes, those will organize based on name." **OBSERVED** [MEDIA FAQ].
  Archived 2018, 2022 and 2023 files are sorted by votes, descending, in every race. **OBSERVED**
  [WB-*]. The name tie-break is on the registry surname, then first name, not the display string.
  **OBSERVED** in the zero-vote test file (for example, `Di Francesco` sorts before `Dias`, and
  `Nisha Kumari` sorts after `Lalla`). Consumers must therefore key on name, never on array
  position. **INFERRED**
- **Withdrawn candidates:** the deadline to file or withdraw was Aug 21, 2026 at 2 p.m., and
  "Candidates cannot withdraw after the nomination period has closed." **OBSERVED** [NOM], [CAND].
  The registry now lists only `Active` statuses (53 mayor, 190 councillor), matching the feed
  exactly. **OBSERVED** [REG]. So the feed contains no withdrawn candidates, and anyone who "drops
  out" from now on stays on the ballot and in the feed. **INFERRED**. The trustee registry was not
  checked.
- **Acclaimed or uncontested races appear in the feed.** TCDSB areas 6 and 12 and Viamonde areas 2
  and 4 each list exactly one candidate. **OBSERVED** [TEST-A]. In 2022, acclaimed French-board
  races stayed in the feed with 0 votes while `pollsReceived` still advanced (Viamonde 2:
  543/588 polls, 0 votes). One race had an empty `candidate` list. **OBSERVED** [WB-2022]; the
  2022 readme says "Candidates were either acclaimed or the election was voided" [PBP-2022
  Readme].
- **Malformed rows have happened.** At 21:46 on 2022 night, MonAvenir area 4 showed `polls:"0"`,
  `pollsReceived:"539"`, `totalVoters:"0"`, `votesReceived:"411"` and no candidates. **OBSERVED**
  [WB-2022]. The parser must tolerate `pollsReceived > polls`, an empty candidate list, and
  `votesReceived ≠ Σ candidates`. **INFERRED**

## 6. Does anything change on the night or at the end?

| Question | Finding | Label | Source |
|---|---|---|---|
| URL or filename change? | No: "The filename will not change on election night." Test and live use the same URL. | OBSERVED | [MEDIA FAQ] |
| Key set or shape change? | The key sets of the 2018, 2022 and 2026 all-office files are identical (`electionDesc`/`office`/`seq`; `id`/`name`/`ward`; the ward and candidate keys). The City promises nothing about this. | OBSERVED (history); not stated | [WB-2018], [WB-2022], [TEST-A] |
| Offices present | Only the offices on the ballot appear. The 2023 mayoral by-election file had only Mayor; the 2023 Ward 20 by-election file had only Councillor, with one ward. For 2026 the spec states six offices. | OBSERVED | [WB-2023b], [WB-2023W20], [SPEC p4] |
| Candidate order | Changes every refresh (sorted by votes) | OBSERVED | [MEDIA FAQ] |
| Ward and office order | Stable (`num` ascending, office id 1–6) in every file seen. Not documented. | OBSERVED (files); not stated | [TEST-*], [WB-*] |
| `polls`, `totalVoters` during the night | Constant through the 2023 night (1,451 / 1,880,172 at 20:26, 21:24 and final). They may still change before election day: "Both values are subject to change as we approach election day." | OBSERVED | [WB-2023a–c], [MEDIA FAQ] |
| End of count | "Updated every 60 seconds, starting from 8 p.m. until all results have been received. There is no fixed end time." | OBSERVED | [MEDIA FAQ] |
| File after the end | It freezes and stays at the URL. 2023: final `seq` 23:37:21 EDT (1,451/1,451) was still served at 11:07 EDT the next day. 2018: final `seq` 2018-10-23 00:13 EDT (1,800/1,800), a capture on 2019-11-12 has the same content digest. 2023 Ward 20 file (`seq` 2023-11-30) still served 2024-05-23. | OBSERVED | [WB CDX], [WB-2023c], [WB-2018] |
| "Count complete" signal | None explicit. Completion has to be read as `pollsReceived == polls` per race or office, plus `seq` no longer advancing. Generation stops after completion, since the last `seq` stays frozen. | INFERRED | [WB-2023c], [WB-2018] |
| Official or final results file | The FAQ was asked "will there be a final data file with official results?" and answered only the filename part. Certified results go to Open Data later. | OBSERVED (non-answer) | [MEDIA FAQ] |
| Count duration (history) | 2023: 84% of polls by 20:26, 97% by 21:24, last `seq` 23:37. 2022: 92.9% of polls by 21:46. | OBSERVED | [WB-2023a–c], [WB-2022] |
| Post-night corrections | 2018: 10 subdivisions' tabulators "applied the reporting of the vote counts to another subdivision on election night" in the same ward. It was corrected in the certified file on Nov 30, 2018; ward totals were unaffected. | OBSERVED | [PBP-2018 Notice sheet] |

## 7. Test schedule

| Date | Event | Label | Source |
|---|---|---|---|
| Sept 17, 2026 | Zeroed files posted ("Files will have list of candidates and all races") | OBSERVED | [PRES slide 10], [MEDIA FAQ] |
| **Sept 28, 2026, 8–10 p.m.** | "System test with live data will be made available, starting at 8 pm and ending at 10 pm." **This is in the past.** The current files' `seq`/`Last-Modified` (2026-09-28 22:04:41 EDT) show they were regenerated, zeroed, about 4 minutes after the window closed. | OBSERVED (schedule, timestamps); INFERRED (reset after test) | [PRES slide 10], [TEST-A], [HDR] |
| Oct 26, 2026, after 8 p.m. | Live | OBSERVED | [PRES slide 10] |

- No further non-zero test is listed in the presentation, the spec or the media page (the media
  page was last modified Sept 21, 2026). **OBSERVED**
- Whether the Sept 28 test carried non-zero vote counts or only "live" file generation is **not
  stated**. No capture of it exists: the Wayback CDX has no capture of either URL after
  2024-05-23. **OBSERVED** [WB CDX].
- The only realistic non-zero fixtures available are therefore the archived real files from 2018,
  2022 and 2023 (§ Sources), plus synthetic files. **INFERRED**

## 8. Rate limits and caching

- **Stated:** "Reasonable rate limits and traffic controls are in place … Consumers should poll
  responsibly and design integrations to accommodate service protection controls, transient
  throttling, and network failures. Polling more frequently than the publication interval is not
  recommended." No numeric limit is given. **OBSERVED** [MEDIA FAQ].
- **Recommended:** "Consumers should use ETags, Last-Modified headers, and Cache-Control directives
  … Applications can also use the JSON sequence (seq) value … Avoid unnecessary cache-busting
  techniques." **OBSERVED** [MEDIA FAQ].
- **Headers observed** on 2026-10-05 at 17:59 UTC, one request per URL [HDR] **OBSERVED**:
  - `cache-control: must-revalidate, max-age=0, s-maxage=0`
  - `etag: "293a85745e2a871b265a1259ff32de8a"` (all-office) and `"83a35b2c5ca89cf94777647cfdb9c659"`
    (ward-by-ward), both quoted 32-hex
  - `last-modified: Tue, 29 Sep 2026 02:04:42 GMT`
  - `content-type: application/json`, `accept-ranges: bytes`
  - `x-cache: Hit from cloudfront` / `RefreshHit from cloudfront`
  - `vary: Accept-Encoding`; brotli (`content-encoding: br`) is served when requested
  - A conditional GET with `If-None-Match` returned **`304`**
  - No `Access-Control-Allow-Origin`; `cross-origin-resource-policy: same-origin`
- **Implications:** a 60 s conditional-GET poller (ETag) is the intended pattern. CloudFront
  revalidates with the origin on every request (`s-maxage=0`), so freshness is bounded by the
  City's push cadence, not by a CDN TTL. **INFERRED**

## 9. Where the documents and the files disagree

| # | Documents say | Files show | Source |
|---|---|---|---|
| 1 | The Mayor office's ward example is "Etobicoke North" ([PRES slide 7]). The spec never says how mayor is represented in the all-office file. | Mayor has one ward, `{"name":"City-wide","num":"0"}` | [TEST-A], [WB-*] |
| 2 | Slide 8: ward-by-ward `"office" : [ … ]` (array) | `office` is an object, as spec p7 says | [TEST-W] |
| 3 | Spec p6 example `"totalVoters" : "78,411"` (comma, curly quote); slides use curly quotes | No commas, straight quotes, in every file (2018–2026) | [TEST-A], [WB-*] |
| 4 | Spec p4 example `"electionDesc" : " 2026 Election"`; p7 `"2026 Election"` | `"2026 Municipal Election"` | [TEST-A] |
| 5 | Spec p5 lists the property as `Ward` | The key is `ward` (lower case) | [TEST-A] |
| 6 | Spec p6 `percentage` example `"0.01"` (for 56 votes; scale unclear) | A 0–100 scale with 2 dp (`"63.49"`) | [WB-2018] |
| 7 | Spec p6: school-board wards have "no name" | The `name` key is omitted entirely | [TEST-A] |
| 8 | Spec p6 candidate example `" John Doe "` (padded) | No padding anywhere | [TEST-A] |
| 9 | Spec gives no types | Every number is a string except `office[].id` (an integer) | [TEST-A], [TEST-W] |
| 10 | Implied: each office's `totalVoters` is its own electorate | **2026 school-board `totalVoters` equal the City-ward value with the same `num`** (TDSB 1 = TCDSB 1 = Ward 1 = 78,411; Viamonde total 302,568; MonAvenir total 205,014). In 2018 and 2022 they were board-specific (2022 TCDSB total 333,112; Viamonde 5,104). Every TDSB area has more `polls` than any single City ward (smallest TDSB area: 86; largest City ward: 82), so they span several wards, yet each carries one ward's `totalVoters`. | [TEST-A], [WB-2018], [WB-2022] |

Row 10 is most likely a defect in the 2026 file builder. Until it is shown fixed on Oct 26,
trustee `totalVoters` must not be used as a turnout or progress denominator. **INFERRED**

## 10. Unknown or not stated

1. **Numeric rate limit** and the throttling response (429? 403? its body?). Not stated, not
   observed.
2. **Whether the Sept 28 test contained non-zero votes**, and whether any other test push will
   happen before Oct 26. Not stated; no capture exists.
3. **When mail (97) and advance (98/99) are loaded on the night**, and whether they come before or
   after election-day polls. The City says only "following the close of polls". 2023 history
   suggests interleaving (§4, INFERRED).
4. **Whether 2026 has a 96 (long-term-care) aggregate** or special codes beyond 97–99. The feed
   cannot show this; the arithmetic suggests not (§3, INFERRED).
5. **The meaning of `totalVoters`** (voters' list at which date; whether election-day additions
   are included). Not defined. History shows it constant through the night.
6. **Whether school-board `totalVoters` will be corrected** before Oct 26 (§9 row 10).
7. **The mapping between school-board areas and City wards.** It is not in the feed, and must
    come from elsewhere. Poll counts show most areas span several City wards. **INFERRED**
8. **Rejected, declined and blank ballots, and total ballots cast.** Not in the feed. Turnout
   cannot be computed from it.
9. **An explicit "race complete" or "count complete" flag.** None exists. The end of updates has
   no fixed time, and there is no promise of a final file.
10. **Shape stability.** No versioning or change notice is promised, beyond "critical messages"
   posted on the media page.
11. **Whether the two files are generated atomically together.** `seq` differs by milliseconds; a
    simultaneous count is not guaranteed.
12. **Whether `pollsReceived` can decrease or votes be revised downward during the night** (for
    example, a reloaded subdivision). Not stated; not observed in the four captures available.
13. **Retention after Oct 26.** History says the file stays up for months, but the City does not
    say so.
14. **Trustee withdrawal status.** The trustee registry was not checked (only mayor and
    councillor were).

## Sources

- **[SPEC]** City of Toronto, *2026 Toronto Municipal Election JSON Unofficial Result Files: Data
  Specifications*, v1.1 (2026-09-01), PDF created 2026-09-16, 9 pp.
  <https://www.toronto.ca/wp-content/uploads/2026/09/96f1-MediaJSONUnofficial-ResultsDataSpecificationsFor-Web.pdf>.
  Page numbers are the PDF's own.
- **[PRES]** City of Toronto, *2026 Toronto Municipal Election Media Technical Briefing: How to
  Access Election Night Results*, Sept 16, 2026 (PDF modified 2026-09-21), 11 slides.
  <https://www.toronto.ca/wp-content/uploads/2026/09/96ed-2026Unofficial-ResultsMediaPresentationfor-Web.pdf>
- **[MEDIA]** / **[MEDIA FAQ]** *Live Results Information for Media* ("Date modified: September 21,
  2026"), fetched 2026-10-05, "Frequently Asked Questions" section.
  <https://www.toronto.ca/city-government/elections/election-results-reports/election-results/live-results-information-for-media/>
- **[TEST-A]** / **[TEST-W]** The zeroed live files
  `https://mediaresults.toronto.ca/results/unofficialresult.json` (48,961 B, `seq`
  1790647481807) and `…/unofficialresult-wardbyward.json` (294,674 B, `seq` 1790647481787),
  downloaded 2026-10-05. HEAD content-lengths matched, so these are the current versions.
- **[HDR]** One-off `curl -sI`, one conditional GET and one `Accept-Encoding` HEAD against both URLs,
  plus one plain-HTTP HEAD, all on 2026-10-05 at about 17:59–18:00 UTC.
- **[WB CDX]** Wayback Machine index of `mediaresults.toronto.ca/results/*`:
  <https://web.archive.org/cdx/search/cdx?url=mediaresults.toronto.ca/results/*&output=json>.
  Captures used (raw via `id_`):
  - **[WB-2018]** `20181029172648` (all-office, final 2018) and `20181029172755` (ward-by-ward)
  - **[WB-2022]** `20221025014628` (all-office, 2022 night, `seq` 21:46:01 EDT)
  - **[WB-2023a]** `20230627002639` (ward-by-ward, 2023 mayoral by-election, `seq` 20:26:22 EDT)
  - **[WB-2023b]** `20230627012426` (all-office, `seq` 21:24:21 EDT)
  - **[WB-2023c]** `20230627150743` (all-office, final, `seq` 23:37:21 EDT)
  - **[WB-2023W20]** `20240523191854` (all-office, Ward 20 by-election, `seq` 2023-11-30)

  URL pattern: `https://web.archive.org/web/<ts>id_/https://mediaresults.toronto.ca/results/<file>`
- **[PBP-2018]**, **[PBP-2022]**, **[PBP-2023]** City certified poll-by-poll mayoral workbooks
  (City Open Data), vendored in `~/code/personal/toronto-election-results/data/`:
  - `raw/results/extracted/2018/2018_Toronto_Poll_By_Poll_Mayor.xlsx` (with the "Notice" sheet)
  - `interim/results/2022/2022_Toronto_Poll_By_Poll_Mayor.xlsx` (plus `Readme.txt`)
  - `raw/byelection/2023_office_of_the_mayor.xlsx` (with the "Read Me" sheet)
- **[VS-2022]** City 2022 voter turnout statistics, "readme" sheet, "Sub" row:
  `~/code/personal/toronto-election-results/data/raw/voter_stats/2022_voter_turnout_statistics_final.xlsx`
- **[REG]** City candidate registry, fetched 2026-10-05:
  <https://www.toronto.ca/data/elections/candidate_list/mayorCandidates_2026.json>,
  <https://www.toronto.ca/data/elections/candidate_list/councilorCandidates_2026.json>
- **[FACT]** *Fact Sheet: 2026 Toronto Municipal Election*, Sept 22, 2026:
  <https://www.toronto.ca/news/fact-sheet-2026-toronto-municipal-election/>
- **[NOM]** *Municipal election candidate nominations close tomorrow*, Aug 20, 2026:
  <https://www.toronto.ca/news/municipal-election-candidate-nominations-close-tomorrow/>
- **[CAND]** *Become a Candidate*:
  <https://www.toronto.ca/city-government/elections/candidates-third-party-advertisers/candidate-information/become-a-candidate/>

## Self-critique

- **Whether history applies.** The 2018–2023 behaviour (percentage scale, sort order, freeze at
  the end, aggregates counted as polls) comes from the same City system and the same spec lineage
  (spec version history 0.1 2018 → 1.1 2026). A rebuild could still change it silently. The 2026
  school-board `totalVoters` defect shows the 2026 builder is not identical.
- **The subset-sum timing result** assumes the night's per-subdivision tallies equal the certified
  ones. The final totals match exactly in 2023, but compensating per-subdivision differences
  cannot be ruled out. Treat the per-ward "must have reported / must be out" calls as strong but
  not certain.
- **Wayback captures are sparse** (one or two per night) and may come from cached CloudFront
  edges. They show states the feed was in, not every transition.
