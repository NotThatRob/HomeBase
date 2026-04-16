# Self-Hosting with Docker Compose

This is the recommended production install path for HomeBase. It runs the app,
PostgreSQL, and Caddy together, stores uploads and database data in named Docker
volumes, runs migrations on app startup, and serves the app over HTTPS by
default.

## Prerequisites

- Docker Engine with Docker Compose v2
- A DNS name pointed at your host
- Ports `80` and `443` reachable by Caddy for HTTPS certificates and browser
  traffic

HomeBase requires HTTPS in production. Production startup refuses default
secrets, missing or invalid MFA encryption keys, debug mode, disabled CSRF
protection, insecure cookies, and non-HTTPS `BASE_URL` values.

## Install

```bash
git clone https://github.com/NotThatRob/HomeBase.git
cd HomeBase
cp .env.prod.example .env
```

Edit `.env` before first boot. Set your domain in all three domain fields, then
replace every `CHANGE_ME` value:

```bash
HOMEBASE_DOMAIN=your-homebase.example.com
BASE_URL=https://your-homebase.example.com
ALLOWED_HOSTS=your-homebase.example.com
POSTGRES_PASSWORD=...
SECRET_KEY=...
TOTP_ENCRYPTION_KEY=...
ADMIN_PASSWORD=...
```

Generate a secret key with:

```bash
openssl rand -hex 32
```

Generate the separate two-factor encryption key with:

```bash
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

`TOTP_ENCRYPTION_KEY` is a server-side deployment key. It protects
authenticator secrets stored by HomeBase. Users do not need this value; they
set up two-factor authentication later from **Settings** in the web UI.
Keep this value in your secret backup and do not rotate it casually. Existing
two-factor secrets cannot be decrypted if this key is lost or changed.

Start HomeBase:

```bash
docker compose -f compose.prod.yaml up -d --build
```

The first app boot waits for PostgreSQL, runs `alembic upgrade head`, and
creates the initial admin user if no users exist.

## Verify

```bash
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs -f app
curl -I https://your-homebase.example.com/health
curl -I https://your-homebase.example.com/ready
```

Open the URL configured in `BASE_URL`, then log in with `ADMIN_USERNAME` and
`ADMIN_PASSWORD`. Change the admin password after first login.

## Network Exposure

In the production Compose file, HomeBase listens only on the private Docker
network. The app and database do not publish host ports. Caddy is the only
public service and publishes ports `80` and `443`.

To restrict a staging deployment to your current public IP, set:

```bash
HOMEBASE_ALLOWED_IPS=203.0.113.10/32
```

You can also enforce the same restriction at your cloud firewall. Keep SSH
restricted to your IP, allow `80` and `443` to the VPS, and never expose
PostgreSQL directly.

## VPS Staging

For a production-like test on a VPS or cloud host:

1. Create the VPS and point a temporary DNS name at it.
2. Configure your provider firewall:
   - allow SSH only from your IP;
   - allow TCP `80` and `443` for Caddy;
   - do not allow inbound PostgreSQL.
3. Set `HOMEBASE_ALLOWED_IPS` to your public IP with `/32` if you want browser
   access locked to you while testing.
4. Deploy with `docker compose -f compose.prod.yaml up -d --build`.

Caddy needs port `80` or a DNS challenge to issue certificates. If your
firewall blocks `80`, certificate issuance can fail.

## Alternate Reverse Proxies

The included Caddy stack is the supported safe default reverse proxy. If you
use Traefik, nginx, Cloudflare Tunnel, or another proxy, keep the same
invariants:

```text
browser -> HTTPS proxy -> app:8000 on a private network
database -> private network only
BASE_URL -> https://your-domain.example
COOKIE_SECURE=true
CSRF_ENABLED=true
TOTP_ENCRYPTION_KEY=...
```

Do not run production-like deployments over plain HTTP.

## Updates

```bash
git pull
docker compose -f compose.prod.yaml up -d --build
```

The app container runs database migrations before starting. If a migration
fails, the old database and uploads volumes remain intact.

Python and frontend dependencies are pinned for repeatable production builds.
Do not edit constraints or lock files casually; refresh them only when you are
intentionally updating dependencies and can run the test suite.

## Backups

Back up `.env` separately from your data backups. It contains deployment
secrets, including `SECRET_KEY` and `TOTP_ENCRYPTION_KEY`. Keep it private, but
make sure it is recoverable.

Back up both named volumes: PostgreSQL data and uploaded files. A logical
database dump plus a tarball of uploads is portable and easy to restore.

```bash
mkdir -p backups
set -a
. ./.env
set +a
docker compose -f compose.prod.yaml exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backups/homebase.sql
docker run --rm -v homebase_homebase-uploads:/data:ro -v "$PWD/backups:/backup" alpine \
    tar -czf /backup/homebase-uploads.tgz -C /data .
