# Deployment guide: backend on Cloud Run, frontend on Vercel

**Status: a walkthrough, not yet executed. Written 2026-08-30, chosen from
the comparison in `docs/deployment-readiness.md` §2 — Cloud Run because
its Always Free tier (2M requests/month, permanent, not a trial) makes
this a genuinely $0 deployment at this app's traffic level, and it reuses
the Google Cloud project already set up for OAuth.**

Follow `docs/deployment-readiness.md` §1 and `docs/security-review.md`
first for the pre-deploy code changes (CORS, secret handling, etc.) — this
doc assumes those are done and just walks the actual deploy.

## Prerequisites

- The Google Cloud project you already created for OAuth
  (`AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` in `.env`) — Cloud Run lives in
  the same project, no new Google account needed.
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) installed and
  Docker running locally (to build the image before pushing).
- A [Vercel](https://vercel.com) account (free, GitHub login is enough).
- Your Neon connection string (already in `.env` as `DATABASE_URL` from
  the earlier migration) and every other real secret currently in `.env`.
- A billing account attached to the Google Cloud project — Cloud Run
  **requires one on file even to use the free tier** (Google's standard
  model: you won't be charged within Always Free limits, but the project
  needs billing enabled to deploy at all). If this project doesn't have
  one yet, add it in Cloud Console → Billing before continuing.

## Part 1 — Backend to Cloud Run

### 1.1 One-time setup

```bash
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>
gcloud config set run/region us-east1   # or whichever region is closest to you/Neon

gcloud artifacts repositories create travel-planner \
  --repository-format=docker \
  --location=us-east1

gcloud auth configure-docker us-east1-docker.pkg.dev
```

### 1.2 Build and push the backend image

From the repo root:

```bash
docker build -t us-east1-docker.pkg.dev/<YOUR_PROJECT_ID>/travel-planner/backend:latest ./backend
docker push us-east1-docker.pkg.dev/<YOUR_PROJECT_ID>/travel-planner/backend:latest
```

(This is the same [`backend/Dockerfile`](../backend/Dockerfile) already
used locally and by CI — no changes needed to build it for Cloud Run.)

### 1.3 Put secrets in Secret Manager, not `--set-env-vars`

Real secrets (`GEMINI_API_KEY`, `GROQ_API_KEY`, `AUTH_BACKEND_SECRET`,
`AUTH_GOOGLE_SECRET`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`) should go
into [Secret Manager](https://cloud.google.com/secret-manager), not a
plaintext `--set-env-vars` flag (which is visible in Cloud Console/`gcloud`
service description to anyone with viewer access to the project):

```bash
# Repeat for each secret -- reads the value from your local .env so it's
# never typed on the command line / shell history.
echo -n "<value>" | gcloud secrets create GEMINI_API_KEY --data-file=-
echo -n "<value>" | gcloud secrets create GROQ_API_KEY --data-file=-
echo -n "<value>" | gcloud secrets create AUTH_BACKEND_SECRET --data-file=-
echo -n "<value>" | gcloud secrets create AUTH_GOOGLE_SECRET --data-file=-
echo -n "<value>" | gcloud secrets create TOKEN_ENCRYPTION_KEY --data-file=-
echo -n "<value>" | gcloud secrets create DATABASE_URL --data-file=-
```

### 1.4 Deploy

```bash
gcloud run deploy travel-planner-backend \
  --image us-east1-docker.pkg.dev/<YOUR_PROJECT_ID>/travel-planner/backend:latest \
  --region us-east1 \
  --allow-unauthenticated \
  --port 8000 \
  --set-env-vars AUTH_GOOGLE_ID=<value>,GEMINI_MODEL=gemini-3.5-flash-lite \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,GROQ_API_KEY=GROQ_API_KEY:latest,AUTH_BACKEND_SECRET=AUTH_BACKEND_SECRET:latest,AUTH_GOOGLE_SECRET=AUTH_GOOGLE_SECRET:latest,TOKEN_ENCRYPTION_KEY=TOKEN_ENCRYPTION_KEY:latest,DATABASE_URL=DATABASE_URL:latest
```

`--allow-unauthenticated` is required — this is a public API the frontend
calls directly, not a private service; Cloud Run's own IAM auth is a
different mechanism than this app's JWT bridge (`auth.py`) and would
conflict with it, not add to it. Note the printed **Service URL**
(`https://travel-planner-backend-<hash>-<region>.a.run.app` or similar) —
you need it for every step below.

Leave `--min-instances` unset (defaults to 0, i.e. scales to zero) to stay
inside the free tier; only set `--min-instances 1` if you decide the small
cold start is worse than a guaranteed non-zero monthly bill (see
`deployment-readiness.md`'s Cloud Run row for that trade-off).

### 1.5 Run the database migration once, against the deployed config

The app's own `create_all()`-on-startup already handles a fresh DB, but
since this is pointing at the *same* Neon database as local dev (already
migrated, already has data), there's nothing to run here — just confirm
the deployed service can actually reach Neon:

```bash
curl https://<your-cloud-run-url>/health
```

## Part 2 — Frontend to Vercel

### 2.1 Import the repo

In the Vercel dashboard: **Add New → Project → Import** your GitHub repo.
Vercel auto-detects Next.js — set the **Root Directory** to `frontend/`
(this is a monorepo with `backend/` alongside it, so this step matters,
it won't build correctly from the repo root).

### 2.2 Set environment variables

In the project's **Settings → Environment Variables**, add everything from
[`frontend/.env.local.example`](../frontend/.env.local.example), with
production values:

| Variable | Value |
|---|---|
| `BACKEND_URL` | The Cloud Run Service URL from step 1.4 |
| `AUTH_GOOGLE_ID` | Same value as the backend's |
| `AUTH_GOOGLE_SECRET` | Same value as the backend's |
| `AUTH_SECRET` | Generate a **new** one for prod: `npx auth secret` |
| `AUTH_URL` | Your real Vercel URL once known (see 2.3) — or your custom domain if you're attaching one |
| `AUTH_BACKEND_SECRET` | **Exact same value** as the backend's `AUTH_BACKEND_SECRET` secret (step 1.3) — a mismatch here 401s every backend call |

### 2.3 Deploy, then fix the two things that need the real URL

Vercel deploys automatically on this first import. Once it's live, you'll
have a real URL (`https://<project>.vercel.app` or your custom domain).
Two things need it:

1. **Update `AUTH_URL`** in Vercel's env vars to match, then redeploy
   (Vercel → Deployments → redeploy, or just push a commit).
2. **Add it as an Authorized redirect URI** in Google Cloud Console →
   APIs & Services → Credentials → your OAuth client:
   `https://<your-vercel-url>/api/auth/callback/google` — login will fail
   with a Google-side error until this is added.

## Part 3 — Close the loop back on the backend

### 3.1 Tighten CORS to the real frontend URL

This is the fix already flagged as the #1 item in
`docs/deployment-readiness.md` — now you have the real URL to put there:

```python
# backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://<your-vercel-url>"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Rebuild and redeploy the backend image (repeat 1.2 and 1.4 — `gcloud run
deploy` with the same service name updates it in place, no downtime for a
low-traffic app).

### 3.2 Publish the Google OAuth consent screen

Still in "Testing" status per `CLAUDE.md`'s decision log — caps refresh
tokens at 7 days, meaning real users lose Calendar push weekly. Google
Cloud Console → APIs & Services → OAuth consent screen → **Publish App**.
This is a manual console step with no CLI equivalent worth scripting.

## Verification checklist

- [ ] `curl https://<cloud-run-url>/health` returns `{"status":"ok"}`
- [ ] Visiting the Vercel URL redirects to `/login` when signed out
- [ ] "Continue with Google" reaches Google's real consent screen (not an
      `invalid_client`/`redirect_uri_mismatch` error — both mean 2.3 or
      3.2 wasn't done correctly)
- [ ] After signing in, sending a real trip prompt gets a real itinerary
      back (proves `BACKEND_URL`, CORS, and the JWT bridge are all wired
      correctly together — any one being wrong breaks this specific step)
- [ ] Browser devtools Network tab shows no CORS errors on the
      `/trips/generate` call specifically (confirms 3.1 took effect)

## Rollback

Both platforms keep prior deployments: `gcloud run services update-traffic
travel-planner-backend --to-revisions=<previous-revision>=100` for the
backend, and Vercel's **Deployments** tab has a one-click "Promote to
Production" on any earlier build for the frontend. Neither requires a new
build — both roll back to an already-built artifact.
