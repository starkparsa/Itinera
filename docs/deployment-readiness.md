# Deployment readiness: prep, methods, and pruning candidates

**Status: mostly actioned as of 2026-08-31 — see the strikethroughs below.
Written 2026-08-30 at the user's request, after the Neon Postgres migration
(`docs/sessions/2026-08-29-neon-postgres-migration.md`) removed the last
piece of local-only infrastructure the app depended on.**

This complements `CLAUDE.md`, it doesn't replace it — current architecture
and decisions still live there. This is a one-time checklist for the
specific question "what's between here and a real public deployment,"
plus a concrete list of things worth deleting. Update or delete this file
once its items are actually done; it's not meant to be kept current
forever the way `CLAUDE.md` is.

## 1. Prep checklist, ranked by how much it'll hurt if skipped

### Must fix before any public deployment

1. ~~**CORS is wide open.**~~ **FIXED 2026-08-31.** `backend/app/main.py`
   now reads an explicit `ALLOWED_ORIGINS` env-var allow-list (defaults to
   the local Next.js dev origin) instead of `["*"]`. Set it to the real
   frontend origin at deploy time — see `docs/deployment-guide.md` §3.1.
2. **Google OAuth consent screen is still in "Testing" status.** Per
   `CLAUDE.md`'s Auth decision row, this caps refresh tokens at 7 days —
   real users would get silently logged out of Calendar push weekly.
   Publishing to Production in Google Cloud Console is a manual step in
   the console — **still open, needs you specifically**: Claude has no
   access to your Google Cloud Console session, and this isn't the kind of
   account-settings change to delegate even if it did. Google Cloud
   Console → APIs & Services → OAuth consent screen → **Publish App**. A
   real OAuth client already exists (`AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET`
   in `.env` are real, confirmed 2026-08-31), so this is reachable right
   now, not blocked on anything else.
3. **Every URL-shaped env var still says `localhost`.** `AUTH_URL`,
   `BACKEND_URL`, the Google OAuth redirect URI
   (`http://localhost:3000/api/auth/callback/google`) — audited
   2026-08-31: every one of these is already `process.env.X ?? "http://
   localhost..."` (frontend) / `os.getenv("X", "http://localhost...")`
   (backend), never a hardcoded requirement — confirmed via a full grep,
   not assumed. **No code change needed here**; this item is really "set
   real values once you have a real URL," which is inherently sequenced
   *after* the first deploy (Cloud Run/Vercel hand you the URL, then you
   feed it back in) — see `docs/deployment-guide.md` Parts 2-3. The OAuth
   redirect URI specifically needs re-registering in Google Cloud Console
   for the new domain, or login breaks outright.
4. **Secrets currently live in a plain `.env` file.** Fine for solo local
   dev; not how they should reach a real host. `docs/deployment-guide.md`
   §1.3 already covers moving them to Cloud Run's Secret Manager — this is
   a deploy-time action, not something to pre-fix in the repo.

### Should fix soon after

5. **CI builds and pushes images but never deploys them.**
   [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)'s
   `build-and-push` job stops at GHCR — there's no step that actually
   rolls the new image out anywhere. Real CD needs one more job once a
   host is picked (webhook trigger, `flyctl deploy`, a Render/Railway
   deploy hook, etc.) — the exact shape depends entirely on §2's choice.
   Deliberately sequenced after the first manual deploy (Part 1-3 of
   `docs/deployment-guide.md`), not before — automating a rollout target
   that doesn't exist yet has nothing to deploy to.
