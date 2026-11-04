# Local mock student account

The CI OIDC issuer can also supply disposable local identities. This lets you test enrollment and check-in without creating another Gmail account. The mock provider listens on `127.0.0.1:9000`; the app remains at `http://localhost:1234`. Use only fake course and attendance data while this override is active.

Start the existing local stack with the mock-login override (one API replica, no Grafana or Prometheus):

```bash
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.local-mock.yml \
  up -d --build --scale app=1 nginx oidc
```

Open `http://localhost:9000/select/student` in a **separate browser profile or private window**. It signs in as `student@headcount.test` through the mock OIDC flow. Keep your Google instructor login in its original browser profile; both logins use a `localhost` cookie, so two tabs in one profile will replace each other's session.

In the student window, enter the class join code from **Records**. In the instructor window, approve the request. The current QR points to `localhost`, so a phone cannot use it; the local test can open the QR's URL in the student profile on this computer. Use an HTTPS staging address for the actual phone pilot. The mock account is not a Gmail account and cannot sign in through Google.

When finished, restore the real Google login configuration from the ignored `.env.docker` file and remove the mock provider:

```bash
docker compose --env-file .env.docker -f docker-compose.yml \
  up -d --build --scale app=1 --remove-orphans nginx
```

Do not use `docker-compose.local-mock.yml` with the production stack. Production startup also rejects the mock provider's HTTP discovery URL.
