# Beta deployment: Cloudflare Workers (frontend) + Cloud Run (backend) + Neon (DB)

**Status: a walkthrough, not yet executed. Written 2026-09-10, for the
specific goal of "share a working beta with people I know for testing" —
not a full public launch.** Stack decided in this session: Cloudflare
Workers replaces Vercel for the frontend (user preference, explicitly
$0 — see `decisions.md`); Neon (already in use) stays as-is; the backend
stays on **Google Cloud Run**, the same pick `docs/deployment-guide.md`
already made and verified — Cloudflare Containers (the only way to run
FastAPI on Cloudflare) requires the paid Workers plan ($5/mo), so it's
out for a $0 deploy.

Every command below assumes you're in the repo root unless a `cd` says
otherwise. Placeholders are `<LIKE_THIS>`.

## Why this combination, briefly

- **Frontend → Cloudflare Workers via OpenNext**: Cloudflare's own current
  guidance for a Next.js App Router app with Server Actions (this app
  uses both) is OpenNext on Workers, not Cloudflare Pages — Pages'
  `next-on-pages` tool only supports the Edge runtime and doesn't fully
  cover Server Actions. OpenNext instead runs on Workers' **Node.js**
  compatibility mode, which is a materially better fit: this app's
  `next-auth` v5 setup already uses JWT sessions (no database adapter —
  see `frontend/src/auth.ts`) and `jose` for signing (already
  Workers-safe), so there's no known incompatibility, but this is real
  new surface area — verify with the local `npm run preview` step below
  before trusting it in production.
- **Backend → Cloud Run, unchanged from `docs/deployment-guide.md`**:
  genuinely free at this app's scale (Always Free tier, not a trial),
  reuses the Google Cloud project already set up for OAuth. Follow
  **Part 1** of that doc as-is — it isn't repeated here, just referenced.
- **Database → Neon, unchanged**: nothing to migrate. Already exactly the
  "sleeps when idle, wakes on the next query, handles a lot of concurrent
  requests" shape (autosuspend after 5 min idle, wakes in a few hundred
  ms, PgBouncer pooler up to 10,000 client connections) — no action
  needed here beyond what local dev already has.

## Part 0 — Prerequisites

- Everything in `docs/deployment-guide.md`'s own Prerequisites section
  (Google Cloud project + billing enabled, `gcloud` CLI, Docker running).
- A free [Cloudflare account](https://dash.cloudflare.com/sign-up) — no
  card required for the Workers Free plan used here.
- Node 18.18+ locally (already required for `frontend/`).

## Part 1 — Backend to Cloud Run

**Follow `docs/deployment-guide.md` Part 1 exactly, steps 1.1–1.5.**
Nothing changes here — Neon's connection string is the same
`DATABASE_URL` already in Secret Manager per that doc's step 1.3. Note
the **Service URL** it prints; you need it below as `BACKEND_URL`.

Skip that doc's Part 2/3 (Vercel-specific) — continue here instead.

## Part 2 — Frontend to Cloudflare Workers (OpenNext)

### 2.1 Install the adapter

```bash
cd frontend
npm install @opennextjs/cloudflare@latest
npm install --save-dev wrangler@latest
```

### 2.2 Add `wrangler.jsonc` (repo root of `frontend/`)

```json
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "main": ".open-next/worker.js",
  "name": "itinera",
  "compatibility_date": "2026-09-10",
  "compatibility_flags": ["nodejs_compat", "global_fetch_strictly_public"],
  "assets": {
    "directory": ".open-next/assets",
    "binding": "ASSETS"
  },
  "vars": {
    "BACKEND_URL": "<YOUR_CLOUD_RUN_SERVICE_URL>"
  }
}
```

`BACKEND_URL` isn't secret (it's just a URL), so it's fine as a plain
`vars` entry here rather than a Wrangler secret. Everything with a real
secret value goes through `wrangler secret put` instead (2.5) — never
committed to this file.

### 2.3 Add `open-next.config.ts` (same directory)

```typescript
import { defineCloudflareConfig } from "@opennextjs/cloudflare";

export default defineCloudflareConfig();
```

(No R2 incremental cache override needed — this app has no ISR/ on-demand
revalidation to speak of; add one later only if that changes.)

### 2.4 Wire up scripts and local preview

Add to `frontend/package.json`'s `scripts`:

```json
"preview:cf": "opennextjs-cloudflare build && opennextjs-cloudflare preview",
"deploy:cf": "opennextjs-cloudflare build && opennextjs-cloudflare deploy"
```

Add to the top of `frontend/next.config.ts` (dev-only, no effect on the
real build):

```typescript
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";
initOpenNextCloudflareForDev();
```

Create `frontend/.dev.vars` (git-ignored — add it to `.gitignore` now):

```
BACKEND_URL=http://localhost:8000
AUTH_GOOGLE_ID=<same value as frontend/.env.local>
AUTH_GOOGLE_SECRET=<same value as frontend/.env.local>
AUTH_SECRET=<same value as frontend/.env.local>
AUTH_URL=http://localhost:3000
AUTH_BACKEND_SECRET=<same value as frontend/.env.local>
```

