# Admin and Deployment Safety

This page is for household admins who run HomeBase themselves. It explains the
safe defaults in plain language. For exact commands, use the
[Docker self-hosting guide](../docs/self-hosting-docker.md).

## Recommended Setup

Use the production Docker Compose setup with Caddy:

- Caddy handles HTTPS.
- HomeBase is private inside Docker and is not exposed directly.
- PostgreSQL is private inside Docker and is not exposed directly.
- Uploads and database data are stored in Docker volumes.
- Database migrations run automatically when the app container starts.

The production start command is:

```bash
docker compose -f compose.prod.yaml up -d --build
```

## Required Environment Values

Before first boot, copy `.env.prod.example` to `.env` and edit it.

Set your real domain in all three domain fields:

```bash
HOMEBASE_DOMAIN=homebase.example.com
BASE_URL=https://homebase.example.com
ALLOWED_HOSTS=homebase.example.com
```

Then replace every `CHANGE_ME` value:

```bash
POSTGRES_PASSWORD=CHANGE_ME_DATABASE_PASSWORD
SECRET_KEY=CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32
ADMIN_PASSWORD=CHANGE_ME_ADMIN_PASSWORD
```

Use a generated secret key, not a password you can remember:

```bash
openssl rand -hex 32
```

## Production Safety Checks

HomeBase refuses to start in production if key safety settings are wrong. This
is intentional. It protects less experienced operators from accidentally
running an unsafe deployment.

Production startup requires:

- `BASE_URL` starts with `https://`
- `DEBUG=false`
- `COOKIE_SECURE=true`
- `CSRF_ENABLED=true`
- `SECRET_KEY` is not the default
- `ADMIN_PASSWORD` is not the default
- `ALLOWED_HOSTS` includes the real domain

If the app exits on startup, check the app logs. The error should name the
setting that needs attention.

## Staging on a VPS

For a private test on a VPS or cloud host, deploy the same way you would in
production, but restrict who can reach it.

Recommended staging approach:

- Use a temporary domain or subdomain.
- Keep HTTPS enabled.
- Allow SSH only from your IP.
- Allow Caddy to receive ports `80` and `443`.
- Do not expose PostgreSQL.
- Set `HOMEBASE_ALLOWED_IPS` to your public IP if you want browser access
  limited during testing.

Example:

```bash
HOMEBASE_ALLOWED_IPS=203.0.113.10/32
```

If your IP changes, update this value and restart the Caddy container.

## Health Checks

HomeBase has two check endpoints:

- `/health` confirms the web app is alive.
- `/ready` confirms the app can reach the database and the schema is current.

For deployment checks, use `/ready`. For basic uptime checks, use `/health`.

## Email Reminders

Email delivery is disabled by default. Leave it disabled until the core app is
working and backups are in place.

When email reminders are enabled:

- Set `EMAIL_ENABLED=true`.
- Set `EMAIL_FROM`.
- Set `RESEND_API_KEY`.
- Confirm `BASE_URL` points to the public HTTPS address.

Digest command output redacts recipient email addresses so logs are safer to
share during troubleshooting.

## Backups Matter

Back up both pieces of data:

- PostgreSQL database volume
- HomeBase uploads volume

The self-hosting guide includes backup and restore commands. Test restore steps
before relying on a deployment for important records.

## Safe Admin Habits

- Change the first admin password after first login.
- Create a separate user for day-to-day use if more than one person uses the
  app.
- Keep personal assets marked personal when they should not appear in shared
  household views.
- Review logs by request ID rather than sharing screenshots with private data.
