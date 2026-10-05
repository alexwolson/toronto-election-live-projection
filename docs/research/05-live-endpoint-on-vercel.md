# Serving the live payload from Vercel: Next.js route, Upstash Redis, Vercel Pro

Research note for [#8](https://github.com/alexwolson/toronto-election-live-projection/issues/8). Written 2026-10-05.

Claims are labelled **OBSERVED** (seen in a source, a doc, or a local run), **INFERRED** (reasoned
from observations) or **UNCONFIRMED** (no primary source found). Source keys are listed at the end.

## Summary

- **The design holds, in one route form.** `revalidate = 15` on its own builds as dynamic (ƒ),
  because `@upstash/redis` fetches with `no-store`. That means no ISR and no request collapsing.
  Adding `dynamic = "force-static"` makes it ISR: `○ /live/results.json 15s`.
  **OBSERVED** [UP-SDK], [NX-ISR], [BUILD].
- **Dropping `output: "export"` keeps every page static.** The one regression: unknown
  `/wards/*` paths now return 500. **OBSERVED** [BUILD].
- **ISR gives one function run per region per interval.** On a Redis error, Vercel serves the
  stale copy and retries after 30 s. **OBSERVED** [V-RC], [V-ISR].
- **Use Upstash pay-as-you-go, not the free tier.** A night is about 3–8K commands, which costs
  about $0.02. The free tier has no replication. **OBSERVED** (limits), **INFERRED** (counts)
  [UP-BILL], [UP-DUR].
- **About $87 of on-demand Pro usage for the night.** Flat Rate CDN's included tier is about 15×
  too small for this traffic. **INFERRED** from [V-YUL1], [V-FLAT].
- **Breakers:** the plan, trial or spend pauses; a deploy on the night; a cached non-200 response.
  See §6.

## 1. Next.js 16.3.4 (installed)

**(a) `cacheComponents` is off.** Switching it on fails the build:
`Route segment config "dynamicParams" is not compatible with nextConfig.cacheComponents`
(in both trustee routes). Leave it off. **OBSERVED** [BUILD], [NX-SEG].

**(b) Without export mode, every existing route stays static.** I built a throwaway worktree of
`main@9964021` with `output: "export"` removed, using the local `.release-data` (no credentials
needed). All pages came out ○ or ● (4 + 29 trustee pages, 25 wards). **OBSERVED** [BUILD].

| Export-mode dependency | Without export | Label |
|---|---|---|
| `wards/[ward_num]` lacks `dynamicParams = false` | `/wards/99/` returns **500**: the fallback render fetches the legacy raw-GitHub feed, which fails validation. Add `dynamicParams = false`. | OBSERVED [BUILD] |
| `images.unoptimized: true` | Keep it. Removing it turns on billable Image Optimization. | INFERRED [V-PRICE] |
| `trailingSlash: true` | Paths with a file extension are exempt. `/live/results.json` serves directly; `/live/results.json/` redirects (308) to it. | OBSERVED [NX-TS], [BUILD] |
| Client fetches, scripts that touch `out/` | None. Only the README's "serve `out/`" preview step changes. | OBSERVED |
| `vercel-build`, `deploy:production` | Unchanged. But the live route prerenders **at build**, so the Upstash env vars and the Redis key must exist then. A throw while prerendering fails the build. | OBSERVED [BUILD] |

**(c) The route form.** In `src/app/live/results.json/route.ts`, export `revalidate = 15` **and**
`dynamic = "force-static"`. Passing `cache: "default"` to `new Redis()` also works.

- **Why the plain form fails.** The Next docs say a route with an explicit `no-store` fetch is
  rendered dynamically [NX-ISR]. The SDK defaults to `cache: ... ?? "no-store"` [UP-SDK].
- **What each form built:** `ƒ` with revalidate only; `○ 15s 1y` with force-static; `○ 15s 1y` with
  `cache: "default"`. **OBSERVED** [BUILD].
- **What it emits:** `Cache-Control: s-maxage=15, stale-while-revalidate=31535985`, and the
  prerender manifest has `initialRevalidateSeconds: 15`. Vercel maps the App Router's segment
  `revalidate` to ISR. **OBSERVED** [BUILD], [V-ISR].
- **Why not `"use cache"` + `cacheLife`.** It needs `cacheComponents`. A profile whose `expire` is
  under 5 minutes is not prerendered, so it runs at request time instead of as ISR. **OBSERVED**
  [NX-LIFE].
- **Local test (`next start` with a mock Redis):** a stale hit was followed by fresh data. While
  the mock returned 500, the route kept returning 200 with the last good payload, and it recovered
  on the next success. **OBSERVED** [BUILD].
- **The handler must throw on an error or a missing key, never return a non-200.** Next caches
  whatever status the `Response` has [NX-SRC], and Vercel treats 404, 410 and 3xx as valid
  [V-ISR]. **OBSERVED**.

## 2. Vercel CDN

- **Request collapsing** covers ISR (and Image Optimization), including STALE background
  revalidation, giving "a single function invocation within the same region". Responses with only
  `Cache-Control` headers get per-region caching but no collapsing. **OBSERVED** [V-RC], [V-ISR].
- **Failed regeneration:** Vercel serves the stale copy and retries after a 30 s TTL. **OBSERVED**
  [V-ISR].
- **Minimum interval:** `s-maxage` can be as short as 1 s [V-CCH]. I found no ISR-specific floor
  (**UNCONFIRMED**).
- **Browser vs CDN headers:** for function responses, `Vercel-CDN-Cache-Control` and
  `CDN-Cache-Control` override `Cache-Control`. Browsers get `public, max-age=0, must-revalidate`
  on the live site. **OBSERVED** [V-CCH], [LIVE]. A custom browser TTL on an ISR route is
  **UNCONFIRMED**, and unnecessary with 60 s polling.
- **Regions:** the CDN cache is per region. A request from this Mac was served by **yul1**, so
  Toronto readers likely hit 1–3 regions (yul1, cle1, iad1). **OBSERVED** [V-CDN], [V-REG], [LIVE];
  **INFERRED** (count).
- **Function and Redis region:** keep **iad1**, where the durable ISR cache lives and the only
  region Hobby allows [V-ISRP], [V-FREG]. Pair it with Upstash **us-east-1**. yul1 with
  ca-central-1 also works, at about 10 % higher unit prices. **INFERRED**.
- **Cache key:** query strings count for non-static responses [V-KEY], so clients must not
  cache-bust. Whether ISR ignores query strings is **UNCONFIRMED**.

## 3. Upstash Redis

| Item | Finding | Label |
|---|---|---|
| Billing | A Vercel-managed install is billed on the Vercel invoice. Spend Management excludes Marketplace charges. | OBSERVED [V-MKT], [V-NATIVE], [V-SPEND] |
| Regions | AWS `us-east-1` and `ca-central-1` both exist. Whether the Vercel install flow offers every region is UNCONFIRMED. | OBSERVED [UP-GLOBAL] |
| Compare-and-set | `EVAL` "runs as a single atomic step" (global lock), including over REST. | OBSERVED [UP-EVAL] |
| Limits | Free and pay-as-you-go: 10K commands/s, 10 MB request. Free: 500K commands and 10 GB a month. PAYG: $0.20 per 100K commands, 200 GB a month free. A PAYG **budget, once hit, rate-limits** the database. | OBSERVED [UP-BILL] |
| Durability | Always persisted to disk. Paid tiers replicate; **the free tier does not**. Reads are eventually consistent. | OBSERVED [UP-DUR], [UP-REPL], [UP-CONS] |
| SLA | 99.99 %, only with the Prod Pack ($200 a month per database). | OBSERVED [UP-SLA] |
| Python | `upstash-redis` 1.8.0 works over REST from any host and supports `eval`. | OBSERVED [UP-PY], [UP-EVAL] |

**Commands per night.** Writes: 2 × 120 × 6 = 1,440 EVALs. Reads: about 4 regenerations a minute
per region × 360 min = 1,440–4,320. Total about **3–8K**, using under 1 GB. Whether `redis.call`s
inside a script are billed separately is **UNCONFIRMED**; even if they were, the total would be
about 10K. **INFERRED**.

## 4. Vercel Pro

- **Billing cycle:** the start date "depends on when you created the account, or the account's
  trial phase ended". The first payment is due within 24 h. The cycle start for a Hobby→Pro upgrade
  is **UNCONFIRMED**; check the Usage page after upgrading. [V-BILL]
- **Included:** $20 platform fee and $20 usage credit, one seat, and Flat Rate CDN's included tier
  (1M requests, 1 TB). [V-PRO]
- **Spend Management:** new customers default to notifications at $200. "Pause Production
  Deployments" is a separate, confirmed switch that takes **all** projects to 503. Spend is checked
  every few minutes. Whether the default includes pausing is **UNCONFIRMED**. Suggested setting:
  about $150 with email and SMS alerts, pause **off**. [V-PRO], [V-SPEND]
- **Flat Rate CDN:** tier changes apply from the next cycle. Usage "materially above" capacity may
  be moved to Flex CDN (no availability guarantee). Vercel recommends on-demand for mission-critical
  traffic. [V-FLAT], [V-CDNT]
- **Unit prices (iad1 / yul1):** CDN requests $2.00 / $2.20 per million. Fast Data Transfer
  $0.15/GB. ISR reads $0.40 / $0.44 and writes $4.00 / $4.40 per million 8 KB units (no write when
  the content is unchanged). Invocations $0.60 per million. [V-IAD1], [V-YUL1], [V-ISRP], [V-FN]

**Cost estimate (INFERRED).** The JSON is 15M requests at about 20 KB gzipped, about 300 GB
(Vercel compresses JSON [V-COMP]). The page shell is assumed at 100K loads × 16 files, about 1.6M
requests and 32 GB; today's home page is 16 files, 316 KB gzipped.

| | On-demand (yul1) | Flat Rate (included tier) |
|---|---|---|
| JSON requests | 15M × $2.20/M = $33 | $0, about 15× capacity (fair-use risk) |
| JSON transfer | 300 GB × $0.15 = $45 | within 1 TB |
| Page shell | ≈ $8 | $0 |
| ISR, functions, Redis | < $1 | < $1 |
| **Night total** | **≈ $87**, less the $20 credit | $0 now; likely moved up to $100/mo (50M tier) next cycle |

## 5. Alternatives to Upstash

- **Vercel Blob conditional writes:** `put(..., { allowOverwrite: true, ifMatch: etag })` throws
  `BlobPreconditionFailedError` if the blob changed since the ETag was read. That gives an
  optimistic compare-and-set (read, compare seqs, write, retry). Overwrites take up to 60 s to
  propagate; private blobs can skip that with `useCache: false`. **OBSERVED** [V-BLOB].
- **Global Config:** 1 MB per store, writes propagate in up to 10 s, and the docs advise against
  frequently updated data. Conditional write: **UNCONFIRMED** [V-GC].

## 6. Breakers

1. **Plan pauses.** Hobby pauses for 30 days past 1M requests or 100 GB. A Pro *trial* pauses at
   1M invocations or 16 CPU-hours and lasts 14 days, so be on **paid** Pro early. An unpaid
   renewal pauses deployments after 14 days. [V-HOBBY], [V-TRIAL], [V-BILL]
2. **The Spend Management pause** takes every production deployment offline. [V-SPEND]
3. **A deploy or rollback on the night.** The ISR cache is per deployment and restarts from the
   build-time snapshot, so clients must keep the newest `(seqA, seqB)` they have seen. [V-ISR]
4. **Route mistakes** (§1c): a ƒ build, or a cached non-200 response.
5. **Redis settings:** the free tier has no replication; a PAYG budget that is hit rate-limits the
   database. [UP-DUR], [UP-BILL]
6. **Flat Rate fair-use action.** Use on-demand in October. [V-FLAT]
7. **Deployment protection.** No doc says an upgrade changes protection or domains
   (**UNCONFIRMED**). Clients must poll `projection.cityhallwatcher.com`, not `*.vercel.app`. [V-DP]

## Sources

- [NX-ISR], [NX-SEG], [NX-LIFE], [NX-TS]: `toronto-election-poll-tracker/node_modules/next/dist/docs/01-app/` (Next 16.3.4): `02-guides/incremental-static-regeneration.md`, `03-api-reference/03-file-conventions/02-route-segment-config/index.md`, `03-api-reference/04-functions/cacheLife.md`, `03-api-reference/05-config/01-next-config-js/trailingSlash.md`
- [NX-SRC]: `node_modules/next/dist/build/templates/app-route.js`, lines 235–268 and 331–334
- [UP-SDK]: `@upstash/redis` 1.39.0, `nodejs.mjs:229` and the retry defaults in `chunk-4WQYU7T6.mjs`
- [BUILD]: local runs, 2026-10-05. A throwaway worktree of `main@9964021` was built with `next build` and served with `next start` against a mock Upstash server. The worktree was removed afterwards.
- [LIVE]: `curl -I https://projection.cityhallwatcher.com/`, 2026-10-05 (`x-vercel-id: yul1::…`)
- Vercel docs, read as `.md` on 2026-10-05; page dates in parentheses:
  - [V-ISR] `/docs/incremental-static-regeneration` (08-28)
  - [V-RC] `…/request-collapsing` (08-11)
  - [V-ISRP] `…/limits-and-pricing` (08-11)
  - [V-CCH] `/docs/caching/cache-control-headers` (09-14)
  - [V-CDN] `/docs/caching/cdn-cache` (09-14)
  - [V-KEY] `/docs/caching/cdn-cache/purge`
  - [V-REG] `/docs/regions` (08-11)
  - [V-FREG] `/docs/functions/configuring-functions/region` (08-11)
  - [V-PRO] `/docs/plans/pro-plan` (09-15)
  - [V-BILL] `/docs/plans/pro-plan/billing` (09-17)
  - [V-TRIAL] `/docs/plans/pro-plan/trials` (09-14)
  - [V-HOBBY] `/docs/plans/hobby` (09-14)
  - [V-SPEND] `/docs/spend-management` (09-18)
  - [V-FLAT] `/docs/pricing/flat-rate-cdn` (09-14)
  - [V-CDNT] `/docs/cdn` (09-14)
  - [V-PRICE] `/docs/pricing` (09-14)
  - [V-IAD1], [V-YUL1] `/docs/pricing/regional-pricing/{iad1,yul1}` (09-14)
  - [V-FN] `/docs/functions/usage-and-pricing` (06-16)
  - [V-COMP] `/docs/how-vercel-cdn-works/compression` (03-05)
  - [V-MKT] `/docs/marketplace-storage` (09-17)
  - [V-NATIVE] `/docs/integrations/install-an-integration/product-integration` (09-17)
  - [V-BLOB] `/docs/vercel-blob` (08-26)
  - [V-GC] `/docs/global-config/global-config-limits` (07-29)
  - [V-DP] `/docs/deployment-protection` (09-15)
- Upstash docs under `https://upstash.com/docs/` (no page dates shown):
  - [UP-BILL] `redis/overall/billing`
  - [UP-EVAL] `redis/commands/scripting/eval`
  - [UP-DUR] `redis/features/durability`
  - [UP-REPL] `redis/features/replication`
  - [UP-CONS] `redis/features/consistency`
  - [UP-GLOBAL] `redis/features/globaldatabase`
  - [UP-SLA] `common/help/sla`
  - [UP-PY] `redis/sdks/py/overview`, plus PyPI `upstash-redis` 1.8.0