```

If your Compose project name is not `homebase`, Docker may use different
volume names. Check with:

```bash
docker volume ls | grep homebase
```

Keep at least one backup copy off the server. Before relying on a deployment
for important records, run a restore rehearsal into a temporary test deployment
and confirm you can log in, view assets, and open uploaded files.

## Restore

The safest restore is into a fresh host or a clean empty database. Clone the
repo, copy the original `.env` and the backup files to the host, start only
PostgreSQL, then restore the database and uploads before starting the app:

```bash
set -a
. ./.env
set +a
docker compose -f compose.prod.yaml up -d db
docker compose -f compose.prod.yaml exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backups/homebase.sql
docker run --rm -v homebase_homebase-uploads:/data -v "$PWD/backups:/backup" alpine \
    tar -xzf /backup/homebase-uploads.tgz -C /data
docker compose -f compose.prod.yaml up -d --build
```

If you restore over an existing deployment, stop the app first so no writes
happen during restore. Verify the upload volume name with `docker volume ls`
before running the upload restore command because it replaces the current
upload volume contents:

```bash
set -a
. ./.env
set +a
docker compose -f compose.prod.yaml stop app
docker compose -f compose.prod.yaml exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB" < backups/homebase.sql
docker run --rm -v homebase_homebase-uploads:/data -v "$PWD/backups:/backup" alpine \
    sh -c 'rm -rf /data/* && tar -xzf /backup/homebase-uploads.tgz -C /data'
docker compose -f compose.prod.yaml up -d
```

## Email Reminders

Email delivery is disabled by default. To enable it, set:

```bash
EMAIL_ENABLED=true
EMAIL_FROM=homebase@example.com
RESEND_API_KEY=re_...
BASE_URL=https://your-homebase.example.com
```

Digest delivery can be run manually from the app container:

```bash
docker compose -f compose.prod.yaml exec app python -m app.cli.send_digests --frequency daily --dry-run
```

For scheduled production delivery, use host-level cron/systemd or adapt the
units in `deploy/systemd/` to run `docker compose exec app python -m
app.cli.send_digests ...`. Digest command output redacts recipient email
addresses; use the user ID and request logs for troubleshooting.

## Troubleshooting

- **App exits on startup**: run `docker compose -f compose.prod.yaml logs app`.
  Production startup refuses default `SECRET_KEY`, missing or invalid
  `TOTP_ENCRYPTION_KEY`, default `ADMIN_PASSWORD`, non-HTTPS `BASE_URL`,
  disabled CSRF, insecure cookies, and an empty host allowlist.
- **Two-factor codes stop working after a restore or config change**: confirm
  the restored `.env` uses the same `TOTP_ENCRYPTION_KEY` that encrypted the
  database values. If the key was lost, affected users need two-factor
  authentication reset by an admin.
- **Database is not ready**: the app waits for PostgreSQL before migrations.
  Check `docker compose -f compose.prod.yaml logs db` if the timeout is reached.
- **Caddy cannot get a certificate**: confirm `HOMEBASE_DOMAIN` resolves to the
  VPS and ports `80` and `443` can reach Caddy.
- **Schema error**: migrations run automatically. If they fail, inspect the app
  logs and do not delete the database volume.
- **Uploads disappear**: confirm the `homebase-uploads` volume exists and is
  mounted at `/data/uploads`.
- **Login works locally but not through a domain**: confirm you are using HTTPS,
  `BASE_URL` matches the external URL, and `ALLOWED_HOSTS` includes the domain.
