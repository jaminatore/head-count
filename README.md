# Headcount

**Distributed classroom attendance system using rotating QR codes.**

An instructor display shows a QR code embedding a short-lived opaque token that rotates every few seconds. Students mark attendance by scanning the *live* code. Old screenshots expire quickly, although a copied current code can still be forwarded within its short validity window.

Built to run as multiple stateless API instances behind a load balancer, sharing Redis so any instance can validate any scan.

---

## Stack

**Python** · **FastAPI** · **Redis** · **PostgreSQL** · **nginx (local) / Caddy (production)** · **Prometheus** · **Grafana** · **Docker Compose**
SQLAlchemy (async) · Pydantic · pytest

---

## Architecture

```
              ┌─────────┐
              │  nginx  │
              └────┬────┘
          ┌────────┼────────┐
       ┌──▼──┐  ┌──▼──┐  ┌──▼──┐
       │app 1│  │app 2│  │app N│
       └──┬──┘  └──┬──┘  └──┬──┘
          └────────┼────────┘
              ┌────┴────┐
         ┌────▼───┐ ┌───▼──────┐
         │ Redis  │ │ Postgres │
         └────────┘ └──────────┘
```

Redis holds live tokens and handles scan deduplication. Postgres is the system of record for sessions and attendance. The two are joined on session UUID: `session:{id}:live_token` ↔ `sessions.id`.

---

## Engineering highlights

**Opaque tokens, not JWTs.** `secrets.token_urlsafe(16)` stored server-side. A JWT stays valid until it expires; an opaque token can be revoked the instant it rotates.

**Exactly-once scans under concurrency.** Naive check-then-act validation has a race window where two concurrent scans of the same token both pass. Redis `SET NX` collapses the check and the write into one atomic operation, so exactly one wins. A Postgres `UniqueConstraint` backstops the fast path.

**Leaderless rotation.** With N instances running, all of them want to rotate the token when it expires. A Redis Lua script — which executes atomically, so nothing can interleave between the read and the conditional write — guarantees exactly one instance wins each rotation round. No leader election, no coordinator, no single point of failure.

**Fail-closed degradation.** If Redis is unreachable, scans are rejected rather than accepted. No attendance record is better than a fraudulent one.

**Testing.** Unit tests cover authentication, scan decisions, and records. CI also runs a disposable, no-host-port Compose stack with a test OIDC issuer. Its black-box runner signs in as a teacher and student through nginx, then exercises enrollment, token rotation, concurrent scans, records, exports, audit, and metrics over HTTP. No school credentials or production volumes are used.

---

## Status

Working locally: token rotation and validation, duplicate scan handling, multi-instance deployment behind nginx, async scan persistence to Postgres, and authenticated instructor/student flows. School OIDC remains configurable but has not been verified against a real issuer.

Each session has its own rotation interval and lock. The instructor page lets you choose a course, start a session, display its live QR code, and end the session. Prometheus collects live metrics from every API replica, Redis, and Postgres; Grafana includes a provisioned dashboard.

---

## Before a real classroom

- Configure and verify the school's OIDC issuer/client, domain, DNS, and HTTPS certificate.
- Configure an alert recipient, off-host encrypted backups, retention policy, and a restore drill.
- Run the teacher/student phone pilot in the deployment runbook, including a manual fallback.
- Verify sign-in against the real school SSO, then run load and failure-injection tests.

---

## Running locally

```bash
git clone https://github.com/jaminatore/head-count.git
cd head-count
cp .env.example .env.docker
docker compose --env-file .env.docker up -d --build --scale app=3
```

This starts nginx, three API replicas, Postgres, Redis, their exporters, Prometheus, and Grafana. Open the app at http://localhost:1234, the [Grafana dashboard](http://localhost:3001/d/headcount-live/headcount-live-metrics), and [Prometheus targets](http://localhost:9090/targets). Grafana's local default login is `admin` / `admin`; set `GRAFANA_ADMIN_PASSWORD` in `.env.docker` before starting it if you want a different initial password. Set `GRAFANA_PORT` there to use a different host port.

