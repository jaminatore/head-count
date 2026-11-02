# Classroom deployment runbook

This Compose deployment is a single-host starting point, not a substitute for a school security review or a tested high-availability design. It uses a separate `headcount-prod` Compose project, so it does not reuse local development volumes.

## Before launch

1. Assign a DNS name to the server and allow inbound TCP 80/443. Caddy obtains and renews the public certificate. If the classroom is on a private-only network, supply an institution-managed TLS terminator/certificate instead of relying on public ACME.
2. Register `https://<domain>/auth/callback` with the school's OIDC provider. Obtain its discovery URL, client ID, and secret. OIDC accounts are created as students; grant instructor roles explicitly after the teacher's first sign-in.
3. Copy `.env.prod.example` to `.env.prod`, replace all placeholders, and restrict the file to the host operator (`chmod 600 .env.prod`). Use a random 32+ character `AUTH_SESSION_SECRET`, distinct database and Grafana passwords, and a percent-encoded database password in `DATABASE_URL`. Do not commit `.env.prod`.
4. Decide and document attendance retention, correction authorization, access to exports, backup retention, and the school's privacy requirements before enrolling real students. Exported CSVs and database dumps contain student data.
5. Arrange a protected host with disk encryption, OS updates, firewall rules, monitoring access over VPN/SSH tunnel, and off-host encrypted backups. The Compose file keeps Postgres and Redis off host ports; Prometheus and Grafana bind to loopback.

## Launch and verify

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
HEADCOUNT_BASE_URL=https://attendance.example.edu python3 scripts/smoke_stack.py
```

`migrate` runs tracked, forward-only schema migration 1 under a Postgres advisory lock before the app starts. Startup rejects a missing/newer schema and invalid production SSO/HTTPS settings. `/healthz` is a process check; `/readyz` checks migration state, Postgres, and Redis. Caddy denies public `/metrics`; Prometheus scrapes it on the private network.

Do not use the example values in production. If the provider or DNS is not ready, do not point real classroom traffic at the stack. Caddy needs reachable DNS and ports 80/443 to provision a public certificate.

For a real pilot, run the read-only smoke script, then sign in as a test teacher and student through the real school SSO. Grant the teacher role with `docker compose --env-file .env.prod -f docker-compose.prod.yml exec app python -m app.manage_user grant-instructor teacher@school.edu`. In a test course, request/approve enrollment, start a session, scan the QR from a phone on classroom Wi-Fi, verify duplicate and expired-code behavior, end the session, review roster/history/audit, make a reasoned correction, and download/check a CSV. Confirm the public URL and QR work on student phones, not just on the server. Prepare a manual attendance fallback for network or SSO outages.

## Backups and recovery

Run `bash scripts/backup_postgres.sh` to write a timestamped custom-format Postgres dump under `backups/` with owner-only permissions, or pass another destination directory. Schedule this with the host's scheduler and copy dumps to encrypted off-host storage. Choose retention with the school; the script intentionally does not delete old backups. Back up `.env.prod` and Caddy volumes securely, separately from source control. Redis persistence is enabled for live state, but Postgres is the attendance system of record.

Test restore on a **separate empty staging project/host** before relying on backups. Start only its Postgres service (`docker compose ... up -d postgres`) so the app migration has not yet populated the database. Then restore an explicitly chosen dump:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' \
  < /absolute/path/to/selected.dump
```

Never run that command against the live database; it is not a safe in-place recovery procedure. After staging restore, start the rest of the stack so migration checks run, then exercise the teacher/student flow. Record a recovery-time and recovery-point objective with the school.

## Monitoring and response

The bundled Prometheus rules cover no app replica, Redis/Postgres unavailability, stalled rotation, and unexpected scan errors. Inspect rules/targets on `http://127.0.0.1:9090` through an SSH tunnel; Grafana is loopback-only on port 3001 by default. **Rules do not page anyone yet.** Configure an institution-approved Grafana/Alertmanager contact point and test delivery before classroom use. Check backup age/restore success, disk capacity, certificate renewal, and host health with your host monitoring system; those are not covered by the bundled rules.

`venv/bin/pytest -q` runs the unit gate. CI also starts the isolated `docker-compose.e2e.yml` stack with three API replicas, a disposable OIDC issuer, Prometheus, and no host ports, then runs `docker compose -f docker-compose.e2e.yml run --build --rm --no-deps e2e`. The read-only smoke script checks the public security boundary. Neither simulated OIDC nor the smoke script replaces a live school-SSO and classroom pilot.
