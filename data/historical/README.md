# Historical inputs

The City of Toronto's certified poll-by-poll results and voter statistics for the replayed nights
(2014, 2018 and 2022 general elections, and the 2023 by-election for mayor), plus the advance-vote
turnout that was public before each of those nights. The Replays, the Mock Feed and the expected
totals read these files (spec #17, S9 and S5; ticket #20).

## Licence

The results and voter statistics are published on the City's open data portal under the
[Open Government Licence – Toronto](https://open.toronto.ca/open-data-licence/). Each of the four
dataset pages lists it under "Licence" (checked 2026-10-07):
[election-results-official](https://open.toronto.ca/dataset/election-results-official/),
[elections-official-by-election-results](https://open.toronto.ca/dataset/elections-official-by-election-results/),
[elections-voter-statistics](https://open.toronto.ca/dataset/elections-voter-statistics/) and
[elections-by-election-voter-statistics](https://open.toronto.ca/dataset/elections-by-election-voter-statistics/).
The portal's CKAN API reports "License not specified" for the same datasets; the dataset pages are
the authority. Attribution, as the licence requires:

> Contains information licensed under the Open Government Licence – Toronto.

`advance_turnout/` holds figures transcribed from City releases and news reports, not copies of
those pages.

## Contents

| Path | What it is |
|---|---|
| `results/2014/` | Mayor, councillor, TDSB and TCDSB workbooks (legacy `.xls`, one sheet per ward) |
| `results/2018/`, `results/2022/` | The same four offices (`.xlsx`); 2022 also has the City's `Readme.txt` |
| `results/2023/` | The 2023 by-election for mayor (`.xlsx`, with a `Read Me` sheet) |
| `voter_statistics/` | Per-subdivision electors and voters for each night, and the City's readmes |
| `advance_turnout/advance_turnout_as_released.csv` | Advance-vote turnout as first published before each night |
| `sources.csv` | For every open-data file: dataset, download URL, sha256 of the downloaded file, zip member, City's last-modified date |
| `SHA256SUMS` | Checksums of every data file above |

The files are unmodified. The 2014, 2018 and 2022 workbooks, and the 2018 voter statistics, are
members of City zip files; `sources.csv` names the zip and its sha256. Left out of those zips: the
French-language board workbooks (tally-only on the night, so never replayed) and
`2022_Toronto_Poll_By_Poll_All_Offices.xlsx`, which repeats the four single-office 2022 files cell
for cell (research 03, §1).

The City publishes one `readme.xls` in both voter-statistics datasets; the two downloads are
byte-identical, so it is vendored once as `voter_statistics/voter-statistics-readme.xls`.

Everything was downloaded from the City's CKAN on 2026-10-07. Each download is byte-identical to the
copy in the canonical `toronto-election-results` repo (`data/raw/`), which research 03 parsed and
reconciled.

## Verify

```bash
(cd data/historical && shasum -a 256 -c SHA256SUMS)   # Linux: sha256sum -c SHA256SUMS
```

`tests/test_historical_data.py` checks the same thing, that every open-data file has a row in
`sources.csv`, and that every advance-turnout row has a source.

## Advance-vote turnout, as released

Spec #17's S5 sizes each replayed night's Ward Aggregates (the advance and mail units, codes 97–99)
from what was public before that night, taking the first available of: a ward table, else the
citywide figure split by historical ward shares, else historical shares alone.

| Night | Election | Released figure | Published | Source | Final figure in City reports |
|---|---|---:|---|---|---:|
| 2014 | Oct 27 | 161,147 citywide | Oct 20, 2014 | The Globe and Mail ([archived](https://web.archive.org/web/20141024050440/http://www.theglobeandmail.com:80/news/toronto/turnout-at-toronto-advance-polls-sets-record/article21173457/)) | 161,147 |
| 2018 | Oct 22 | 124,306 citywide | Oct 15, 2018 | CBC News ([archived](https://web.archive.org/web/20181015211524/https://www.cbc.ca/news/canada/toronto/advance-voter-turnout-municipal-election-2018-1.4863816)); Global News gives the same figure | 124,299 |
| 2022 | Oct 24 | 115,911 citywide | Oct 15, 2022 | [City release](https://www.toronto.ca/news/turnout-for-2022-toronto-municipal-election-advance-vote/) | 115,899 |
| 2023 | Jun 26 | 129,745 citywide; ward table | Jun 14 (city), Jun 15 (wards), 2023 | [City release](https://www.toronto.ca/news/advance-vote-turnout-for-the-2023-by-election-for-mayor/); [ward table PDF](https://www.toronto.ca/wp-content/uploads/2023/06/98ae-1.1-Advance-Vote-Turnout-Ward-by-Ward.pdf) | 129,745 |

Use the released figure, not the final one: a replay may only know what was public at the time.

- **2014 has a dated pre-election source, but only a press one.** S5 gives 2014 historical shares
  unless a dated pre-election source is found. This one would put 2014 on the citywide figure like
  2018 and 2022. Whether a press report counts is a decision for the pre-registration (#23), not
  this data. The Globe and Mail
  published 161,147 on Monday, Oct 20, 2014 (2:51 p.m. EDT), quoting the City Clerk. CP24 the same
  day quoted the Clerk's written statement as "more than 160,000". The City's own release is no
  longer online, and the backend's earlier research note
  (`toronto-election-poll-tracker-backend/docs/research/advance-voting-and-forecast-target.md`)
  had not found a dated 2014 source.
- **2018 rests on press reports.** The City's 2018 release is no longer on toronto.ca and was not
  found in the Wayback Machine. CBC News (archived 2018-10-15 21:15 UTC) and Global News (Oct 15)
  both report 124,306 as newly released City figures.
- **2023 ward table.** Transcribed from the City's PDF (sha256
  `439ce628620671382bce3dcf05d01891e5ffaf0a2cd5acaec610fe666b3e19dc` on 2026-10-07). Its 25 ward
  figures sum to the citywide 129,745. The published date is the PDF's creation date, matching the
  backend research note's "ward totals added June 15".
- **Mail** (code 97) always uses historical shares under S5, so no mail figure is recorded.

The voter-statistics workbooks count advance voters slightly differently from the City's reports
(2014: 161,173; 2023: 129,648; research 03, §3).
