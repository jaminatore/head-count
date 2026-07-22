# Headcount

**Distributed classroom attendance system using rotating QR codes.**

An admin display shows a QR code embedding a short-lived opaque token that rotates every few seconds. Students mark attendance by scanning the *live* code. Because tokens expire before they can be relayed, screenshot-and-share spoofing doesn't work.

Built to run as multiple stateless API instances behind a load balancer, sharing Redis so any instance can validate any scan.

---

## Stack

**Python** · **FastAPI** · **Redis** · **PostgreSQL** · **nginx** · **Docker Compose**
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

Currently replacing the global rotation lock with a per-session one, so each class can run its own rotation interval.

---

## Next steps

- **Per-session rotation locks** — lets each session configure its own rotation cadence instead of sharing one global interval
- **Prometheus + Grafana** — scan rate, rotation timing, rejection reasons
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
docker compose up --build
```

Brings up nginx, multiple API replicas, Postgres, and Redis.

---