**Before deploying anywhere, run the local Workers preview and actually
click through a real login + trip generation:**

```bash
npm run preview:cf
```

This is the real compatibility check this doc's "Why this combination"
section flagged as unverified — `next-auth`'s OAuth callback flow and
Server Actions haven't been exercised on the Workers runtime in this
codebase before. If anything breaks here, it's cheaper to find out now
than after a real deploy.

### 2.5 Set production secrets

Real secrets never go in `wrangler.jsonc`. From `frontend/`:

```bash
echo -n "<value>" | npx wrangler secret put AUTH_GOOGLE_SECRET
echo -n "<value>" | npx wrangler secret put AUTH_BACKEND_SECRET   # must exactly match the backend's own secret (Part 1)
npx auth secret   # generates a NEW value for prod -- do not reuse the local one
echo -n "<the value auth secret just printed>" | npx wrangler secret put AUTH_SECRET
```

`AUTH_GOOGLE_ID` isn't secret — add it to `wrangler.jsonc`'s `vars`
alongside `BACKEND_URL` instead of a `wrangler secret put` call.

`AUTH_URL` needs the real deployed Workers URL, which you don't have
yet — see 2.7.

### 2.6 First deploy

```bash
npm run deploy:cf
```

This prints your real Workers URL:
`https://itinera.<your-subdomain>.workers.dev`.

### 2.7 Fix `AUTH_URL` now that you have the real URL

```bash
echo -n "https://itinera.<your-subdomain>.workers.dev" | npx wrangler secret put AUTH_URL
npm run deploy:cf   # redeploy so the change takes effect
```

## Part 3 — Close the loop back on the backend

### 3.1 Point CORS at the real Workers URL

Same mechanism as `docs/deployment-guide.md` §3.1, just a different
origin:

```bash
gcloud run services update itinera-backend \
  --set-env-vars ALLOWED_ORIGINS=https://itinera.<your-subdomain>.workers.dev
```

### 3.2 Register the OAuth redirect URI

Google Cloud Console → APIs & Services → Credentials → your OAuth
client → **Authorized redirect URIs** → add:

```
https://itinera.<your-subdomain>.workers.dev/api/auth/callback/google
```

## Part 4 — Add your beta testers, without publishing the app

The consent screen is still in **Testing** status (per `decisions.md`'s
Auth entry) — that's fine for a beta with people you know, and it's
*less* work than `docs/deployment-guide.md`'s §3.2 "Publish App" step,
which this doc deliberately skips:

Google Cloud Console → APIs & Services → **OAuth consent screen → Test
users** → add each tester's real Google account email (up to 100).

Two things worth telling your testers up front, both real consequences
of staying in Testing mode rather than publishing:
- They'll see an "unverified app" warning on first login — expected,
  they click through it.
- Their Google Calendar push refresh token expires after 7 days — if a
  tester goes quiet for over a week, they'll need to sign in again for
  Calendar push to keep working. Doesn't affect trip planning itself,
  only the Calendar export feature.

## Verification checklist

- [ ] `curl https://<cloud-run-url>/health` returns `{"status":"ok"}`
- [ ] `npm run preview:cf` locally: login, a real trip prompt, and Google
      Calendar export all work against the Workers runtime *before* any
      real deploy
- [ ] Visiting the Workers URL redirects to `/login` when signed out
- [ ] "Continue with Google" reaches the real consent screen (not
      `invalid_client`/`redirect_uri_mismatch` — both mean 3.2 wasn't
      done correctly)
- [ ] A tester who is NOT you (added in Part 4) can sign in and see the
      "unverified app" screen, click through, and reach the app
- [ ] A real trip prompt after sign-in gets a real itinerary back
      (proves `BACKEND_URL`, CORS, and the JWT bridge are all correctly
      wired together)
- [ ] Browser devtools Network tab shows no CORS errors on
      `/trips/generate` specifically (confirms 3.1 took effect)

## Rollback

`npx wrangler deployments list` shows prior Worker deployments;
`npx wrangler rollback <deployment-id>` reverts to one instantly, no
rebuild needed. Cloud Run rollback is unchanged from
`docs/deployment-guide.md`'s own Rollback section.

## What's deliberately NOT in scope here

- Publishing the OAuth consent screen to Production — stays in Testing
  per Part 4's reasoning; revisit only when this moves past a beta with
  people you know.
- A custom domain — both the Workers URL and the Cloud Run URL work as
  real HTTPS URLs on their own; attaching a domain is a separate,
  optional step (Cloudflare Workers Custom Domains) not needed to get a
  beta in front of testers.
- CI/CD automation of this deploy — `docs/deployment-readiness.md`'s
  item 5 (CI builds and pushes images but never deploys) is still open;
  this doc is a manual walkthrough, same status as
  `docs/deployment-guide.md` was before its own first execution.
