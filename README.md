# Headcount

**Distributed classroom attendance system using rotating QR codes.**

An admin display shows a QR code embedding a short-lived opaque token that rotates every few seconds. Students mark attendance by scanning the *live* code. Because tokens expire before they can be relayed, screenshot-and-share spoofing doesn't work.

Built to run as multiple stateless API instances behind a load balancer, sharing Redis so any instance can validate any scan.

---

## Stack

**Python** · **FastAPI** · **Redis** · **PostgreSQL** · **nginx** · **Prometheus** · **Grafana** · **Docker Compose**
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

**Black-box testing.** Tests drive the system over HTTP with no imports from the application package, so they exercise the real nginx → app → Redis → Postgres path rather than a mocked stand-in.

---

## Status

Working end to end: token rotation and validation, exactly-once scan handling, multi-instance deployment behind nginx, async scan persistence to Postgres, and an HTTP test suite covering the valid / duplicate / forged / expired token paths.

Each session has its own rotation interval and lock. Prometheus collects live metrics from every API replica, Redis, and Postgres; Grafana includes a provisioned dashboard.

---

## Next steps

- **Throughput benchmark** — validated scans/sec across N instances under load
- **Failure injection** — prove zero stale-token acceptances under concurrency, and clean recovery after a Redis restart
- **Audit logging** on rejection paths, to back the benchmark numbers with evidence
- **Auth boundary** on the student identifier in scan payloads
- Migrate the remaining synchronous Redis calls to `redis.asyncio`

---

## Running locally

```bash
git clone https://github.com/jaminatore/head-count.git
cd head-count
cp .env.example .env.docker
docker compose --env-file .env.docker up -d --build --scale app=3
```

This starts nginx, three API replicas, Postgres, Redis, their exporters, Prometheus, and Grafana. Open the app at http://localhost:1234, the [Grafana dashboard](http://localhost:3001/d/headcount-live/headcount-live-metrics), and [Prometheus targets](http://localhost:9090/targets). Grafana's local default login is `admin` / `admin`; set `GRAFANA_ADMIN_PASSWORD` in `.env.docker` before starting it if you want a different initial password. Set `GRAFANA_PORT` there to use a different host port.

The Compose migration step also adds the `sessions.reload_time` column with a five-second default when upgrading an older persisted Postgres volume. It leaves existing session rows in place.

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
