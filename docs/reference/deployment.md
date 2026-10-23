---
status: stable
last_reviewed: 2026-10-23
owner: '@raphaelfh'
---

> **Status:** Stable · Owner: @raphaelfh

# Deployment

## Topology

```text
Browser
   │
   ▼
Vercel ─── (VITE_API_URL=https://web-production-48b398.up.railway.app) ──▶ Railway web (FastAPI + gunicorn)
                                                              │
                                                              │ Celery .delay()
                                                              ▼
                                                          Railway Redis (managed)
                                                              ▲
                                                              │ broker
                                                              │
                                                          Railway worker (Celery)
                                                              │
                                                              ▼
                                                          Supabase (Postgres + Auth + Storage)
                                                          (web also writes directly)
```

All three Railway services + the Redis plugin live in the same project, region **US East** (`us-east4-eqdc4a` — same AZ class as Supabase US East).

## Services

| Service | Builder | Start | Public | Healthcheck |
| --- | --- | --- | --- | --- |
| `web` | `backend/Dockerfile` | `alembic upgrade head && python -m app.seed && gunicorn -k UvicornWorker -w 1 -t 120 -b 0.0.0.0:${PORT:-8000}` (Dockerfile CMD) | yes — <https://web-production-48b398.up.railway.app> | `/health` |
| `worker` | `backend/Dockerfile` | `celery -A app.worker.celery_app worker --loglevel=info --queues=extractions,imports,exports,celery` (Railway custom start command — overrides Dockerfile CMD) | no | none |
| `Redis` | Railway managed plugin | n/a | private network only (`redis.railway.internal`) | n/a |

## Worker — task runner

Every Celery task in `backend/app/worker/tasks/` delegates to a single
shared runner:

```python
from app.worker._runner import run_task

@celery_app.task
def my_task(self, ...):
    async def run():
        async with AsyncSessionLocal() as db:
            ...
    return run_task(run)
```

`run_task` calls `asyncio.run(coro_factory())` — a fresh loop per task.
**Do not** cache event loops in module globals (we tried; see the
2026-05-24 incident). **Do not** cache the Supabase client at module
scope; `get_supabase_client()` returns a new instance per call, so the
httpx connection pool stays bound to the current loop.

## Observability — task-registry alerts

`LoggedTask.on_failure` emits two distinct structlog events:

| Event | Meaning | Recommended alert |
| --- | --- | --- |
| `task_failed` | Generic task crash (business error, retry exhausted). | Aggregate; alert above baseline rate. |
| `celery.task_unregistered` | The worker received a task name it has no handler for. **P1** — always caused by `celery_app.include` drift or a routing typo. | Page on first occurrence. |

The drift guard at `backend/tests/unit/test_celery_app_task_registry.py`
prevents this in CI, but the log event is the runtime safety net.

## Environment variables

The tracked templates are `backend/.env.example` and the root `.env.example`; real env files match `.gitignore` line 21 (`.env.*`). Two hosts, two requirement sets: the **Railway (backend)** tables immediately below, and the **Vercel (frontend)** subsection further down (the `VITE_` prefix rule makes them genuinely different). These tables are the canonical reference; paste the values into the Railway dashboard or use the Railway CLI to set them.

### Shared across all services

