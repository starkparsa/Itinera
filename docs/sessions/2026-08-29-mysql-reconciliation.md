# 2026-08-29 — Local dev MySQL wasn't actually the MySQL in use

**`.env`'s `DATABASE_URL` pointed at `localhost:3306` — a native Windows
MySQL80 service unrelated to this project, with the wrong password for
`travel_user`. Real local dev had actually been split across two different
databases: Docker's MySQL (with its own real history) and an accidentally
git-committed SQLite file.**

## What happened

- User correctly doubted MySQL had actually been in use. Investigation
  found `backend/_dev_site.db`, a real populated SQLite file (2 users, 3
  conversations, 26 messages, 6 trips, schema at the current migration
  head) that had been **committed to git** — bundled into the unrelated
  `12fdcd6 "wiki updates"` commit, presumably an accidental `git add .`.
- Docker's MySQL container (`docker-compose.yml`'s `mysql` service, host
  port 3307) turned out to already exist (created 2 days prior) with its
  **own**, larger, real dataset: 3 users, 5 conversations, 16 messages, 20
  trips, 239 itinerary items, 2 Calendar credentials — but one migration
  behind head (missing `tour_guide_mode`).
- The native MySQL80 Windows service on port 3306 (`.env`'s actual target)
  was a red herring the whole time — unrelated to this project, its
  `travel_user` password didn't match `.env`'s `travel_pass`, and no admin
  rights were available from this session to reset it.

## Resolution (per explicit user decisions)

1. Untracked `backend/_dev_site.db` from git, added it to `.gitignore`
   (kept on disk, not deleted).
2. Started Docker's MySQL (`docker compose up -d mysql`) rather than
   pursuing the native service further — no admin rights or root password
   needed, and it already matched `docker-compose.yml`'s documented
   credentials with zero manual provisioning.
3. Ran `alembic upgrade head` against it (`f0fa120ecdf7 -> 65524d890048`,
   adding `conversations.tour_guide_mode`) — confirmed all existing data
   (3 users, 5 conversations, 20 trips, etc.) survived intact.
4. Docker MySQL's data was kept as the one true history; the SQLite file's
   data was **not** merged in (explicit user choice — avoids silently
   colliding two independently-numbered primary-key sequences).
5. `.env`'s `DATABASE_URL` updated `localhost:3306` -> `localhost:3307`
   (matches what `README.md` already documented as the Docker-mapped
   port -- the README was correct the whole time, `.env` just hadn't kept
   up).
6. Verified live: backend boots clean against the new URL, `/health`
   returns ok, no errors in logs, row counts and schema confirmed via
   direct `docker exec mysql` queries.

## Key learning

`docker ps` returning empty at one point earlier in this session (while
debugging the original MySQL connection failure) was accurate at that
moment but misleading in hindsight -- the Docker MySQL container existed
the whole time, just stopped, not "never set up." Checking `docker compose
ps <service>` (which shows stopped-but-defined services) would have
surfaced this immediately instead of concluding no Docker MySQL existed.

## Open items / follow-ups

- `backend/_dev_site.db`'s data (2 users, 3 conversations, 6 trips,
  including today's live tour-guide-mode verification conversation) is
  now orphaned -- still on disk, untracked, not read by the app. Not
  deleted in case it's wanted later; revisit only if it comes up.
- CLAUDE.md's decision log updated with the full story under the
  "Database: MySQL -> Postgres on Neon" row; no other docs needed
  changes (README already correctly documented the 3307 port).
