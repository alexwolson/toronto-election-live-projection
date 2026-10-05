# Where the two election-night pipelines run

Research note for [#8](https://github.com/alexwolson/toronto-election-live-projection/issues/8). Written 2026-10-05.

Every load-bearing claim is labelled **OBSERVED** (seen in the source) or **INFERRED** (reasoned
from observations). **UNCONFIRMED** marks a gap the sources did not close. Source keys in square
brackets are listed under "Sources" at the end. Prices are list prices fetched on 2026-10-05, and
"2 weeks" means 336 hours (rehearsals from about Oct 13 through the night of Oct 26).

The workload is already fixed: one long-running Python process per host, using the same image
pinned by digest. It polls two City files every 60 s, archives each new version, runs a simulation
of about 1 s, and publishes to Upstash over HTTPS. Readers are served by Vercel iad1, and both
Vercel and Upstash run on AWS us-east-1.

## Summary

- **Recommended pair: Fly.io Machines in `yyz` (Toronto) and a Google Cloud Run worker pool in
  `northamerica-northeast1` (Montreal).** They are different companies on different hardware.
  Fly says it "runs its own hardware" and is "not an API layer on an existing public cloud".
  Neither host is on AWS, and each takes an image by `@sha256` digest from its CLI.
  **OBSERVED** (facts) [FLY-OWN], [FLY-REG], [CR-LOC], [CR-WP]. **INFERRED** (the choice).
- **Alternative pair: DigitalOcean App Platform worker in `TOR` and Google Cloud Run.** DO replaces
  Fly. If Google is the problem instead, Azure Container Apps in Canada Central replaces Google.
  **INFERRED**.
- **Cost: about $60–75 for 2 weeks** for the recommended pair at 2 vCPU / 4 GB. Fly
  performance-2x is about $30. The Cloud Run worker pool is about $28 at the default rate, more at
  Montreal's Tier-2 rate. Archive storage costs cents or nothing. **OBSERVED** (rates),
  **INFERRED** (totals).
- **Archive: each pipeline writes to its own provider's object store with write-once keys.** Fly
  uses Tigris, which supports `If-None-Match: *` and returns 412 on conflict. Google uses GCS,
  which needs `x-goog-if-generation-match: 0`: GCS does **not** honour `If-None-Match` on writes.
  Do not use volumes as the archive. **OBSERVED** [TIGRIS-COND], [GCS-COND], [FLY-VOL].
- **Surprising risks.** **OBSERVED** for the facts, as cited:
  1. **flyctl doubled a digest-form image ref** (`@sha256:X@sha256:X`) in v0.4.36, reported in
     April 2026 [FLY-DIGEST]. Whether the installed v0.4.111 fixes it is **UNCONFIRMED**.
  2. **Cloud Run caches GHCR images "for up to one hour"** [CR-REG]. A restart on the night may
     therefore pull from GHCR again, which makes GHCR a shared dependency of both legs
     (**INFERRED**).
  3. **A Fly Machine with a volume is tied to one host**, and Machines are not moved automatically
     when a host fails [FLY-VOL], [FLY-HOST].
  4. **Azure Container Apps cannot have a maintenance window on Consumption profiles.** Critical
     updates there can land "Anytime" [ACA-MAINT].
- **Local state:** `fly` v0.4.111 is installed but **not logged in**. No other provider CLI is on
  `PATH`, even in a login shell. **OBSERVED** [LOCAL].

## 1. Candidates dropped

| Candidate | Reason | Label |
|---|---|---|
| AWS App Runner | "No longer open to new customers" [AR-CLOSED] | OBSERVED |
| Koyeb | No Canadian region (nearest is Washington, D.C.) [KOYEB-REG]. Joining Mistral AI as of 2026-02-17 and moving into "Mistral Compute" [KOYEB-MISTRAL]: a roadmap risk for a 3-week dependency | OBSERVED / INFERRED |
| Render | "Much of Render" runs on AWS, including US East (Virginia and Ohio) [RENDER-AWS], so it is not independent of Vercel and Upstash. No Canadian region [RENDER-REG] and no object store. Digest deploys do work [RENDER-IMG]; 2c-4g costs $85/mo [RENDER-PRICE] | OBSERVED / INFERRED |
| Northflank | Its managed-cloud page does not say what hardware the regions run on [NF-CLOUD], so independence cannot be shown | OBSERVED / INFERRED |
| AWS Lightsail containers | Same AWS dependency as Fargate, with no advantage over it; 2 vCPU / 4 GB is $80/mo [LS-PRICE] | OBSERVED / INFERRED |

## 2. Runtime requirements

| Candidate | Always on, CPU between polls | CPU type, burst risk | Region nearest Toronto | Image by digest (CLI) | Restart + health | Maintenance, SLA | Underlying infra |
|---|---|---|---|---|---|---|---|
| **Fly.io Machines** | Yes, with restart policy `always` [FLY-RESTART]. No auto-stop without services (**INFERRED**) | `performance` gets 100% of each 80 ms period. `shared` gets 6.25% plus a burst balance of up to 500 s. A 1–2% duty cycle stays under baseline, so this is a **non-issue** [FLY-CPU] | `yyz` Toronto [FLY-REG] | `fly deploy --image` / `fly machine run` [FLY-DEPLOY]. Digest bug above: use the `repo:tag@sha256:…` form or the Machines API [FLY-DIGEST] | `always`, or `on-fail` with 10 retries per 5 min [FLY-RESTART] | Machines are migrated for maintenance, and migration stops the Machine [FLY-MIG]. They are not auto-moved on host failure [FLY-HOST]. 99.9% SLA for Enterprise only [FLY-SLA] | Own hardware [FLY-OWN] |
| **Google Cloud Run worker pool** | Built "for performing continuous background work", with no endpoint and no autoscaling [CR-WP]. GA since 2026-04-14 [CR-NOTES]. "An idle instance can be shut down at any time" [CR-CONTRACT], so the process must tolerate restarts | Allocated vCPU, no burst credits (**INFERRED**) | `northamerica-northeast2` Toronto and `-northeast1` Montreal, both Tier 2 [CR-LOC]. Worker pools in these regions: **UNCONFIRMED** | `gcloud run worker-pools deploy --image …@sha256:…` [CR-WP] | Startup and liveness probes; the container restarts on liveness failure [CR-HC] | 99.95% covers "Cloud Run service"; worker pools are not named (**UNCONFIRMED**) [CR-SLA] | Google |
| GCE VM (e2-standard-2) | Plain VM | E2 VMs live-migrate by default, with disruption "typically much less than 1 second" [GCE-HM], [GCE-LM] | Toronto or Montreal | `docker run …@sha256` in a startup script. The container agent (konlet) is **deprecated** [GCE-CONT] | Docker restart policy or systemd (**INFERRED**) | Live migration | Google |
| **Azure Container Apps** (Consumption) | Min replicas ≥ 1. "Idle" (< 0.01 vCPU, < 1 kB/s) changes the **price**, not the CPU allowed [ACA-BILL] (**INFERRED**) | Not stated | Canada Central (Toronto); meters listed [ACA-PRICE] | `az containerapp update --image …@sha256` (**INFERRED**) | Probes (**INFERRED**) | Critical updates "Anytime"; no windows on Consumption [ACA-MAINT]. 99.95% SLA: **UNCONFIRMED** | Microsoft |
| **DigitalOcean App Platform worker** | Yes (**INFERRED**) | Shared (`apps-s-2vcpu-4gb`, $50) or dedicated (`apps-d-2vcpu-4gb`, $78/mo) [DO-APP-PRICE]. Shared-CPU burst rules not documented | `TOR` [DO-APP-REG]. Dedicated sizes in TOR: **UNCONFIRMED** | App spec `image.digest` with `registry_type: GHCR` [DO-APP-SPEC] | Workers take a `liveness_health_check` [DO-APP-SPEC] | 99.95% SLA [DO-SLA-APP] | DO's own (**INFERRED**) |
| DigitalOcean Droplet | VM | Basic is shared ($24/mo). CPU-Optimized 2 vCPU / 4 GB is dedicated ($42/mo) [DO-DROP-PRICE] | `TOR1` | `docker run …@sha256` (**INFERRED**) | Docker or systemd | Live migration with ≥ 10 min metadata notice; cloud-firewall connections reset [DO-LM]. 99.99% per Droplet, excluding scheduled maintenance [DO-SLA-DROP] | DO's own (**INFERRED**) |
| AWS ECS Fargate | Service tasks | Allocated vCPU (**INFERRED**) | `ca-central-1` Montreal | Task-definition digest (**INFERRED**) | The ECS service replaces tasks | Patch retirement: new task first; notice is 7 days by default, configurable to 14 [FG-MAINT] | **AWS**, the same company as Vercel and Upstash |
| Hetzner Cloud | VM | CCX is dedicated, CPX is shared [HZ-PRICE] | Ashburn (no Canada) [HZ-LOC] | `docker run …@sha256` | Docker or systemd | Live migration "usually … less than 1 second" [HZ-LM] | Hetzner's own (**INFERRED**) |
| Railway | Yes | Usage-billed shared vCPU [RW-PRICE] | US East Metal, Virginia [RW-REG] | `railway service source connect --image`. Digest form: **UNCONFIRMED** | **UNCONFIRMED** | No SLA found | "Railway Metal" [RW-REG] |

## 3. Storage, egress, cost, setup

Two-week costs are at 2 vCPU / 4 GB. Setup times run from zero to a first deploy and are all
**INFERRED**.

| Candidate | Volume | Same-provider object store, write-once? | Egress | 2-week cost | Setup |
|---|---|---|---|---|---|
| Fly.io | NVMe slice on the Machine's host. Not replicated; daily snapshots "may not have your latest data" [FLY-VOL] | Tigris: `If-None-Match: *` gives 412 [TIGRIS-COND]. Runs on Fly's infrastructure [TIGRIS-FLY]. Durability figure **UNCONFIRMED**. $0.02/GB-mo; 5 GB and 10k Class A requests free [TIGRIS-PRICE] | $0.02/GB in North America [FLY-PRICE] | performance-2x 4 GB: **$30.38** (the $66/mo rate is the iad/ewr price; the yyz price is **UNCONFIRMED**). shared-cpu-2x: about $6 | ~15 min: CLI installed |
| Cloud Run worker pool | None; in-memory filesystem [CR-CONTRACT] | GCS: `ifGenerationMatch=0` or `x-goog-if-generation-match: 0`. `If-None-Match` is not honoured on writes [GCS-COND]. 11 nines [GCS-DUR] | Normal internet egress (**INFERRED**) | **$27.96** at the default rate ($0.000011244 per vCPU-s, $0.000001235 per GiB-s, less the free tier) [CR-PRICE]. The Tier-2 rate is higher: **UNCONFIRMED** | 30–45 min: install `gcloud`, set up project and billing, create an Artifact Registry remote repo |
| Azure Container Apps | Azure Files (**INFERRED**) | Blob `Put Blob` with `If-None-Match: *` gives 412 [AZ-BLOB-COND] | — | Canada Central: $0.000034 per vCPU-s active, $0.000004 idle, $0.000004 per GiB-s. That is **$21 (mostly idle) to $94 (always active)** after free grants [ACA-PRICE], [ACA-BILL] | 45–60 min |
| DO App Platform | None (**INFERRED**) | Spaces is available in TOR1 [DO-SPACES-AV], but conditional writes are not among the documented features [DO-SPACES-S3]: **UNCONFIRMED**. $5/mo for 250 GiB [DO-SPACES-PRICE] | Allowance included [DO-APP-PRICE] | **$35.90** (`apps-d-2vcpu-4gb`) plus $5 | 20–30 min (no `doctl` installed) |
| DO Droplet | Block storage | Spaces, as above | 4 TB included [DO-DROP-PRICE] | **$21.00** (CPU-Optimized) plus $5 | 30–45 min |
| AWS Fargate | EFS (**INFERRED**) | S3 `If-None-Match: *` gives 412 [S3-COND] | A private subnet needs a NAT gateway; use a public IP instead (**INFERRED**) | **$36.48** plus $1.68 for IPv4 [FG-PRICE] | 60–90 min (IAM, VPC, cluster, service) |
| Hetzner | Volumes | No Object Storage in US locations [HZ-LOC] | Generous allowance | CCX13: **$27.45** [HZ-PRICE] | 30–60 min, plus a possible ID check [HZ-VERIFY] |
| Railway | Volumes $0.15/GB | Buckets run "on Tigris's metal servers"; conditional writes not documented [RW-BUCKET] | $0.05/GB | About $5 of usage plus a $5 or $20 plan [RW-PRICE] | ~15 min |

## 4. Recommendation

**Leg A: Fly.io, `yyz`.** Run one `performance-2x` Machine (4 GB) with restart policy `always` and
no volume, archiving to Tigris. Fly has no SLA below Enterprise, and a failed host leaves the Machine
down [FLY-SLA], [FLY-HOST]. Leg B covers that. A second Fly Machine on another host costs about
$30 more and is optional. Rehearse a digest deploy with the installed flyctl first.

**Leg B: Google Cloud Run worker pool, `northamerica-northeast1`.** Run one instance at
2 vCPU / 4 GiB, archiving to GCS. Montreal keeps the two legs in different metros as well as
different companies; Toronto (`-northeast2`) would also work. If `worker-pools deploy` is refused
in that region, fall back to a Cloud Run service with instance-based billing and `min-instances=1`
[CR-BILL]. That fallback needs a listening port.

Why this pair (**INFERRED**):

- Two companies on separately owned infrastructure, neither on AWS, so neither leg shares a fate
  with the other.
- Both deploy the same digest from a CLI.
- Both are within about 500 km of Toronto.
- Setup is the lowest of the candidates: `fly` is installed, and `~/.config/gcloud` holds prior
  state from June 2026, so both accounts probably exist [LOCAL].

**Mirror the image into each provider's registry.** Copy it to `registry.fly.io` and to Artifact
Registry, so that restarts on the night do not depend on GHCR. A byte-for-byte copy keeps the same
digest (**INFERRED**).

**Alternative pair: DigitalOcean App Platform (`TOR`, `apps-d-2vcpu-4gb`) and Google Cloud Run.**
DO brings a 99.95% SLA [DO-SLA-APP] and digest-pinned GHCR in the app spec [DO-APP-SPEC], at about
$36 for 2 weeks. Against that, there is no CLI installed, and Spaces' write-once support is
**UNCONFIRMED**, so the DO leg would archive to R2 or GCS. To replace the Google leg instead, use
Azure Container Apps in Canada Central.

## 5. Archive storage options

**(a) Each host's own volume.**
- A Fly volume ties the Machine to one host, is not replicated, and its snapshots can lag
  [FLY-VOL].
- Cloud Run has no volume at all [CR-CONTRACT].
- Use a volume only as a local spool. **OBSERVED** / **INFERRED**.

**(b) Each provider's own object store, write-once (recommended).** Write-once support:
- Tigris: yes, with `If-None-Match: *` [TIGRIS-COND].
- GCS: yes, but only with the generation-match header, not `If-None-Match` [GCS-COND].
- Azure Blob: yes [AZ-BLOB-COND].
- S3: yes [S3-COND].
- DO Spaces: **UNCONFIRMED** [DO-SPACES-S3].
- Railway Buckets: **UNCONFIRMED** [RW-BUCKET].

The two archives are independent, and each co-fails only with its own leg. The cost is 1–2 GB and
up to 5,000 PUTs, which is $0 inside Tigris's free tier and cents on GCS. The GCS cents are
**INFERRED**, because GCS rates were not fetched. Use the sha256 of the body as the key.

The price of (b) is two code paths: S3 with `If-None-Match` for Tigris and the GCS client for GCS.
For one code path, point leg B at R2 instead of GCS. R2 is S3-compatible with `If-None-Match`, but
it adds a Cloudflare account.

**(c) One shared store that both legs write to.**

| Store | Write-once | Durability | ~1–2 GB, ≤5k objects | Label |
|---|---|---|---|---|
| Cloudflare R2 | `If-None-Match` on PutObject [R2-COND] | 11 nines [R2-DUR] | $0 inside the free tier (10 GB-mo, 1M Class A) [R2-PRICE] | OBSERVED |
| Backblaze B2 | Not listed in the PutObject headers (docs dated 2023) [B2-PUT] | — | — | **UNCONFIRMED** |
| Vercel Blob | `put()` throws if the pathname exists, by default [VB-DOCS] | 11 nines, stored on Amazon S3 [VB-DOCS] | Pro: $0.023/GB and $5 per 1M advanced ops [VB-PRICE] | OBSERVED |
| AWS S3 | `If-None-Match: *` [S3-COND] | 11 nines | Cents | OBSERVED |

With content-addressed keys, the second writer gets a 412, so the two legs deduplicate for free.

A shared store **is a common failure point**: an outage stops both archives at once. A Cloud Run
in-memory spool is lost if the instance restarts during that outage. Vercel Blob and S3 also share
AWS with the reader path. **INFERRED**.

## 6. Local state (2026-10-05) [LOCAL]

- `fly auth whoami` → `Error: no access token available.`. It is installed as `fly` and `flyctl`
  at `/opt/homebrew/bin`, v0.4.111 (built 2026-09-30). `~/.fly/config.yml` records
  `last_login: 2026-06-26`. **OBSERVED**.
- `gcloud aws az doctl render railway koyeb northflank hcloud` are **not found** in either the tool
  shell or a `zsh -lc` login shell. `docker` is at `/usr/local/bin/docker`. **OBSERVED**.
- `~/.config/gcloud/` exists, with `application_default_credentials.json` dated Jun 3, even though
  the CLI is absent. **OBSERVED**. A Google Cloud account probably exists. **INFERRED**.

## Self-critique

- **Independence is judged by owner and hardware, not by building or network.** Fly `yyz`,
  DO `TOR1` and Google's Toronto region may share Toronto carrier hotels or transit
  (**UNCONFIRMED**). This is part of why leg B goes to Montreal.
- **The shared dependencies sit outside both hosts.** These are GHCR, the City's CloudFront feed,
  Upstash and Vercel, and the most likely failure on the night is one of them or our own code, not
  a host. Two hosts do not protect against those.
- **Several claims rest on search excerpts or community posts, not fetched docs.** These are
  [FLY-DIGEST], [CR-HC], [DO-SLA-APP], [KOYEB-MISTRAL], [VB-PRICE] and [HZ-VERIFY]. Treat them as
  weaker.
- **The regional price multipliers (yyz, Tier 2) are unconfirmed.** Every candidate is under
  about $100 for 2 weeks, so cost should not decide this.

## Sources

Fetched 2026-10-05. Dates are the page's own where it shows one.

- **[FLY-CPU]** <https://docs.fly.io/machines/cpu-performance>
- **[FLY-REG]** <https://docs.fly.io/reference/regions>
- **[FLY-PRICE]** <https://docs.fly.io/about/pricing>
- **[FLY-RESTART]** <https://docs.fly.io/machines/guides-examples/machine-restart-policy>
- **[FLY-VOL]** <https://docs.fly.io/volumes/overview>
- **[FLY-MIG]** <https://docs.fly.io/reference/machine-migration>
- **[FLY-HOST]** <https://docs.fly.io/apps/trouble-host-unavailable>
- **[FLY-SLA]** <https://fly.io/legal/sla-uptime/>
- **[FLY-DEPLOY]** <https://docs.fly.io/flyctl/deploy>
- **[FLY-DIGEST]** Community report, 2026-04-21:
  <https://community.fly.io/t/fly-machine-run-duplicates-sha256-digest-when-image-ref-is-digest-form-rejects-as-invalid-image-identifier/27679>
- **[FLY-OWN]** <https://fly.io/enterprise/> and <https://fly.io/security/>
- **[TIGRIS-COND]** <https://www.tigrisdata.com/docs/objects/conditionals/>
- **[TIGRIS-PRICE]** <https://www.tigrisdata.com/pricing/>
- **[TIGRIS-FLY]** <https://fly.io/blog/tigris-public-beta/>
- **[CR-WP]** <https://docs.cloud.google.com/run/docs/deploy-worker-pools> (updated 2026-09-30)
- **[CR-NOTES]** <https://docs.cloud.google.com/run/docs/release-notes> (preview 2025-06-25, GA 2026-04-14)
- **[CR-BILL]** <https://docs.cloud.google.com/run/docs/configuring/billing-settings> (2026-09-30)
- **[CR-LOC]** <https://docs.cloud.google.com/run/docs/locations> (2026-09-30)
- **[CR-PRICE]** <https://cloud.google.com/run/pricing> (worker-pool table, default region)
- **[CR-SLA]** <https://cloud.google.com/run/sla>
- **[CR-HC]** <https://docs.cloud.google.com/run/docs/configuring/workerpools/healthchecks> (search excerpt)
- **[CR-CONTRACT]** <https://docs.cloud.google.com/run/docs/container-contract> (2026-09-30)
- **[CR-REG]** <https://docs.cloud.google.com/run/docs/deploying> (2026-09-30)
- **[GCS-COND]** <https://docs.cloud.google.com/storage/docs/request-preconditions> (2026-09-30)
- **[GCS-DUR]** <https://docs.cloud.google.com/storage/docs/availability-durability> (2026-09-30)
- **[GCE-LM]** <https://docs.cloud.google.com/compute/docs/instances/live-migration-process> (2026-10-02)
- **[GCE-HM]** <https://docs.cloud.google.com/compute/docs/instances/host-maintenance-overview>
- **[GCE-CONT]** <https://docs.cloud.google.com/compute/docs/containers/deploying-containers>
- **[ACA-BILL]** <https://learn.microsoft.com/en-us/azure/container-apps/billing> (ms.date 2025-12-09)
- **[ACA-PRICE]** Azure Retail Prices API, `serviceName eq 'Azure Container Apps' and armRegionName eq 'canadacentral'`:
  <https://prices.azure.com/api/retail/prices>
- **[ACA-MAINT]** <https://learn.microsoft.com/en-us/azure/container-apps/planned-maintenance> (ms.date 2025-05-02)
- **[AZ-BLOB-COND]** <https://learn.microsoft.com/en-us/rest/api/storageservices/specifying-conditional-headers-for-blob-service-operations>
- **[AR-CLOSED]** <https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html>
- **[FG-MAINT]** <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-maintenance.html>
- **[FG-PRICE]** AWS Price List API, publicationDate 2026-09-11:
  <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/ca-central-1/index.json>
  (vCPU-hour $0.04456, GB-hour $0.004865)
- **[LS-PRICE]** <https://aws.amazon.com/lightsail/pricing/>
- **[S3-COND]** <https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
- **[DO-APP-REG]** <https://docs.digitalocean.com/products/app-platform/details/availability/>
- **[DO-APP-SPEC]** <https://docs.digitalocean.com/products/app-platform/reference/app-spec/> (verified 2026-09-01)
- **[DO-APP-PRICE]** <https://docs.digitalocean.com/products/app-platform/details/pricing/> (verified 2026-07-13)
- **[DO-DROP-PRICE]** <https://www.digitalocean.com/pricing/droplets>
- **[DO-LM]** <https://docs.digitalocean.com/products/droplets/details/live-migration/> (verified 2026-07-29)
- **[DO-SLA-APP]** <https://www.digitalocean.com/sla/app-platform> (search excerpt)
- **[DO-SLA-DROP]** <https://www.digitalocean.com/sla/cpu-droplets> (updated 2025-06-03)
- **[DO-SPACES-AV]** <https://docs.digitalocean.com/products/spaces/details/availability/>
- **[DO-SPACES-S3]** <https://docs.digitalocean.com/products/spaces/reference/s3-compatibility/> (verified 2026-06-22)
- **[DO-SPACES-PRICE]** <https://docs.digitalocean.com/products/spaces/details/pricing/> (verified 2026-07-13)
- **[RENDER-REG]** <https://render.com/docs/regions>
- **[RENDER-AWS]** <https://render.com/blog/render-joins-aws-marketplace> (2024-09-12)
- **[RENDER-PRICE]** <https://render.com/pricing>
- **[RENDER-IMG]** <https://render.com/docs/deploying-an-image>
- **[RW-REG]** <https://docs.railway.com/reference/regions>
- **[RW-PRICE]** <https://docs.railway.com/reference/pricing/plans>
- **[RW-BUCKET]** <https://docs.railway.com/storage-buckets>
- **[KOYEB-REG]** <https://www.koyeb.com/docs/reference/regions> (2026-05-27)
- **[KOYEB-MISTRAL]** <https://www.koyeb.com/blog/koyeb-is-joining-mistral-ai-to-build-the-future-of-ai-infrastructure> (2026-02-17, search excerpt)
- **[NF-CLOUD]** <https://northflank.com/cloud>
- **[HZ-LOC]** <https://docs.hetzner.com/cloud/general/locations/>
- **[HZ-PRICE]** <https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/> (effective 2026-06-15)
- **[HZ-LM]** <https://docs.hetzner.com/cloud/servers/technical-concepts/terminology/> (2025-08-28)
- **[HZ-VERIFY]** <https://docs.hetzner.com/general/security-and-identify/fraud-prevention-faq/> (search excerpt)
- **[R2-COND]** <https://developers.cloudflare.com/r2/api/s3/api/> (2026-07-31)
- **[R2-PRICE]** <https://developers.cloudflare.com/r2/pricing/> (2026-10-01)
- **[R2-DUR]** <https://developers.cloudflare.com/r2/reference/durability/> (2026-04-21)
- **[B2-PUT]** <https://www.backblaze.com/apidocs/s3-put-object> (2023-06-01)
- **[VB-DOCS]** <https://vercel.com/docs/vercel-blob> (2026-08-26)
- **[VB-PRICE]** <https://vercel.com/docs/vercel-blob/usage-and-pricing> (search excerpt)
- **[LOCAL]** Commands run 2026-10-05: `fly auth whoami`, `fly version`, `command -v` for each CLI
  (tool shell and `zsh -lc`), and listings of `~/.fly` and `~/.config/gcloud` (no secrets read)

## 7. DigitalOcean App Platform: open points closed (2026-10-05)

DO primary sources, fetched 2026-10-05.

**Verdict (INFERRED): App Platform holds up as the second leg.** Run one `apps-d-2vcpu-4gb` worker
in `region: nyc`, a different metro from Fly `yyz`. Pull the image by digest from DOCR `nyc3` and
archive to Spaces `nyc3`. No blocker found; open risks are new-account review and undocumented
host-failure behaviour.

1. **Digest-pinned worker.** **OBSERVED**:
   - Workers are "not routable", so no port is needed [DO-APP-SPEC].
   - The `image` fields are `registry_type` (`DOCR`, `DOCKER_HUB` or `GHCR`), `registry` (for
     GHCR, the org), `repository` and `digest`, which excludes `tag` [DO-APP-SPEC], [DO-IMG].
   - Private GHCR needs `registry_credentials: "$username:$access_token"` [DO-APP-SPEC].
   - `brew install doctl` (1.177.0); `doctl apps create --spec` deploys; `doctl apps propose --spec`
     validates and prices a spec without creating it [DOCTL].
   - `apps update` deploys a changed digest [DO-IMG].
   - DOCR exists in TOR1 and NYC3; the Starter plan is free, with 500 MiB [DOCR].
   - Images must be amd64 [DO-LIMITS].

   Whether a restart pulls from GHCR again is **UNCONFIRMED**, and DOCR sidesteps the question.
   `crane copy` keeps the manifest bytes, and so the digest (**INFERRED**). Check the copy with
   `doctl registry repository list-manifests`, and keep it tagged.
2. **Regions and price.** **OBSERVED**:
   - Apps run in NYC, AMS, SFO, SGP, LON, FRA, TOR, BLR, SYD, ATL, RIC and MKC [DO-REGAV].
   - No page restricts sizes by region. Dedicated sizes in TOR or NYC stay **UNCONFIRMED** until a
     `propose` passes.
   - Billing is per second, capped at 28 days a month [DO-APP-PRICE].

   At 2 vCPU / 4 GB, shared `apps-s-2vcpu-4gb` is $50/mo and dedicated `apps-d-2vcpu-4gb` is $78/mo.
   For 14 days that is **$25** and **$39** (**INFERRED**). $39 replaces the $35.90 above.
3. **Shared CPU.** **OBSERVED**: on shared CPUs, resources "may vary depending on usage by other
   customers" [DO-PLAN]. No burst or credit rule is documented. A 1 s job per minute has ample
   headroom; dedicated removes the variable for $14 (**INFERRED**).
4. **Restarts and maintenance.**
   - **Crashes.** A crashed container restarts. Its last output is in
     `doctl apps logs --type=run_restarted` [DO-LOGS]. **OBSERVED**.
   - **Liveness.** Worker liveness checks are HTTP or TCP on a port the worker must listen on; there
     is no exec probe. Defaults are a 10 s period with a failure threshold of 18 [DO-APP-SPEC],
     [DO-HC]. **OBSERVED**. Without a port, a hung process is never restarted (**INFERRED**).
   - **Deploys.** The new instance must be healthy before the old one gets SIGTERM [DO-FAQ].
     **OBSERVED**. A redeploy therefore briefly runs two copies rather than none (**INFERRED**).
   - **Maintenance** "may" redeploy the app, "without downtime". No notice policy is documented
     [DO-MAINT]. **OBSERVED**.
   - **Host failure.** Apps run on "a shared DigitalOcean Kubernetes cluster" [DO-FAQ]. High
     availability needs at least 2 containers [DO-LIMITS]. Whether a container is rescheduled after
     a host fails is **UNCONFIRMED**.
5. **SLA (page fetched).** **OBSERVED**: DO promises "commercially reasonable efforts to provide a
   Monthly Uptime Percentage of 99.95% for each App Platform ACI". The SLA names background workers.
   Without ingress, downtime means 5 minutes or more in which the component "fails to start or
   execute due to an internal App Platform issue". Scheduled maintenance is excluded [DO-SLA].
6. **Spaces.** **OBSERVED**:
   - Spaces is available in TOR1 and NYC3 [DO-SPACES-AV].
   - **PutObject's supported headers omit `If-None-Match`**; only GetObject and HeadObject list it
     [DO-SPACES-API].
   - No durability figure is published. Spaces "runs on Ceph" [DO-SPACES-FEAT], and the SLA
     promises 99.9% uptime per bucket [DO-SPACES-SLA].
   - Price: $5/mo, prorated hourly [DO-SPACES-PRICE].

   **INFERRED**: content-hashed keys make an overwrite byte-identical, so the missing 412 costs only
   a redundant PUT.
7. **Logs and alerts.** **OBSERVED**:
   - `doctl apps logs <app> <worker> --follow` streams the log [DO-LOGS].
   - Alert rules cover deployments plus per-component `RESTART_COUNT`, CPU and memory
     [DO-APP-SPEC].
   - Alerts are sent by email or Slack [DO-ALERTS].

   To page the developer, send a `RESTART_COUNT` alert to Slack with phone push on (**INFERRED**).
8. **Account setup.** **OBSERVED**:
   - Adding a card places a $25 authorization, which becomes credit.
   - An account "locked during sign-up" has to contact support.
   - Tier 1 accounts cannot create dedicated Droplets. App Platform is not listed in the tiers
     [DO-ACCT].

   Whether a new account can use `apps-d-*` is **UNCONFIRMED**. Setup takes 20–30 min without a
   review (**INFERRED**), so open the account now.

### Sources (section 7)

Also cited, listed above and fetched again: [DO-APP-SPEC], [DO-APP-PRICE], [DO-SPACES-AV] and
[DO-SPACES-PRICE].

- **[DO-IMG]** <https://docs.digitalocean.com/products/app-platform/how-to/deploy-from-container-images/> (verified 2026-07-13)
- **[DO-HC]** <https://docs.digitalocean.com/products/app-platform/how-to/manage-health-checks/> (2026-07-13)
- **[DO-LIMITS]** <https://docs.digitalocean.com/products/app-platform/details/limits/> (2026-05-20)
- **[DO-REGAV]** <https://docs.digitalocean.com/platform/regional-availability/#app-platform> (2026-10-01)
- **[DO-PLAN]** <https://docs.digitalocean.com/products/app-platform/concepts/choosing-a-plan/> (2025-05-01)
- **[DO-FAQ]** <https://docs.digitalocean.com/products/app-platform/details/intro-faq/> (2025-11-24)
- **[DO-MAINT]** <https://docs.digitalocean.com/products/app-platform/details/maintenance/> (2024-11-22)
- **[DO-LOGS]** <https://docs.digitalocean.com/products/app-platform/how-to/view-logs/> (2026-03-23) and
  <https://docs.digitalocean.com/reference/doctl/reference/apps/logs/> (doctl v1.177.0)
- **[DO-ALERTS]** <https://docs.digitalocean.com/products/app-platform/how-to/create-alerts/> (2026-04-24)
- **[DO-SLA]** <https://www.digitalocean.com/sla/app-platform> (updated 2025-06-03). Fetched directly;
  replaces [DO-SLA-APP].
- **[DO-SPACES-API]** <https://docs.digitalocean.com/reference/api/spaces/> (2026-09-03)
- **[DO-SPACES-FEAT]** <https://docs.digitalocean.com/products/spaces/details/features/> (2026-07-13)
- **[DO-SPACES-SLA]** <https://www.digitalocean.com/sla/spaces> (updated 2025-12-02)
- **[DOCR]** <https://docs.digitalocean.com/products/container-registry/details/pricing/> (2026-07-13),
  `…/details/availability/` (generated 2026-10-05) and `…/getting-started/quickstart/` (2026-09-03)
- **[DOCTL]** <https://docs.digitalocean.com/reference/doctl/how-to/install/> (2026-10-01),
  `…/reference/apps/create/` and `…/reference/apps/propose/`, and `brew info doctl`
- **[DO-ACCT]** <https://docs.digitalocean.com/platform/billing/manage-payment-methods/> (2026-07-30),
  <https://docs.digitalocean.com/support/what-do-i-do-if-my-account-was-locked-during-sign-up/>
  (2024-03-29) and <https://docs.digitalocean.com/platform/resource-limits/> (2026-09-30)
