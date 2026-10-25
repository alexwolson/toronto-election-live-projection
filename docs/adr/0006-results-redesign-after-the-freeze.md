# 0006 — The results redesign ships after the Deploy Freeze

**Status:** accepted (Alex, 2026-10-24/25) · **Amends:** the Deploy Freeze (CONTEXT.md), for the
Frontend's results pages only; ADR 0003, for races with every voting area in

## Decision

Alex lifted the Deploy Freeze once, for the Frontend's results pages: the approved redesign
replaced the live results UI before the night, behind a Rehearsal and a go/no-go. The default
without a clean go was to keep production on the frozen build.

- **What changed:** the presentation layer only. The live results route, the switches, Night
  Close, the payload validator and the Night apps are unchanged. Every result page is now its own
  route: `/results/` (mayor, council, map, school boards), one page per ward
  (`/university-rosedale/`), `/tdsb/<n>/`, `/tcdsb/<n>/`, and `/conseils-scolaires/` (French and
  English). Old links (`/results/4/`, `?open=councillor-4`, `?open=viamonde-3`) redirect.
- **Rehearsal:** an accelerated Full-night Rehearsal on the Rehearsal store (Oct 24, speed 8,
  full-night faults) against the redesign's preview, ending in Night Close (run 40151000371,
  Rehearsal apps only). The Mock Feed was stopped afterwards.
- **Freeze gate:** the Dress archives weren't reachable from the machine doing the deploy. Alex
  accepted instead the gate run on two of the Rehearsal's payloads against the redesign commit:
  `freeze gate: 2 payloads pass at d9353bd…, backend-2026-10-24.1`. The final commit changed only
  French wording.
- **Production:** `main` at `89821a1` on `backend-2026-10-24.1`, deployment `87n17n9cz` (Oct 25,
  01:34 EDT). Rollback: promote `3hqk6q75k` (`ae27c87`, the frozen build), which builds nothing
  (Frontend `docs/v2-release.md` § Rollback).
- **A race with every voting area in reads as complete** (amends ADR 0003). Its leader's rivals
  are grouped under "Candidates below are mathematically eliminated" and greyed, the wording
  drops "leads" for "has N more votes than", and the catch-up chart is gone. It follows the race's
  state, so it reverts if the City's file reverts. A tie at the top groups no one. Nothing names
  a winner before Night Close's "Elected (unofficial)" ("Remporte le siège (non officiel)" in
  French).

## Why

- The approved design was ready, and the old results UI was the weakest part of the page.
- The risk sat in the presentation layer, which the Rehearsal exercises end to end, and the frozen
  build stays one promote away.
- With every voting area counted, no outstanding vote can change the order: calling the trailing
  candidates eliminated is arithmetic, as ADR 0003's badge is while counting.

## Consequences

- The runbook's page checks and Night Close expectations describe the new pages.
- A Frontend rollback is a promote, not a deploy. It is still not an on-night action unless the
  page itself is broken and the page pause doesn't cover it.