| Key | Source |
| --- | --- |
| `ENCRYPTION_KEY` | set once, never rotate (encrypted Zotero and LLM-connection keys would become unreadable); MUST be the same value across web + worker (Zotero credentials are cross-process). Both refuse to boot while it is blank or the `.env.example` placeholder, unless `SUPABASE_ENV=local` (`app/core/security.py::check_encryption_key`) |
| `SUPABASE_URL` | Supabase project settings |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase project settings |
| `DATABASE_URL` | Supabase Session pooler (used for app traffic; see [Reaching prod Postgres](#reaching-prod-postgres)) |
| `DIRECT_DATABASE_URL` | Supabase direct (used by Alembic at boot) |
| `OPENAI_API_KEY` | OpenAI dashboard |
| `LLM_DEFAULT_MODEL` | `gpt-4o-mini` — set with `LLM_PROVIDER`; since C1b this pair is the FALLBACK for projects with no stored `llm_engine` setting (the ⚙ popover writes `projects.settings.llm_engine`, which wins). MUST still be the same value across web + worker: unset projects resolve it independently in each service (`/api/v1/extraction/models` in **web**, `/api/v1/extraction/sections` in the **worker**) — a per-service mismatch silently runs two different engines for those projects. The former `OPENAI_DEFAULT_MODEL` was defined but never read at runtime |
| `DEBUG` | `false` |
| `RATE_LIMIT_PER_MINUTE` | `60` |
| `PROJECT_NAME` | `Prumo API` |
| `API_V1_PREFIX` | `/api/v1` |
| `SUPABASE_ENV` | `production` |

### Reaching prod Postgres

Connect only through the Session pooler:
`postgresql://postgres.<project-ref>:<password>@aws-1-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require`.
The direct host `db.<project-ref>.supabase.co` is IPv6-only and refuses
IPv4 clients. The password is the one in Railway `web`'s `DATABASE_URL`;
pass it inline (`DATABASE_URL=... uv run ...`), never by editing
`backend/.env`. Never use Supabase's "Reset database password": `web` and
`worker` both hold the current one.

### Service-level overrides

| Service | Key | Value |
| --- | --- | --- |
| `web` | `CORS_ORIGINS` | Comma-separated allow-list that **extends** the always-allowed defaults baked into [`backend/app/core/config.py`](../../backend/app/core/config.py) (already pins `prumoai.vercel.app` + localhost). The live value lives in the Railway `web` env — the running env is the source of truth, not this table. |
| `web` | `PUBLIC_APP_URL` | Public origin of the web app, used for links in agent results (`editor_url`). Default `https://prumoai.vercel.app`; production leaves it unset, so the default applies. There is no staging environment today; one would set its own origin here. |
| `web` | `MCP_ALLOWED_HOSTS` | Comma-separated `Host` allow-list for the `/mcp` mount (`web-production-48b398.up.railway.app` in production). Default `localhost:*,127.0.0.1:*,[::1]:*,test`; a host not listed gets 421, so leaving it unset in production fails closed. |
| `web` | `MCP_ALLOWED_ORIGINS` | Comma-separated browser `Origin` allow-list for `/mcp`. Default empty: no browser origin may call it (CLI agents send no `Origin` and pass). |
| `web` | `MCP_MAX_INFLIGHT_PER_TOKEN` | Concurrent `/mcp` requests per token per process (default 4, half the default web pool of 8, so one token cannot hold every connection); over it the request gets 429 with `Retry-After: 1`. Keep it at most half of `DB_POOL_SIZE` + `DB_MAX_OVERFLOW`. |
| `web` | `DB_POOL_SIZE` | Web engine pool size (default 5; at least 1). Rule: web `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` + the worker's connections stay at or below the pooler client cap. Production uses the Supabase pooler in session mode, capped at 15 clients: defaults give web 5 + 3 = 8, worker 2 children x up to 2 sessions = 4 (an assumption: no setting caps sessions per task), total 12, leaving 3 for migrations and admin sessions. Raising web or worker concurrency means re-doing this sum. |
| `web` | `DB_MAX_OVERFLOW` | Connections the web pool may open beyond `DB_POOL_SIZE` under load (default 3; 0 gives a fixed-size pool); counts toward the pooler cap above. |
| `web` | `DB_POOL_TIMEOUT` | Seconds a request waits for a pooled connection (default 10). Past it, or when the database refuses or drops the connection, `/mcp` answers 503 with `Retry-After: 2`, during the token lookup or the tool call alike. |
| `web` | `REDIS_URL` | `${{Redis.REDIS_URL}}` (reference variable, resolves to private network) |
| `web` | `RATE_LIMIT_STORAGE_URI` | `${{Redis.REDIS_URL}}` (reference variable). Unset falls back to `memory://`, which is per process: limits then reset on restart and are not shared across instances. |
| `web` | `TRUSTED_CLIENT_IP_HEADER` | `X-Real-IP` in production. The request header every per-IP rate-limit key reads (OAuth `/register` and `/token`, unauthenticated `/mcp`, anonymous REST). Unset keys on the TCP peer, which behind Railway's edge is the proxy: every caller then shares one bucket. Trust assumption: Railway's edge overwrites a caller-supplied `X-Real-IP` (its http logs record the real `srcIp` for a request that spoofed the header), and `web` has no TCP proxy or other public path that bypasses the edge. A value that is not one IP literal falls back to the peer. Never set it on a service reachable without the edge. |
| `worker` | `REDIS_URL` | `${{Redis.REDIS_URL}}` (reference variable) |

### Feedback / Linear

| Key | Purpose | Used by |
| --- | --- | --- |
| `LINEAR_API_KEY` | Linear personal/workspace API key (SECRET) — used to create feedback issues via the Linear GraphQL API | `web`, `worker` |
| `LINEAR_TEAM_ID` | Linear **Feedback** team UUID (key `FEE`) — in-app feedback routes here; the Prumo team is GitHub-sync/automation only, NOT the feedback target. Must be the team **UUID, not the `FEE` slug** (`issueCreate(teamId:)` requires the UUID; the slug fails). Validated at boot in `config.py`; the live value lives in the Railway env (source of truth). | `web`, `worker` |
| `FEEDBACK_MEDIA_BUCKET` | Supabase Storage bucket for feedback screenshots/clips (default `feedback-media`) | `worker` |

### Vercel (frontend) — only `VITE_*` reaches the browser

The frontend is a **Vite** SPA (not Next.js). Vite exposes **only** variables prefixed
with `VITE_` to the client bundle — `vite.config.ts` does not override the default
`envPrefix`. Every other variable (`SUPABASE_URL`, `NEXT_PUBLIC_*`, `POSTGRES_*`, …) is
absent from `import.meta.env` at build time and resolves to `undefined` in the browser.

Canonical frontend vars (set in the Vercel project for Production + Preview):

| Key | Required | Notes |
| --- | --- | --- |
| `VITE_API_URL` | yes | Railway backend base URL (`https://web-production-48b398.up.railway.app`). |
| `VITE_SUPABASE_URL` | yes | Supabase project URL — same value as the integration's `SUPABASE_URL`, but it must carry the `VITE_` prefix. |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | yes | Supabase publishable (anon) key. `VITE_SUPABASE_ANON_KEY` is accepted as a fallback. |
| `VITE_SITE_URL` | yes | Auth redirect base for the sign-up-confirmation and password-reset e-mails (`getAuthRedirectBaseUrl` in `frontend/pages/Auth.tsx`; falls back to `window.location.origin` when unset). Must equal the production origin **and** be allow-listed in Supabase — see [Supabase auth redirects](#supabase-auth-redirects-the-silent-failure) below. |
| `VITE_SUPABASE_ENV` | optional | `local` points the client at the local Supabase URL; anything else (or unset) means `production`. |

#### The Supabase ↔ Vercel integration does not feed the Vite build

Installing the integration auto-syncs (and keeps fresh) these into the Vercel project:

```text
POSTGRES_URL, POSTGRES_PRISMA_URL, POSTGRES_URL_NON_POOLING, POSTGRES_USER,
POSTGRES_HOST, POSTGRES_PASSWORD, POSTGRES_DATABASE,
SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY), SUPABASE_JWT_SECRET,
NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
```

None of them carry the `VITE_` prefix, so the Vite build ignores all of them; the app
keeps reading the manually-set `VITE_SUPABASE_*` copies. The integration is handy as a
value source and for the Studio link, but it is **not** what makes the frontend work and
it does **not** replace the `VITE_*` vars. (`frontend/config/supabase-env.ts` resolves
only `VITE_SUPABASE_*` for exactly this reason — it deliberately does not read the
non-`VITE_` names, since they are invisible to the build.)

> **Key-rotation drift — the one thing to remember.** If you rotate the Supabase
> anon/publishable key, the integration refreshes `SUPABASE_PUBLISHABLE_KEY` /
> `NEXT_PUBLIC_*` automatically but **not** `VITE_SUPABASE_PUBLISHABLE_KEY`. Update the
> `VITE_` copy by hand, or production login breaks while the integration-managed vars
> still look current.
>
> **Security trap — never widen `envPrefix`.** Do not "activate" the integration vars by
> adding `SUPABASE_`, `POSTGRES_`, or `NEXT_PUBLIC_` to `envPrefix` in `vite.config.ts`.
> That would inline `SUPABASE_SECRET_KEY` / `SUPABASE_SERVICE_ROLE_KEY` /
> `SUPABASE_JWT_SECRET` / `POSTGRES_PASSWORD` into the public JS bundle — a credential
> leak (the secret / service-role key bypasses RLS). Keep `VITE_` as the only prefix and
> re-expose just the two public values (`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`).

#### Backend secrets do not belong in the Vercel project

The Vercel project currently also holds backend-only vars (`SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_SECRET_KEY`, `DATABASE_URL`, `DIRECT_DATABASE_URL`, `ENCRYPTION_KEY`,
`OPENAI_API_KEY`, `REDIS_*`, `RAILWAY_RUN_COMMAND`, …). FastAPI runs on **Railway**, not
Vercel, so these are unused by the static build (no `VITE_` prefix → never bundled) but
are needless secret surface on a second platform. They are safe to delete from Vercel;
keep them only on Railway.

#### Supabase auth redirects: the silent failure

The sign-up-confirmation and password-reset e-mails carry a `redirect_to` built
from `VITE_SITE_URL`. GoTrue honours it **only** when it matches the project's
Redirect URLs allow list. On a miss it silently discards the value and sends the
user to the Site URL instead. Nothing fails loudly: the e-mail still arrives, the
link still works, the user just lands on the wrong page. There is no console
error, no failed request, and no build-time signal.

Two settings must therefore agree, in **Dashboard > Authentication > URL
Configuration**:

| Setting | Value | Why |
| --- | --- | --- |
| Site URL | `https://prumoai.vercel.app` | The fallback target. Must be a public origin: pointing it at the project-scoped `prumo-*.vercel.app` domain sends users into Vercel's Deployment Protection login wall. |
| Redirect URLs | `https://prumoai.vercel.app/**`, `http://localhost:8080/**` | The allow list. **The `/**` suffix is load-bearing** — a bare `http://localhost:8080` does not match `http://localhost:8080/auth/reset-password`. Local dev runs on 8080 (`vite.config.ts`), not Vite's default 5173. |

This has broken three times, always through domain drift
(`prumo` -> `prumo-alpha` -> `prumoai`). To check a redirect target after a
domain rename, ask GoTrue directly — a deliberately invalid token is read-only,
so no e-mail is sent and no auth state changes:

```bash
curl -sSI "https://<project-ref>.supabase.co/auth/v1/verify?token=invalid&type=recovery&redirect_to=https%3A%2F%2Fprumoai.vercel.app%2Fauth%2Freset-password" | grep -i '^location'
```

If the `location` echoes the URL and path you sent, it is allow-listed. If it
returns anything else, that something else is the Site URL and your redirect was
discarded. (`otp_expired` in the fragment is the expected response to the
invalid token; read the host and path only.)

`AuthProvider` also routes to the reset form whenever Supabase emits
`PASSWORD_RECOVERY`, so a same-origin allow-list miss degrades to a redirect
rather than to a silent sign-in. That safety net cannot cover a cross-origin
fallback: the PKCE verifier lives in the requesting origin's `localStorage`, so
a local-dev request falling back to the production Site URL still fails. Keep
both origins allow-listed.

## Migrations

Alembic runs automatically as part of the web service's Dockerfile `CMD`,
followed by the seed, which converges the global template catalogue on
every deploy:

```text
alembic upgrade head && python -m app.seed && gunicorn ...
```

The seed is idempotent end to end — every template seeder early-returns on
an existing row and the instruction backfill is fill-if-null — so a deploy
installs newly added global templates without a manual step and never
touches existing rows. A seed failure aborts the boot: Railway marks the
deploy failed and keeps the previous build live.

The worker does NOT run Alembic or the seed — it boots after the web
service via Celery startup. To add a migration:

1. Create it locally: `cd backend && alembic revision --autogenerate -m "description"`.
2. Test locally: `alembic upgrade head` against the local stack.
3. Open a PR to `dev`. Once merged, promote `dev → main` via a merge-commit PR, not a fast-forward push (see the deploy-release skill runbook for the commands). Railway then deploys `web`, which runs Alembic before booting gunicorn.

Auth/storage migrations (`supabase/migrations/`) are authored with the
Supabase CLI (see `docs/reference/migrations.md`) and deployed by the same
`main` push, through the Supabase GitHub integration. Its `Supabase Preview`
check on the `main` commit is not a required context, so read it after any
promotion that touches `supabase/`. Never apply one through the Supabase MCP
`apply_migration`: it records a generated version that does not match the
file, and every later integration deploy fails on the mismatch.

## Rollback

If a deploy breaks production:

1. **Fast path** (≤2 min): in the Railway dashboard → `web` service → Deployments tab → find the last green deployment → ⋯ → **Redeploy**. Railway redeploys the previous image without rebuilding.
2. **Slow path** (full revert): `git revert <bad-commit> && git push origin main`. Railway auto-deploys the revert.

To roll back the frontend, change `VITE_API_URL` in Vercel back to the previous value and redeploy.

## Deploys are triggered by

Both `web` and `worker` are wired to `raphaelfh/prumo` branch `main`,
root directory `/backend`, builder `DOCKERFILE`, with **Wait for CI**
enabled (Railway holds the deploy until the GitHub Actions workflow
on the head commit passes).

- Push to `main` → Railway queues a deploy for both services. If CI
  passes, deploys promote. If CI fails or is skipped, the Railway
  deployment is marked `SKIPPED` and stays pending until a newer
  commit's CI goes green.
- Push to `dev` → no deploy. Use `dev` for staging-style integration;
  promote `dev → main` to ship — via a merge-commit PR, not a
  fast-forward push (`main` carries merge commits dev lacks). See the
  deploy-release skill for the commands + runbook.

### What CI gates the deploy on

The Railway "Wait for CI" gate waits for every required check on the
head commit. As of 2026-05-24 the relevant ones for backend code:

1. **`backend-lint`** — ruff lint + ruff format (mypy advisory).
2. **`fitness`** — every fitness function in `scripts/fitness/`
   (migration boundaries, layered architecture, ApiResponse envelope,
   TanStack query keys, glossary sync, RLS coverage, legacy concept
   blacklist). Baselines are empty as of 2026-05-20; any new violation
   blocks merge with no grandfathering.
3. **`backend-test`** — pytest with three coverage gates:
   - **Global ratchet** (`--cov-fail-under=62`): floor that only ever
     goes up. Current `main` coverage is **71%**. Bumped from 60→62
     on 2026-05-24 after F1/F2; next target 70% after F4 lands.
     **Never lower this once raised** — if a PR drops coverage, the
     PR adds tests, not a relaxed gate.
   - **Diff coverage** (`PRUMO_DIFF_COVERAGE_MIN`, default 80%, PR-only):
     the lines a PR introduces must be ≥80% covered. Catches "new code
     without tests" before the global ratchet notices the dip.
   - **Critical-path aggregate** (`PRUMO_CRITICAL_COVERAGE_MIN`,
     default 85%): the modules listed in `backend/.coverage_critical`
     (autosave write path, run lifecycle, HITL session opener, auth
     deps, coord coherence, run lock, review service, proposal repo)
     aggregate to ≥85%. Bug there = data loss / BOLA / HITL state
     corruption. Snapshot today is 89%.
4. **`backend-e2e`** — `pytest -m e2e`.
5. **`backend-build`** — Docker image build.
6. **`frontend-lint`** + **`frontend-build`** + the ephemeral-stack
   frontend E2E (self-provisioned, no secrets needed).
7. **`docs-ci`** — runs on the same push. Railway's "Wait for CI" waits
   for the **full** Actions suite (CI **and** `docs-ci`), so a `docs-ci`
   that reports SKIPPED (path-filtered) can wedge the deploy — recover
   per the deploy-release skill (push a newer commit, or `railway up`
   from the repo root).

After a deploy, the `post-deploy-smoke` workflow (push-triggered +
every 6 hours) verifies prod in three layers; a failure emails the
owner. It is the deploy safety net, not a gate.

1. **Reachability** — `/health`, the frontend root, and a CORS preflight
   from the prod origin.
2. **Deployed commit** — `/health.commit` (the Railway-injected
   `RAILWAY_GIT_COMMIT_SHA`, surfaced via `settings`) must equal the
   promoted SHA. This is what actually catches the wedge described above:
   reachability alone cannot tell a fresh deploy from one stuck on an
   older commit. **Only the 6-hourly scheduled run fails on a mismatch.**
   A push-triggered run polls (up to ~10 min) and then merely warns,
   because it races the deploy it is verifying and a red check on the SHA
   makes Railway's wait-for-CI skip that deploy — which deadlocks prod
   into permanent staleness. That deadlock was observed on `a4dc5b65`
   (2026-08-24): the first promotion after the assertion went live had its
   deploy SKIPPED on both services, leaving prod on the previous build.
   The scheduled run is not attached to a commit, so it can page without
   wedging anything.
There is deliberately **no credentialed probe and no Playwright suite
pointed at prod**. An authenticated probe was built and then removed
(2026-08-23): beyond layer 1 it only adds the narrow delta between "JWKS
loaded at boot" (already reported by `/health.checks`) and "a freshly
minted token is accepted", which does not pay for a permanent production
password living in CI — nor for a `::warning::` on every run while it sits
without credentials, which is how a warning stops being read. The former
`remote-smoke` project dispatched a real AI extraction (LLM spend + a run
left behind per execution) and had never run in CI — no secrets were ever
provisioned — so it silently self-skipped to a green "pass".

Override the env-driven thresholds via repo variables
(`PRUMO_DIFF_COVERAGE_MIN`, `PRUMO_CRITICAL_COVERAGE_MIN`) when
deliberately experimenting; do not edit `ci.yml` for one-off tweaks.

### Manual deploy fallback

Two distinct scenarios, with different (and unequal) escape hatches:

**Deploy wedged but CI green** (QUEUED for no reason, SKIPPED-SHA
wait-for-CI wedge): re-trigger the git-linked deploy with an empty
commit merged into `main` **via PR** — `main` is protected, so a direct
push is not possible. Verified 2026-08-18 (#635):

```bash
git switch -c chore/redeploy-nudge origin/main
git commit --allow-empty -m "chore(deploy): re-trigger the Railway deploy for <sha>"
gh pr create --base main --title "chore(deploy): re-trigger the Railway deploy" --body "..."
```

**Shipping past a red CI** (e.g. coverage temporarily dips while a
spec is in flight): the documented CLI path is

```bash
# run from the repo ROOT — the older `backend --path-as-root` form is
# retired and bash-guard-blocked
railway up --service web --detach -m "<msg>"
railway up --service worker --detach -m "<msg>"
```

but it is **unverified today**: on 2026-08-18 it failed with
"Deployment does not have an associated build" (there is no root
Dockerfile; `dockerfilePath` is relative to `rootDirectory=/backend`),
and `railway up backend` fails with "prefix not found". Until a working
invocation is re-verified against the live project, assume there is no
CLI path past a red CI — fix CI or use the dashboard's Redeploy (which
only redeploys the last built image, i.e. old code).

Use these sparingly. Manual deploys bypass the gates; if you are
shipping past a red CI, document why in the deploy message.