Configure `OIDC_METADATA_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and a long random `AUTH_SESSION_SECRET` in `.env.docker`. Register `<PUBLIC_BASE_URL>/auth/callback` as the provider callback. Set `PUBLIC_BASE_URL` to the site's public origin. Set `COOKIE_SECURE=true` behind HTTPS. For a shared school issuer, set `OIDC_REQUIRED_CLAIMS_JSON` to the required verified ID-token claims. See the [Gmail test sign-in guide](docs/google-test-login.md) for named test users and the later Workspace restriction. Without the core OIDC values, the app shows a configuration message instead of allowing an insecure login.

The first successful SSO login creates a student account. An operator can grant instructor access with `docker compose --env-file .env.docker exec app python -m app.manage_user grant-instructor teacher@school.edu`. The user can then reload to see the instructor page. Instructor permissions are never inferred from an email domain. Existing pre-SSO users can be linked by an operator using `python -m app.manage_user link-identity EMAIL ISSUER SUBJECT` inside the app container; the issuer and subject must come from the verified school identity provider. The callback does not auto-link accounts by email.

For a second local identity without another Gmail account, use the [loopback-only mock login guide](docs/local-mock-login.md). It reuses the disposable OIDC provider from CI and keeps the production deployment separate.

Instructors can select their own course, choose the QR rotation interval, and click **Start attendance**. The page refreshes the QR code once a second and restores the active session after a browser reload. Click **End attendance** to close it. The `/current` token, course list, and session controls require an authenticated instructor who owns the course.

The QR opens `<PUBLIC_BASE_URL>/check-in` on a student's phone. The student signs in with school SSO, then scans the current code again if sign-in took longer than the rotation interval. The check-in page submits the code and shows success, duplicate, expired, closed-session, or not-enrolled feedback. The API derives the student identity from the browser session, checks enrollment, and atomically checks the active session and live token in Redis before writing attendance. It never trusts a student UUID from the request. A copied live QR URL can still be forwarded during its short validity window; this app does not prove physical presence.

Instructors use **Records** from the live display to create courses, share each course's join code, approve student requests, review live and past sessions, download attendance CSVs, and make manual corrections. Students enter a join code on the check-in page; the request stays pending until an instructor approves it. Corrections require a reason, preserve the attendance row by marking it void rather than deleting it, and create an audit event with the actor and before/after state. Scan outcomes also create audit events. Course and attendance APIs are scoped to the owning instructor.

The Compose migration step also adds the `sessions.reload_time` column with a five-second default when upgrading an older persisted Postgres volume. It leaves existing session rows in place.

For a provider-neutral HTTPS deployment, use [the classroom deployment runbook](docs/deployment.md) and `docker-compose.prod.yml`. It is a separate Compose project with private Postgres/Redis, secure-cookie and OIDC startup checks, tracked migrations, readiness checks, a backup script, and Prometheus alert rules. Live school SSO, a public domain/certificate, notification delivery, privacy policy, and a real classroom pilot still require operator configuration and verification.

Prometheus uses Docker DNS to discover and scrape every `app:8000/metrics` replica independently. It also scrapes the Redis and Postgres exporters. The app's `/metrics` route is reachable within the Compose network, but nginx returns 404 for it on the public app port. Prometheus and Grafana bind to localhost only.

The dashboard shows scan outcomes and rate, active sessions, HTTP latency, token rotation lag and errors, rotator age by replica, and Redis/Postgres health. The active-session gauge reads Redis on each scrape, so its value is the same on every API replica; use `max(headcount_active_sessions)` in PromQL rather than summing it. Other app counters are per replica and should be summed when viewing cluster totals. Metric labels are bounded and contain no student, course, session, or token IDs.

Useful queries in Grafana Explore or Prometheus:

```promql
sum by (result) (rate(headcount_scans_total[5m]))
histogram_quantile(0.95, sum by (le) (rate(headcount_rotation_lag_seconds_bucket[5m])))
time() - headcount_rotator_last_iteration_timestamp_seconds
```

If Redis is unavailable during a metrics scrape, the app still exposes its process counters, sets `headcount_metrics_redis_query_success` to `0`, and reports `headcount_active_sessions` as `NaN` until the next successful scrape. The rotator retries after failures and records them in `headcount_rotator_errors_total`.

Prometheus and Grafana keep data in named Docker volumes. Run `docker compose --env-file .env.docker down` to stop the stack without deleting that history. `down -v` removes the Postgres, Prometheus, and Grafana volumes.

---
