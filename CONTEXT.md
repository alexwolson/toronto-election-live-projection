# Toronto Election Night

The language of election-night live results and projection for the 2026 Toronto municipal
election. Forecasting terms (Mayoral Forecast, Council Forecast, Final Ballot, Publication Gate and
others) are defined in `toronto-election-poll-tracker-backend/CONTEXT.md` and keep those meanings
here.

## Language

**Election-Night Projection**:
The predictive distribution of a race's complete unofficial count, conditioned on the partial unofficial count published by the City on election night. It is neither the Mayoral Forecast nor the Council Forecast, though the mayoral projection may lean on the final Mayoral Forecast while the count is thin, and each office level (mayor, council, school-board trustee) is available only after beating the Tally Baseline in Replays.
_Avoid_: Live forecast, live odds, race call

**Outstanding Vote**:
The valid votes in a race that are not yet included in the City's partial unofficial count.
_Avoid_: Remaining polls, uncounted ballots

### The count

**Count Snapshot**:
One generation of one of the City's election-night results files, identified by its sequence stamp.
_Avoid_: Update, refresh, poll

**Reporting Unit**:
One voting subdivision as the City's election-night count tallies it: either an election-day subdivision or a Ward Aggregate. The feed calls it a "poll", a word reserved here for opinion polls.
_Avoid_: Poll, voting place, precinct

**Ward Aggregate**:
A Reporting Unit carrying all of one ward's votes from a single non-election-day channel: advance, mail, or long-term care.
_Avoid_: Advance poll, special subdivision

**Reporting Progress**:
The share of a race's Reporting Units the City has received. It is not the share of the race's votes counted.
_Avoid_: Percent reported, polls reported, completeness

**Live Tally**:
A race's partial unofficial count as the latest Count Snapshot publishes it: each candidate's counted votes and shares, with the race's Reporting Progress.
_Avoid_: Live results, current results

**Ward Ballot**:
The races a voter in one City ward may find on their ballot: mayor, that ward's councillor, and the trustee area covering the ward on each school board. Any one voter votes in only one board's trustee race.
_Avoid_: Your ballot, ballot (alone; the Final Ballot is a set of candidates)

**Ballot Name**:
A candidate's name as the City prints it on the ballot and publishes it in the count, in the given-name and last-name parts the candidate filed. A single-name candidate has only a last name.
_Avoid_: Display name, feed name, registered name

### Going live

**Replay**:
A past election night re-run for scoring: its final Reporting Unit counts are revealed in a simulated arrival order, producing the Count Snapshots the Election-Night Projection would have seen.
_Avoid_: Backtest, simulation (the projection's own draws are simulations)

**Tally Baseline**:
The Live Tally read as a forecast of the complete count: every candidate finishes at their counted share and the current leader wins with certainty. An office level's Election-Night Projection goes live only by beating it in Replays.
_Avoid_: Naive model, current shares

**Gate Result**:
The frozen record of one office level's (or the mayoral variant's) Replays: pass or fail, the scores, and the model version it holds for. A level's Election-Night Projection may show only while a passing Gate Result matches the running model. The one exception is the mayor, live on Alex's approval of its failed Gate Results for the version they scored (ADR 0002).
_Avoid_: Scoreboard, qualification result

**Night Bundle**:
The fixed inputs election night runs on, baked into one image before the Deploy Freeze: frozen parameters, Gate Results, expected totals, Ballot Names and the pinned final forecast draws.
_Avoid_: Config, release

### Rehearsing

**Rehearsal**:
An end-to-end run of the night's system, from reading the count to the page readers see, against a Mock Feed before election night. Unlike a Replay, it tests how the system runs, not how accurate the projection is.
_Avoid_: Dry run, replay, test

**Mock Feed**:
A stand-in for the City's two election-night results files, serving Count Snapshots in their exact shape and on the night's clock for a Rehearsal. Its counts are invented for the purpose and never presented as real.
_Avoid_: Test feed (the City's own zeroed files), fake feed

**Deploy Freeze**:
The cut-off after which the night's code, image and page no longer change, apart from one scheduled forecast-only release before election day. After it, only the count changes what readers see.
_Avoid_: Freeze (alone; Night Close is not a freeze), code freeze

### On the night

**Withdrawal**:
An Election-Night Projection withheld from a race or an office level during the night by an integrity check or a switch, leaving the Live Tally. Unlike a level that failed its gate, it is temporary and can lift.
_Avoid_: Kill, outage, count only

**Estimated Range**:
A candidate's central 90% final-share range from the Election-Night Projection: where their final share lands in 9 of 10 simulated finishes. For the mayor it comes from the forecast-weighted variant, or count-only when the variant isn't in effect.
_Avoid_: Confidence interval, margin of error, prediction

**Possible Range**:
The mayor's final shares still mathematically possible for a candidate, from none of the outstanding votes going to them up to all of them. It assumes nothing about how the outstanding votes will split, and is shown beside the Estimated Range (ADR 0002).
_Avoid_: Worst case, best case, scenario

**Night Close**:
The declared end of election night, after which the City's count is treated as no longer changing and the page shows its final unofficial state. The City's feed has no completion signal, so it is declared, never inferred.
_Avoid_: Freeze, end of count, count complete
