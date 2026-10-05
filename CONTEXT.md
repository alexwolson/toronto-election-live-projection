# Toronto Election Night

The language of election-night live results and projection for the 2026 Toronto municipal
election. Forecasting terms (Mayoral Forecast, Council Forecast, Final Ballot, Publication Gate and
others) are defined in `toronto-election-poll-tracker-backend/CONTEXT.md` and keep those meanings
here.

## Language

**Election-Night Projection**:
The predictive distribution of a race's complete unofficial count, conditioned on the partial unofficial count published by the City on election night. It is neither the Mayoral Forecast nor the Council Forecast, though it may start from one, and each office level (mayor, council, school-board trustee) is available only after qualifying on historical counts.
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
