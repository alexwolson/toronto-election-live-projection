# On-night runbook

For Alex, alone, on a phone in Korea, on Tue Oct 27 KST (#17 § On the night). The system runs
unattended and fails closed race by race. You only need to act if a reader would otherwise see
something wrong.

**Times.** Korea is 13 hours ahead of Toronto. `night status` prints Toronto time (EDT): add 13
hours.

| KST, Tue Oct 27 | EDT, Mon Oct 26 | |
|---|---|---|
| 08:30 | 19:30 | You're reachable |
| 09:00 | 20:00 | Counting starts |
| about 10:00 | about 21:00 | Most votes are in |
| 10:30 | 21:30 | You're out of reach |
| about 14:00 | about 01:00 Tue | The tail ends |
| evening | morning Tue | Night Close |

**Nothing deploys on the night.** No image, no Frontend deploy, no `deploy` run. The only
actions are the switches, the page pause and Night Close.

## Before 08:30 KST

1. Open the GitHub app: this repo → **Actions**.
2. Run **night status** → `night`. Expect both heartbeats fresh and every switch `on`
   (see [Reading night status](#reading-night-status)).
3. Open Pushover: the night checks are quiet.
4. Log in to the Upstash console with 2FA, so the fallback is one tap away.
5. Open `https://projection.cityhallwatcher.com/results/`. Before 20:00 EDT it reads
   "Results from 8 p.m.".

## Alerts

The checks are on healthchecks.io and reach you through Pushover (docs/store.md § Calm alerts).
Each alert arrives once; none repeat.

### `reader-path` (sound)

**Means:** for 5 minutes, no pipeline has fetched the public `/live/results.json` with a heartbeat
under 5 minutes old. Readers already see the banner "We haven't been able to read the City's
results since …".

**Do:**
1. Run **night status** → `night`.
2. Both heartbeats stale: neither pipeline has a valid read of the City's files. Open the City's
   own results page.
   - If the City's page isn't moving either, the City feed is down or frozen. Do nothing: the
     banner is the right state.
   - If the City's page is moving and ours isn't for about 15 minutes, pause the page
     ([Page pause](#page-pause)), so readers go to the City's results.
3. A heartbeat fresh but the alert sounded: the route isn't serving a fresh payload (Vercel or
   the store). Open `/results/` on the phone. If it shows a recent "City count as of", it has
   recovered. If not, pause the page.

### `count-decrease` (sound)

**Means:** the citywide mayoral votes counted went down between two payloads from one pipeline.
The page shows the lower count, as the City serves it.

**Do:**
1. Run **night status** → `night`. Read **Count decreases**: the newest `citywide` row gives
   before and after.
2. Open the City's results page.
   - A small drop, or a drop the City's page shows too: the City corrected its count. Do nothing.
   - The count fell to zero or near it (the City regenerated the file as zeros, as in its
     Sept 28 test): do nothing for a few minutes. It returns when the City republishes.
   - It stays at zeros, or our count disagrees with the City's page: pause the page.

The check stays down after one signal, so a second citywide decrease is silent. Read **Count
decreases** in night status for anything after the first.

### `pipeline-fly` or `pipeline-do` (badge, no sound)

**Means:** that pipeline hasn't completed a tick within its check's grace period. Its platform
restarts it (the watchdog exits a stuck process), and the other pipeline carries on.

**Do:** run **night status**. If the other heartbeat is fresh, nothing more. If both are stale,
`reader-path` will sound: follow it. Don't redeploy.

### Ward or area count decreases (no alert)

They appear only in night status, under **Count decreases**, with scope `ward` or `area`. No
action.

## Reading night status

Actions → **night status** → Run workflow → store `night`. When the run is green, open it and
tap **Summary**. Sections, top to bottom:

- **Heartbeats.** Each pipeline's last valid read of both files, with its age. `stale` means
  over 5 minutes. One stale: that pipeline is down and the other carries the page. Both stale:
  readers see the banner.
- **Stored seq pair.** The City's time stamp on each file and its age. "City count as of" is the
  older one, as readers see it. An old `seq` alone is fine: the City hasn't published since.
  After the count ends, these ages tell you when Night Close is due.
- **Switches.** Each switch as the route reads it. `on (not set)` is on. Anything **bold** is
  off, including `off (unrecognized value …)`: a typo fails closed.
- **Night Close.** `Open.` until you declare it.
- **Withdrawals.** Races whose projection a check has withdrawn, with the machine reason. Readers
  see "No projection for this race right now" and the count. These lift by themselves when the
  feed recovers. No action. Reasons:
  - `polls_received_above_polls`, `polls_zero`, `polls_differ_from_bundle`: the race's `polls`
    figures are off; Reporting Progress is hidden.
  - `votes_received_mismatch`, `ward_votes_counted_mismatch`: totals don't add up.
  - `count_above_expected`: more votes than the ward could cast.
  - `ward_fields_differ`, `wards_differ_from_office`: the two files disagree.
  - `projection_numerics`: the model produced a bad number.
- **Count decreases.** Every decrease seen, newest first. `citywide` (bold) is the mayor race
  and sounded the alert; `ward` and `area` are silent.

## Switches

Each switch is a store flag that the route applies. A flip reaches readers in about 75 s. There
is no per-race switch, and every switch turns back on (docs/store.md § Switches).

**Which switch for which symptom:**

- **Mayor's Estimated Range looks wrong** (outside what's possible, jumping wildly, or out of
  line with the count): `mayor` off. The mayor card keeps the count and the Possible Range,
  worded "Projection paused for the mayor's race". (`mayor_variant` off does the same tonight:
  the payload carries no count-only band to fall back to.)
- **A Possible Range looks wrong:** no switch removes it, since it is arithmetic on the count,
  not a projection (docs/payload.md). If it misleads, pause the page.
- **Council ranges look wrong across races:** `council` off. Tiles read "Count only".
- **TDSB or TCDSB ranges look wrong:** `trustee` off.
- **More than one level looks wrong, or you can't tell which:** `projections` off. Every level
  shows its Live Tally only.
- **The tallies themselves are wrong, or the page is broken:** the page pause, below.

One race with an odd range is not a reason to flip a level: the checks withdraw single races by
themselves.

**Flip one:**
1. Actions → **switch** → Run workflow.
2. store `night`; the switch; `off` (or `on` to restore).
3. Run. Green means the store reads back what you set. The summary shows the read-back and the
   full night status.
4. After about 90 s, reload `/results/` and check the change.

A red run means the read-back differed or the store was unreachable. Use the
[Upstash console](#fallback-the-upstash-console).

A level that was switched off for the whole night at the Dress review stays off. Turning it on
mid-night would be untested (#17 § Rehearsal plan).

## Page pause

The last resort, for wrong tallies or a broken page. It replaces live results with "Live results
are paused. See the City of Toronto's results: [link]".

- **Pause:** Actions → **switch** → store `night`, switch `page`, `off`.
- **Resume:** the same, with `on`.

The page pause still needs a good payload in the store: the route keeps the last good copy
whatever happens (docs/store.md § Switches).

## Night Close

Declare it once **neither file has changed for 2 hours**. In night status, both rows under
**Stored seq pair** show ages of 2 h or more. Expect this on Tue Oct 27 evening KST.

1. Actions → **night close** → Run workflow.
2. store `night`, action `close`.
3. Run. The `flag` job reads back `closed`. Only then does the `shutdown` job destroy the two
   Night apps (`toronto-election-night-fly`, `toronto-election-night-do`) and check both are gone.
4. After about 90 s, reload `/results/`. Expect "Final unofficial count as of …", "Elected
   (unofficial)" on the leader of each race with every voting area in, and no Live status line or
   banner.

**Declared by mistake:** run **night close** with action `clear`. The page goes back to live
wording, but the Night apps stay destroyed and the count no longer updates. Only declare Night
Close when the count is over.

If the `flag` job is red, nothing was shut down. If the `shutdown` job is red, the flag is set
but an app may still run: tell an agent, or run `deploy/shutdown.sh night` from a laptop.

## Fallback: the Upstash console

When a workflow won't run (GitHub down, the app logged out, a red run).

1. Open `console.upstash.com` and log in with 2FA.
2. Open the Night database, `election-night`. Not `election-rehearsal`.
3. Open the **CLI** tab.
4. Type one command, exactly as below, and check the reply.

| To | Type |
|---|---|
| Turn a switch off | `SET switch:council off` |
| Turn it back on | `SET switch:council on` |
| Check it | `GET switch:council` |
| Pause the page | `SET switch:page off` |
| Resume the page | `SET switch:page on` |
| Night Close | `SET night_close closed` |
| Undo Night Close | `DEL night_close` |

The switches are `switch:mayor`, `switch:council`, `switch:trustee`, `switch:mayor_variant`,
`switch:projections` and `switch:page`. Values are `on` or `off`, lower case.

`SET night_close closed` from the console sets only the flag: the Night apps keep running.
Shut them down later with `deploy/shutdown.sh night` from a laptop.

## Each action and its Rehearsal run

Every action above is a workflow or console step that exists. Each has been run against the
Rehearsal store:

- **night status:** run 38087286581 (Oct 10).
- **switch,** each switch off then on: runs 38084223338 to 38084518577 (Oct 10, #49).
- **night close,** `close` with the shutdown, then `clear`: runs 38093180402 and 38093261131
  (Oct 10, #51).
- **Upstash console,** each switch and Night Close: not yet. The Full-night Rehearsal (#53) runs
  every switch each way from the console.
