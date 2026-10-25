# 0003 — A "Mathematically Eliminated" badge, read from the Possible Range

**Status:** accepted (Alex, 2026-10-10) · **Tickets:** #62, #90 · **Amends:** ADR 0002's "no
race-call wording", for this badge only · **Amended by:** ADR 0004 (2026-10-11): the mayor's
Possible Range, and so its badges, now stay while a ward's progress is hidden, and the
French-language boards' contested races get a range and badges; ADR 0006 (2026-10-25): a race
with every voting area in groups its leader's rivals as mathematically eliminated

## Decision

While a race is counting, a candidate who cannot win even if every outstanding vote went to them
carries a **Mathematically Eliminated** badge beside their name in the Live Tally. Alex chose to
show it although it comes close to a race call: late in a race it can leave a single candidate
unbadged.

- **The rule:** the candidate's votes plus the remaining electors are fewer than another
  candidate's votes, v + R < v′. A race's Possible Ranges share the denominator V + R, so this
  is the candidate's possible high below another candidate's possible low. A tie is not an
  elimination.
- **Read from the published Possible Range,** on the page. The payload rounds each bound to 2
  decimals, so the badge needs a gap of more than 0.01 pt. With that margin, rounding never badges
  a candidate who can still win.
- **It follows the Possible Range.** The badge appears on mayor, council and trustee races while
  they are counting. It never appears on the French-language boards or once all voting areas are
  in. It is also absent wherever the range is, for example on the mayor's race while a ward's
  Reporting Progress is missing. It stays through a Withdrawal, as the range does.
- **Named rows only.** The mayor's folded "N other candidates" row stands for many candidates and
  is never badged.
- **No win probability and no chance-to-win wording**, as before (ADR 0002). The badge is the one
  exception to "no race-call wording", and nothing marks a winner before Night Close's "Elected
  (unofficial)".

## Why

- **It is arithmetic, not a model.** It inherits the Possible Range's bound on the outstanding
  vote, every remaining elector. So it needs no gate, and it holds whatever the outstanding vote
  does.
- **Frontend only.** The payload already publishes everything the rule needs. Computing it there
  would change `payload.py`, which moves the model version and needs new Gate Results and a new
  mayoral approval before the Deploy Freeze.
