# Rehearsal checklist

For the Full-night Rehearsal (#53, Mon Oct 19) and the Dress (#55, Wed Oct 21), then the Deploy
Freeze (#56). It covers every item in #17's fault script and pass checklist, each with its
expected observation (#17 § Rehearsal plan).

**How to use it.** Copy the sections for the Rehearsal into a comment on its issue. Under each
item, write what you saw after **Observed:** and tick it if it matches **Expect:**. Anything that
doesn't match is a defect: file it with a failing test.

Times are the night clock in Toronto time (EDT). At the Full night (speed 1, start 19:50 EDT)
it is also the wall clock. At the Dress (speed 4) one wall minute is four night minutes.

## Before every Rehearsal

This applies to Plumbing (#42) and the 48-hour real-feed poll (#47) as well.

- [ ] **Reset the Rehearsal store's `seq` pair.** The Mock Feed stamps the same `seq`s every
  Rehearsal (the night clock from Oct 26 19:50), so after one Rehearsal the store rejects the
  next one's pairs as older. In the Upstash console, database `election-rehearsal`, CLI tab:
  `DEL payload:seq` and `DEL count_decreases`. Keep `payload`: the route needs one.
  **Expect:** `GET payload:seq` returns nil, and the first pair the pipelines read is stored.
- [ ] **Switches on, Night Close open.** **night status** → `rehearsal`.
  **Expect:** every switch `on (not set)` or `on`; Night Close `Open.`
- [ ] **Resume `count-decrease`** in healthchecks.io (Rehearsal set): it stays down after a
  Rehearsal's first citywide decrease. **Expect:** all four Rehearsal checks up.
- [ ] **Image.** The **image** run's tag and digest, recorded on the issue.
- [ ] **Mock Feed.** The **mock-feed** run: that tag and digest; the start; the speed; the faults.
  **Expect:** before the start, both files are the zeroed test files, marked REHEARSAL, with
  304s on repeat requests (#83).
- [ ] **Rehearsal apps.** The **deploy** run: `rehearsal`, the same tag and digest, feed
  `https://toronto-election-mock-feed.fly.dev/results`, the preview's `/live/results.json` as the
  reader path, and this Rehearsal's own archive prefix as recorded on its issue
  (`rehearsal/plumbing/`, `rehearsal/real-feed-poll/`, `rehearsal/full-night/` or
  `rehearsal/dress/`). **Expect:** both digest checks green; the run's summary names that prefix.
- [ ] **Preview.** The Frontend preview reading the Rehearsal store, and its commit.
  **Expect:** `/results/` shows the "Rehearsal: not real results" bar and "Results from 8 p.m."
- [ ] **Phone.** Logged in to GitHub, Upstash (2FA) and Pushover; the preview open on cellular,
  wifi off.

## Full night (#53)

Mock Feed: `start 2026-10-19T19:50:00-04:00`, speed 1, faults `full-night` (#83). Every operator
action from the phone only. The fault times and payload details are in
[full-night-faults.md](full-night-faults.md).

### Feed faults

- [ ] **Live-looking data before 20:00** (19:50–20:00, the Sept 28 repeat).
  **Expect:** "Results from 8 p.m." and the Rehearsal bar, despite live-looking counts.
- [ ] **Counting starts** (20:00). **Expect:** tallies and Reporting Progress appear.
- [ ] **Per-race faults** (20:10–20:25). **Expect:** each race below as listed; every other race
  unaffected; night status lists the Withdrawals with these reasons.
  - [ ] `councillor-4`, a `"-"` vote: "No figures from the City for this race right now".
  - [ ] `tcdsb-3`, row missing: "No figures from the City for this race right now".
  - [ ] `councillor-6`, `pollsReceived` above `polls`: tally, "Voting areas: not available", no
    range; `polls_received_above_polls`.
  - [ ] `tdsb-5`, `polls: 0` in a TDSB area: as above, and every other trustee race keeps its
    range; `polls_zero`.
  - [ ] `councillor-7`, `polls` differs from the bundle: as above; `polls_differ_from_bundle`.
  - [ ] `councillor-8`, `votesReceived` one over the candidates' sum: tally, no range;
    `votes_received_mismatch`.
  - [ ] `councillor-10`, votes above the ward's electors: tally, no range; `count_above_expected`.
  - [ ] `councillor-12`, an unknown name: "Rehearsal Unknown" shown as written; the range
    continues; no Withdrawal.
  - [ ] `councillor-26`, a race not in the bundle: nothing shown.
  - [ ] `mayor`, Ward 5's `votesCounted` off by one: mayor tally, no Estimated Range;
    `ward_votes_counted_mismatch`.
  - [ ] `councillor-14`, a count decrease: the lower count, as served; a `ward` row in night
    status; no sound.
- [ ] **Faults lift** (20:25–20:30). **Expect:** every race back to normal; Withdrawals gone; a
  second `ward` decrease for `councillor-10`, badge only.
- [ ] **File regenerated as zeros mid-count** (20:30–20:40). **Expect:** every race at zero;
  `count-decrease` sounds once; night status shows a `citywide` row. Test the page pause here
  (Operator, below).
- [ ] **Counts return** (20:40). **Expect:** higher than before the zeros.
- [ ] **Long 304 run** (20:45–21:15). **Expect:** the count holds at "City count as of 8:45
  p.m."; no banner; heartbeats fresh.
- [ ] **Stalled `seq`** (21:20–21:30). **Expect:** the page holds the first count at the 21:20
  pair; no banner.
- [ ] **5xx burst** (21:35–21:45). **Expect:** the banner from about 21:40; `reader-path` sounds
  once at about 5 minutes; no `pipeline-*` alert.
- [ ] **403 throttle** (21:50–22:00). **Expect:** as for 5xx.
- [ ] **Timeouts** (22:05–22:15). **Expect:** as for 5xx.
- [ ] **Truncated body** (22:20–22:30). **Expect:** as for 5xx.
- [ ] **Renamed key** (22:35–22:45). **Expect:** as for 5xx.
- [ ] **One file failing, the other fine** (22:50–23:00). **Expect:** as for 5xx; the good file
  is never paired with an older copy of the other.
- [ ] **100% while votes still rise** (`councillor-13`, 23:37–01:37). **Expect:** "All voting
  areas in", no range, no Withdrawal; its votes still rise at 01:07 and 01:37.
- [ ] **Two-hour near-silent tail** (00:07, 00:37, 01:07, 01:37: one unit each). **Expect:**
  small changes, 304s between, no alerts.

### System faults

Run by an agent from a laptop; Alex watches from the phone. Leave a few minutes between faults
and keep them clear of the feed-fault windows above, for example in the tail after 23:40.

- [ ] **Stop the Fly pipeline:** `flyctl machine stop <id> -a toronto-election-rehearsal-fly`.
  **Expect:** the page keeps updating from DigitalOcean; night status shows `fly` stale and `do`
  fresh; the `pipeline-fly` badge within 5 minutes; no banner. Restore with
  `flyctl machine start <id> -a toronto-election-rehearsal-fly`: `fly` fresh again.
- [ ] **Stop both:** the **teardown** workflow. **Expect:** the banner on the page about 5
  minutes after the last heartbeat; `reader-path` sounds; both `pipeline-*` badges.
- [ ] **Restore both:** the **deploy** workflow with the same inputs. **Expect:** heartbeats fresh,
  the banner drops, the count resumes and never goes backwards. (A decrease across a restart is
  missed by design: docs/store.md § Calm alerts.)
- [ ] **Preview redeploy mid-count:** `vercel redeploy <preview URL>`. **Expect:** the route
  serves again within a minute of READY; the page's "City count as of" never goes back.

### Operator actions, phone only

Times are suggestions in the tail, clear of the faults.

- [ ] **Page pause** (20:30–20:40, during the zeros): **switch** → `rehearsal`, `page`, `off`,
  then `on`. **Expect:** "Live results are paused. See the City of Toronto's results: [link]"
  within 90 s, and the Live Tallies back within 90 s of `on`.
- [ ] **Every switch by workflow, each way** (about 23:40–00:05): `mayor`, `council`, `trustee`,
  `mayor_variant`, `projections`, `page`, each `off` then `on`, one at a time. **Expect:** each
  run green; each change on the page within 90 s, worded as docs/store.md § Switches:
  - `mayor` off: the mayor card shows the count and the Possible Range, "Projection paused
    for the mayor's race".
  - `council` off: "Projection paused for council races"; tiles "Count only".
  - `trustee` off: "Projection paused for school board trustee races".
  - `mayor_variant` off: no Estimated Range, the Possible Range, the paused wording.
  - `projections` off: all three levels paused.
  - `page` off: the page pause.
- [ ] **Every switch from the Upstash console, each way** (about 00:10–00:35): `SET switch:<name>
  off`, then `on`, for the same six. **Expect:** as for the workflow; night status agrees.
- [ ] **Night Close** (03:37 or later: two night-clock hours after the last unit at 01:37).
  The `seq`s carry Oct 26 times, so night status can't show their age before Oct 26: go by the
  clock. **night close** → `rehearsal`, `close`. **Expect:** the `flag` job reads back
  `closed`; the `shutdown` job destroys both Rehearsal apps; within 90 s the page shows "Final
  unofficial count as of …", "Elected (unofficial)" on each fully reported race's leader, and
  no Live line or banner. Then **night close** → `clear`, so the next Rehearsal starts open.

### Pass checklist

- [ ] **Every fault produced the reader state #9 decided.** **Expect:** every item above ticked.
- [ ] **Exact tallies.** Every published Live Tally equals the Mock Feed's true count for its
  snapshot, exactly, in every race and every snapshot. Check each archived payload against
  `MockFeed.reference(a_seq, w_seq)`, built with the deployed start, speed, seed and fault script
  (full-night-faults.md § Exact tallies). **Expect:** zero mismatches.
- [ ] **Byte-identical archives.** List `payloads/` under this Rehearsal's prefix in both buckets
  (Tigris and Spaces). **Expect:** every `seq` pair in both buckets has one hash, except the
  stalled 21:20 pair.
- [ ] **The client never shows an older `seq` pair.** **Expect:** the phone's "City count as of"
  never goes back all night, including across the preview redeploy and the restore.
- [ ] **Each switch flip reaches a phone on cellular within 90 s** (75 s expected).
  **Expect:** every flip timed from the run going green to the page changing, all under 90 s.
- [ ] **Each alert reaches the phone within 5 minutes.** **Expect:** every Pushover alert timed
  from its fault's start, all under 5 minutes: `count-decrease`, `reader-path`, `pipeline-fly`
  and both `pipeline-*` when both stop.
- [ ] **Tick time and memory.** **Expect:** each tick's log line (`logs/<pipeline>/` in the
  archive, or `flyctl logs`) lands within a few seconds of its slot (Fly on the minute,
  DigitalOcean at :30), even in the 20:00–20:30 burst; Fly's and DigitalOcean's memory graphs
  stay flat from 20:00 to Night Close.
- [ ] **The archive is kept.** **Expect:** its prefix recorded on #53.

## Dress (#55)

Mock Feed: a start of your choosing, speed 4 (about 90 minutes), faults `off`. The exact image
digest and Frontend commit intended for the night.

- [ ] **The digest and Frontend commit,** recorded on #55. **Expect:** the same digest on the
  Mock Feed and both Rehearsal apps; the preview built from the commit that `main` will
  fast-forward to.
- [ ] **A clean count.** **Expect:** before 20:00 "Results from 8 p.m."; the count runs to
  "All voting areas in" everywhere; no Withdrawals; no alerts.
- [ ] **One pipeline stopped:** stop the Fly Machine, then start it, as in the Full night.
  **Expect:** DigitalOcean carries the page; the `pipeline-fly` badge within 5 minutes; `fly`
  fresh again after the start.
- [ ] **One flip of each switch,** off then on, by workflow. **Expect:** each change on the phone
  within 90 s, worded as in the Full night.
- [ ] **Night Close,** two night-clock hours after the last unit: 30 wall minutes at 4×.
  **Expect:** as in the Full night; then `clear`.
- [ ] **Pass checklist:** exact tallies, byte-identical archives, never an older pair, ticks
  well under 60 s. **Expect:** as in the Full night.
- [ ] **The no-op forecast-only release** on the current tag, timed from start to end
  ([forecast-only-release.md](forecast-only-release.md)). The Night apps don't exist before the
  Deploy Freeze, and production stays on the build before it, so:
  - step 1 is skipped (the current tag);
  - step 2 stops at the preview with the current tag;
  - step 3's `git diff --stat` is empty, and the check lists the same two names; build the
    image from the frozen commit;
  - step 4 runs as written;
  - step 5 deploys the Rehearsal apps, not the Night apps.

  **Expect:** every step green; the total time recorded on #55.
- [ ] **The fallback ladder,** decided by Alex at the review, per level: switched off for the
  night, or the live page doesn't launch. **Expect:** recorded on #55.

## Deploy Freeze (#56, Fri Oct 23 18:00 EDT)

- [ ] **`main` fast-forwards to the Dress commit** (Frontend, S8). Alex previews that build.
  **Expect:** the preview at the Dress commit.
- [ ] **Seed the Night store** before the production build (Frontend `docs/v2-release.md` § The
  live results route), with `REDIS_URL` the Night store's. **Expect:** `payload`, `payload:seq`,
  `heartbeat:fly` and `heartbeat:do` present; the keys posted on #56.
- [ ] **Production Frontend deploy,** after Alex's go. **Expect:** READY;
  `https://projection.cityhallwatcher.com/live/results.json` answers 200.
- [ ] **Night apps by digest:** **deploy** → `night`, the Dress's tag and digest, feed
  `https://mediaresults.toronto.ca/results`, reader path
  `https://projection.cityhallwatcher.com/live/results.json`. **Expect:** both digest checks green;
  night status → `night` shows both heartbeats fresh.
- [ ] **The freeze gate (#40).** Copy the Dress's payloads from both buckets, then:

  ```bash
  uv run election-night freeze-gate --archive dress/fly --archive dress/do \
    --frontend-commit <production build's full SHA> \
    --backend-release-tag <the tag given to npm run deploy:production>
  ```

  The copy commands are in the README § Freeze gate. **Expect:** exit 0 and no `FAIL` lines;
  the output posted on #56.
- [ ] **The soak begins** on the real City feed. **Expect:** "before results" on the production
  page; heartbeats fresh daily; an unannounced City test push leaves the page in "before
  results"; every Ballot Name in the City's files matches the bundle (the payload compares them
  on every count; for the mayor, a mismatch turns the variant off with `forecast_unmatched`).
- [ ] **Pre-departure check,** Sat Oct 24 morning. **Expect:** the Night apps current on the
  soak, all Night checks green in healthchecks.io, and phone logins working: GitHub, Upstash
  with 2FA, Pushover. Recorded on #56.
