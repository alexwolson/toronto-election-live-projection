# Forecast-only release

After the Deploy Freeze, one release may change the final Mayoral Forecast the site and the
mayor's variant use (#17 § Rehearsal plan). Nothing else changes: not the code, not the page, and
never the names (#16).

**Hard stop: Sun Oct 25, 12:00 EDT (Mon Oct 26, 01:00 KST).** Anything not done by then is
dropped, and the frozen state stands. Nothing deploys on Oct 26.

It can be worked from Toronto, the plane or Korea: the image builds in GitHub Actions. The
Frontend steps need the laptop.

The Dress runs this procedure once as a no-op, on the current tag (#55).

## Before you start

- Note the frozen state, to roll back to: the production Vercel deployment URL, the Backend tag
  it pins (`/data/source-manifest.json` on the site), and the Night apps' image tag and digest
  (the Deploy Freeze's `deploy` run summary).
- The release is a new Backend tag from the same Results release. A forecast built from a
  different Results release fails step 3.

## 1. Backend release

Cut the Backend release as usual (Backend `docs/ROADMAP.md` → the data repo's poll ingestion
and release runbook), in a clean worktree, with its draws asset (S1). Check the tag is free
first: `gh release view <tag>` must fail.

**Done when:** `gh release view <tag>` lists `mayoral_forecast_draws.npz` and
`mayoral_forecast_draws.json`.

## 2. Frontend production deploy, tag only

The same Frontend commit as production, with only `BACKEND_RELEASE_TAG` changed (Frontend
`docs/v2-release.md`).

1. Preview: build the production commit on a preview with the new tag. Alex previews it.
2. On Alex's go, set the Production tag, then deploy:

   ```bash
   vercel env add BACKEND_RELEASE_TAG production \
     --value <tag> --sensitive --force --yes
   npm run deploy:production -- <tag>
   ```

**Done when:** the production `/data/source-manifest.json` names the new tag, and
`/live/results.json` still answers 200 (the route prerenders from the Night store at build).

## 3. Image rebuild, draws only

On a branch from the commit the frozen image was built from (its image tag is that SHA):

```bash
uv run election-night name-inputs --forecast-only --backend-release <tag>
uv run election-night bundle --forecast-only
git diff --stat
```

`name-inputs --forecast-only` replaces `mayoral_forecast.json` and the draws only. It fails if the
new forecast was built from a different Results release than `canonical-2026.csv`. Names are
never refreshed.

`bundle --forecast-only` reruns the forecast-id match to the bundle's mayoral rows. **A
forecast id that no longer sits on exactly one row turns the mayor's variant off for the night**
instead of failing the build. Check which happened:

```bash
jq '[.races[] | select(.id == "mayor") | .candidates[] | select(.candidate_id) | .short_label]' \
  data/night-bundle/night-bundle.json
```

It should list two names: the new forecast's leader and challenger. Fewer means the variant is
off, and the mayor will show no Estimated Range all night. Decide before going on: carry on with
the variant off, or stop and keep the frozen state.

The diff touches only `data/night-bundle/inputs/mayoral_forecast.json`, its draws,
`sources.json` and `night-bundle.json`. Anything else: stop.

Commit, push, and run the **image** workflow on that branch. Note the tag and digest from its
summary.

**Done when:** the image run is green, with one digest in all three registries.

## 4. Short accelerated Rehearsal

On the Rehearsal apps and store, with the new digest:

First reset the Rehearsal store and resume `count-decrease`, as in
[rehearsal-checklist.md](rehearsal-checklist.md) § Before every Rehearsal. Without it the store
rejects every Mock Feed pair as older than the last Rehearsal's.

1. **mock-feed** workflow: the new tag and digest, `start` a few minutes from now, `speed` 10,
   `faults` off.
2. **deploy** workflow: `rehearsal`, the new tag and digest, feed
   `https://toronto-election-mock-feed.fly.dev/results`, the preview's `/live/results.json` as
   the reader path, and the archive prefix `rehearsal/release-<YYYY-MM-DD>/` (today's date), so
   the check's payloads stay out of every Rehearsal's archive, the Dress's included.
3. Let it run past the burst (about 15 minutes at 10×).
4. Check:
   - **night status** → `rehearsal`: both heartbeats fresh, no unexpected Withdrawals.
   - The preview's `/live/results.json` has `forecast_release_tag` equal to the new tag.
   - The mayor's `projection.variant.in_effect` is `forecast_weighted`, or, if step 3 turned
     the variant off, its `off_reason` is `forecast_unmatched`.
   - The freeze gate passes on this Rehearsal's payloads against the production Frontend commit
     and the new tag (README § Freeze gate).
5. **teardown** workflow.

**Done when:** every check above holds.

## 5. Night apps, new digest

**deploy** workflow: `night`, the new tag and digest, feed
`https://mediaresults.toronto.ca/results`, reader path
`https://projection.cityhallwatcher.com/live/results.json`.

**Done when:** both digest checks are green, **night status** → `night` shows both heartbeats
fresh, and the production `/live/results.json` has `forecast_release_tag` equal to the new tag.

## At the hard stop

- **All five done:** the release stands.
- **Stopped before step 2:** nothing has changed. The frozen state stands.
- **Stopped after step 2, before step 5:** the site names the new forecast while the Night apps
  still use the frozen draws. Roll the site back: promote the frozen production deployment in
  Vercel and set the Production `BACKEND_RELEASE_TAG` back to the frozen tag. The frozen state
  stands.
- **Step 5 failed partway** (one provider on the new digest, one on the old): rerun **deploy**
  with the frozen tag and digest, then roll the site back as above.
