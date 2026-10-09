# 0001 — 2023 takes half the weight of the mayoral fit

**Status:** accepted (Alex, 2026-10-09) · **Ticket:** #36

## Decision

Whenever 2023 is a training night, it takes 50% of the weight in every mayoral count-extension
parameter (`fit_mayor`: κ, unit-size CV, τ, ω_city, ω_ward). The other nights share the other
50% in their usual pooled proportions. Without 2023, every night keeps its pooled share.
Council, trustee and the expected-total inputs are not weighted.

## Why

Alex expects 2026's voter dynamics to resemble the 2023 by-election more than 2014–2022. 2023's
early vote differed from its election-day vote far more than on any other night: Bailão 37.5% on
election day against 14.2% in advance and mail, and Chow 34.3% against 47.4%. That gives a shift
spread v of 0.103, against 0.003–0.033 on 2014–2022.

## This is an assumption, not a fit

- The record does not identify this weight. It was set by judgement, and nothing here may cite
  a replay score to support it (ADR 0030).
- The Replays can't validate it. The 2023 fold leaves 2023 out by construction, so the weight
  never touches the Bailão check (criterion 6). It does change the 2014, 2018 and 2022 folds,
  which are scored with it.

## Alongside

On the same date, the citywide early-vote shift's spread became uncertain per draw. It is drawn
from a scaled-inverse-chi-squared distribution whose degrees of freedom are the fit's effective
(Kish) number of nights (`omega_city_nu`). This is the standard treatment of a variance estimated
from a few observations, and it is not an assumption about 2026.