6. ~~**Gemini's free-tier request cap is a real production risk...**~~
   **Groq fallback live-verified end-to-end, 2026-08-31.** Previously
   flagged as "not yet live-verified" — confirmed live with a real network
   call to Groq (both `_call_gemini`'s structured-output path and
   `_call_gemini_chat`'s plain-chat path), triggered by a simulated Gemini
   429 so it didn't cost real Gemini quota to test. Both correctly routed
   to Groq and returned valid, correctly-parsed responses. The underlying
   risk (Gemini's free tier is genuinely low) is unchanged and still worth
   budgeting a paid tier for once usage grows — this item is about the
   fallback mechanism working, which it does.
7. **Docker images run as root, single process, no container-level health
   check.** Not urgent for a low-traffic hobby app behind a platform's own
   health checks, but worth a `USER` directive and (for the backend) an
   explicit `--workers` count if traffic ever justifies it.

### Not blocking, worth knowing

- Neon's free tier has real storage/compute-hour limits that weren't
  re-verified as part of the migration (see
  `docs/sessions/2026-08-29-neon-postgres-migration.md`) — check current
  numbers against your actual usage before assuming headroom.
- No error tracking / structured logging beyond FastAPI's defaults and
  `print()`-based retry messages in `main.py` — fine solo, would want
  something (even just a log drain from whatever host you pick) once
  anyone besides you hits a bug you can't reproduce locally.

## 2. Deployment method options

You already have Dockerfiles for both services, a working `docker-compose.yml`
(local multi-service orchestration), and CI that builds + pushes images to
GHCR — that infrastructure is the natural thing to deploy *from*, so the
options below all assume using it rather than re-architecting around a
platform's own build pipeline.

> **Correction, 2026-08-30 (same day this doc was first written):** the
> original version of this table recommended Fly.io as a free option. That
> was wrong, and I only caught it by actually searching rather than
> trusting a remembered figure — worth noting as a live example of exactly
> the discipline this project's own `CLAUDE.md` keeps insisting on for
> every free-tier claim. **Fly.io removed free allowances for new accounts
> in 2024**; a new signup gets a 2-hour/7-day trial, then requires a credit
> card, and even a minimal always-on machine runs ~$1.94/mo. Not a $0
> option anymore. Table corrected below.

### Frontend (all options — pick one regardless of backend choice)

**Vercel Hobby** is the clear pick and not really in question: free forever
for non-commercial use, no credit card, native Next.js support (this app
already uses the App Router patterns Vercel is built around, so it's
zero-rewrite), 100GB data transfer + 1M function invocations/month on the
free tier — generous for a hobby app's realistic traffic. The only
alternative worth naming is deploying the existing `frontend/Dockerfile`
to whichever backend host you pick below, so both services live on one
platform — simpler ops, but gives up Vercel's Next.js-specific
optimizations for no real benefit at this scale.

### Backend — the actual decision, laid out in full

| Option | Cost | Cold starts? | Setup effort | Notes |
|---|---|---|---|---|
| **Koyeb free instance** | $0, no card | **Yes** — scales to zero after 1hr idle, cannot be disabled on the free tier | Low — deploys the existing `backend/Dockerfile` directly | 512MB RAM / 0.1 vCPU free instance. |
| **Google Cloud Run** | **$0 in practice for this app's scale** — Always Free tier gives 2M requests/month + 360,000 GB-seconds + 180,000 vCPU-seconds *every month, permanently*, not a trial | Yes by default (scales to zero) — but cold starts on Cloud Run's gen2 execution environment are reported as meaningfully faster than a generic free-tier PaaS; can be eliminated entirely by setting `min-instances=1`, at which point it's no longer free | Medium — needs `gcloud` CLI, a Cloud Run service per container, an Artifact Registry (or reuse GHCR) | You already have a Google Cloud project for OAuth — one fewer new account to manage, everything under one billing umbrella. Genuinely the strongest "free tier" left standing among all these, worth serious consideration precisely because it's not a shrinking-scrappy-startup free tier but a permanent line item in Google's own pricing page. |
| **Render Starter (paid)** | **$7/mo** | No — Starter tier is explicitly always-on, no spin-down | Low — same Dockerfile deploy as the free tier, just a paid plan | Simplest upgrade path if you start on Render free and later want to remove cold starts. |
| **Fly.io (paid, no free tier since 2024)** | ~$2-5/mo for a small always-on machine, card required | No | Low-medium — `fly launch` detects the Dockerfile, `fly deploy` | Was this doc's original (wrong) recommendation — kept here corrected, still a reasonable paid option, just not free. |
| **DigitalOcean App Platform** | $5/mo minimum for a dynamic (non-static) container | No | Low — points at the GHCR image or the Dockerfile directly | Straightforward, predictable, no tier complexity (DO removed its old Basic/Pro tier split in favor of pay-for-what-you-pick). |
| **Railway** | Nominally free ($5 one-time + ~$1/mo ongoing credit) | No, while credit lasts | Low | Not a sustainable $0 option in practice — commonly reported as exhausted within a week or two of real use, then becomes a paid plan anyway. |
| **Self-managed VPS (Hetzner/DigitalOcean droplet)** | ~$4-6/mo | No | **Highest** — you run `docker compose up` yourself, set up a reverse proxy (Caddy/nginx) for TLS, patch the OS, monitor uptime | Closest to what already runs locally — literally the existing `docker-compose.yml` minus the `mysql` service. Full control, but real ongoing maintenance burden for a solo hobby project. |

### My honest read, now that the numbers are actually in front of us

Two real front-runners, for different reasons:

- **Google Cloud Run**, if you're willing to spend ~30 extra minutes on
  `gcloud` setup: genuinely free at this app's traffic level (not a trial,
  not a shrinking allowance), reuses infra you already pay for/manage
  (the Google Cloud project), and its cold starts are reported as
  noticeably better than a generic PaaS free tier — closest thing to
  "free and stable" actually available right now.
- **Render Starter ($7/mo)**, if $0 stops being a hard requirement and you
  just want the least new surface area: same Dockerfile-based deploy as
  every other managed option, genuinely always-on, no server you own.

Koyeb free and the self-managed VPS sit at the two extremes (cheapest-but-
cold-starts vs. most-control-but-most-maintenance) and are worth knowing
about but aren't where I'd start.

## 3. Pruning candidates

Flagging these, not deleting them — a few things in this repo that *looked*
dead turned out to be intentional (the `.ics` export endpoint, the Calendar
status endpoint — see `CLAUDE.md`'s "Codebase cleanup pass" row), so
confirm before removing rather than trusting a search alone.

| Candidate | Evidence | Confidence |
|---|---|---|
| [`frontend/src/components/ui/card.tsx`](../frontend/src/components/ui/card.tsx) | Generated during the Tailwind/shadcn redesign (2026-08-29), never actually imported anywhere — every other shadcn component (`button`, `alert`, `badge`, etc.) is used in 1+ files, `card` is used in 0. Message bubbles/day cards ended up as plain `div`s with Tailwind classes instead. | High — genuinely unreferenced, safe to delete. |
| [`backend/app/tools.py`](../backend/app/tools.py)'s combined `TOOL_SCHEMAS` export (line ~172) | Only `CURRENCY_TOOL_SCHEMAS`/`QA_TOOL_SCHEMAS`/`PLANNING_TOOL_SCHEMAS` are ever imported by `agent_service.py` — deliberately, per that file's own comment (each loop must only see its own tool). The combined export looks like a leftover from before the three loops were split apart. | Medium-high — check no test imports it before removing. |
| `backend/scripts/migrate_to_neon.py` | Its own docstring already says "safe to delete once the migration is confirmed and Docker MySQL is decommissioned." Migration is confirmed (row counts verified 2026-08-29); Docker MySQL isn't decommissioned yet. | Ready once you're confident enough in Neon to stop Docker MySQL — not yet. |
| `pymysql` in `backend/requirements.txt` | Same story — only still needed as the migration script's source-side reader. | Same as above — remove together with the script. |
| `docker-compose.yml`'s `mysql` service (`legacy-mysql` profile) | Kept deliberately as a rollback path, not started by default. | Same as above — a bundle of three related removals, not three separate decisions. |
| `backend/_dev_site.db` | The accidentally-committed SQLite file from the MySQL reconciliation session — untracked and gitignored, but still sitting on disk with now-orphaned data (today's session in `_dev_site.db` predates the Neon migration and was never merged into it, per explicit user choice at the time). | Low urgency — it's not tracked or read by anything anymore, just disk clutter. Delete whenever, or keep as a curiosity; doesn't affect anything either way. |
| `AGENT_TOOL_CALLING_ENABLED` currency tool-calling loop (`agent_service.py`) | **Not a pruning candidate — flagging so it isn't mistaken for one.** This is a fully-working feature behind a deliberate kill-switch (currently `False` by product decision, not a bug), see `CLAUDE.md`'s Weather/currency decision row. Removing the code would mean re-building it from scratch if the product decision reverses. | N/A — leave alone. |

### Suggested order if you want me to act on this

1. CORS fix (#1 above) — quick, no dependencies on anything else.
2. Delete `card.tsx` and confirm the combined `TOOL_SCHEMAS` export is
   truly unused, then remove both — quick, low-risk, verified by lint/build/tests.
3. ~~Pick a deployment target from §2~~ — done, Google Cloud Run + Vercel
   chosen; see `docs/deployment-guide.md` for the full walkthrough (steps
   #2/#3/#4 in the checklist above are folded into that guide already).
4. Once you're confident in Neon (some real time running on it, not just
   today's migration), decommission Docker MySQL and remove the three
   bundled leftovers together.
