# HomeBase

Personal asset management system for tracking everything you own — specs, documents, service history, costs, and maintenance schedules. Built for a two-person household.

## Project Status

> **HomeBase is no longer under active development.** The app works, but I'm
> not building new features. Contributions and forks are very welcome. See
> [Contributing](#contributing) for known issues and ideas.

HomeBase is a self-hostable beta. It is intended for careful household use in
isolated or personally managed environments. Before relying on it for important
records, deploy with the Docker + Caddy guide, change all production secrets,
verify backups, and practice a restore.

<img width="1369" height="754" alt="Webpage" src="https://github.com/user-attachments/assets/804720e9-ef1f-4566-89bc-2a1b582564eb" />

## Contents

- [Project Status](#project-status)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [User Guide](#user-guide)
- [Self-hosting with Docker Compose](#self-hosting-with-docker-compose)
- [Manual Development Setup](#manual-development-setup)
- [Diagnostics](#diagnostics)
- [Running tests](#running-tests)
- [Linting](#linting)
- [Dev seed data](#dev-seed-data)
- [Maintenance digests](#maintenance-digests)
- [Logging](#logging)
- [Schema guard](#schema-guard)
- [Manual Python deploy order](#manual-python-deploy-order)
- [Manual Setup Troubleshooting](#manual-setup-troubleshooting)
- [Security Notes](#security-notes)
- [Contributing](#contributing)
- [Reporting a Vulnerability](#reporting-a-vulnerability)
- [Acknowledgments](#acknowledgments)
- [License](#license)

## Tech Stack

- **Backend**: Python 3.12+ / FastAPI (sync handlers)
- **Frontend**: HTMX + Jinja2 (server-rendered, local static assets)
- **Database**: PostgreSQL 17 + SQLAlchemy 2.0 + Alembic
- **Styling**: Tailwind CSS generated into local CSS with custom color tokens
- **Icons**: Local inline SVG icon renderer
- **Auth**: Signed session cookies via itsdangerous

## Features

- Session-based authentication with admin auto-seeding on first run
- Optional authenticator-app two-factor authentication with recovery codes
- Settings page for profile updates, password changes, and admin-created users
- Asset CRUD with vehicle-specific metadata (VIN, mileage, fuel type, insurance)
- Component tagging (brakes, oil, filter, etc.) with category-based presets
- Document upload, preview, and download — link to asset or to a specific service record
- Service record logbook with cost, vendor, DIY flag, "next time" notes, component tags
- Recurring cost tracking for insurance, registration, subscriptions, taxes, and fees
- Quick fuel logging for vehicles with gallons, price, total cost, odometer, and MPG
- Maintenance tasks with interval, calendar, one-time, and usage-based
  schedules, plus a cross-asset Maintenance hub for status-grouped tracking
- Email reminder plumbing with per-user digest times and dry-run support;
  delivery stays disabled until configured
- Dashboard with Chart.js financial overview and recent activity feed
- Reports tab with canned cost/service views, per-entity CSV exports,
  a JSON data export, and chart PNG exports (the JSON export is not a
  restorable backup; see [Contributing](#contributing))
- Global search across assets, service records, and documents
- First-run wizard for guided onboarding
- Shared vs. personal asset visibility (personal can't be selected in the UI
  yet; see [Contributing](#contributing))

## User Guide

For day-to-day usage instructions, see the [HomeBase User Guide](user-guide/README.md).

## Self-hosting with Docker Compose

Docker Compose with Caddy is the recommended production path for public
self-hosting. It runs HomeBase, PostgreSQL, and HTTPS termination together,
keeps database data and uploads in named volumes, and runs migrations on app
startup.

```bash
git clone https://github.com/NotThatRob/HomeBase.git
cd HomeBase
cp .env.prod.example .env
# edit .env: set your domain and replace every CHANGE_ME value
docker compose -f compose.prod.yaml up -d --build
```

See [Self-Hosting with Docker Compose](docs/self-hosting-docker.md) for Caddy
HTTPS, VPS staging, backup, restore, update, email reminder, and
troubleshooting guidance.

## Manual Development Setup

You do not need this section for the recommended Docker + Caddy deployment.
Use it only if you want to run HomeBase directly with Python for local
development, tests, or a custom non-Docker deployment.

### Prerequisites

- **Python 3.12 or newer**
- **PostgreSQL 17** for the development database. You can run it in Docker or
  install it on your host.
- **Node.js 20+ and npm** only if you change templates, CSS, or frontend
  vendor assets.
- Git

### 1. Start a Development PostgreSQL Database

Pick one option. The Docker option is usually the quickest because it does not
install PostgreSQL on your host.

**Docker PostgreSQL container (any OS):**
```bash
docker run --name homebase-pg -e POSTGRES_PASSWORD=homebase -e POSTGRES_USER=homebase -e POSTGRES_DB=homebase -p 5432:5432 -d postgres:17
```

This creates the `homebase` user, password, and development database. You will
still create the test database in step 5.

If you already have PostgreSQL running locally, skip to step 2 or use one of
the host install options below.

**Windows host install (winget):**
```powershell
winget install PostgreSQL.PostgreSQL.17
```

The installer registers a Windows service that auto-starts and prompts you to
set a password for the `postgres` superuser. Write that password down; you'll
need it in step 5.

After install, **open a new PowerShell window** so `PATH` refreshes, then verify:
```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" --version
```

**Windows host install (GUI):** download from
<https://www.postgresql.org/download/windows/> and run it. Same result as
winget.

**macOS host install (Homebrew):**
```bash
brew install postgresql@17
brew services start postgresql@17
```

**Linux host install (Debian/Ubuntu):**
```bash
sudo apt install postgresql-17
sudo systemctl enable --now postgresql
```

### 2. Clone

```bash
git clone https://github.com/NotThatRob/HomeBase.git
cd HomeBase
```

### 3. Create and activate a virtual environment

The activation command differs by shell. Pick the one that matches your OS.

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

> If PowerShell blocks the script with an execution-policy error, run this once in the same session:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`

**Windows (cmd.exe):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**macOS / Linux (bash or zsh):**
```bash
python3 -m venv venv
source venv/bin/activate
```

You'll know it worked when your shell prompt is prefixed with `(venv)`.

### 4. Install dependencies

```bash
pip install -r requirements-dev.txt -c constraints-dev.txt
```

Python constraints are pinned for repeatable installs. Update them
intentionally after dependency changes.

### 5. Create the database user and databases

The app expects a `homebase` PostgreSQL user with password `homebase`, plus two databases (`homebase` for dev, `homebase_test` for tests). Skip the `CREATE USER` step if you used the Docker command in step 1 — it already created the user and dev DB, and you just need the test DB.

**Windows (PowerShell)** — using the `postgres` superuser password you set during install:
```powershell
$env:PGPASSWORD = "your-postgres-password-here"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE USER homebase WITH PASSWORD 'homebase';"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE DATABASE homebase OWNER homebase;"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -c "CREATE DATABASE homebase_test OWNER homebase;"
```
Setting `$env:PGPASSWORD` for the session avoids being prompted three times. It only lives for that PowerShell window.

**macOS / Linux** — `createdb` and `psql` ship on `PATH` after install:
```bash
psql postgres -c "CREATE USER homebase WITH PASSWORD 'homebase';"
createdb -O homebase homebase
createdb -O homebase homebase_test
```

**Docker users (from step 1):** the container already has the `homebase` user and `homebase` database. Just create the test DB:
```bash
docker exec -it homebase-pg psql -U homebase -c "CREATE DATABASE homebase_test OWNER homebase;"
```

If you'd rather use an existing Postgres user instead of creating `homebase`, edit `DATABASE_URL` in your `.env` (next step) — for example `postgresql://postgres:yourpass@localhost/homebase`.

### 6. Configure environment

**macOS / Linux:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Generate a secret key and paste it into `.env` as `SECRET_KEY=...`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The default `DATABASE_URL` in `.env.example` matches the `homebase` user,
password, and database created in step 5. Replace the entire
`SECRET_KEY=dev-secret-key-change-in-production` placeholder with the generated
value before running with `DEBUG=false`.

For production, use the Docker + Caddy deployment above. If you are building a
custom non-Docker deployment, set `ENVIRONMENT=production`, `DEBUG=false`, a
non-default `SECRET_KEY`, a non-default `ADMIN_PASSWORD`, an `https://`
`BASE_URL`, `ALLOWED_HOSTS` for your domain, and a valid
`TOTP_ENCRYPTION_KEY`.

### 7. Run migrations and start the server

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Open <http://localhost:8000>.

On first launch an admin user is created from `ADMIN_USERNAME` / `ADMIN_PASSWORD` (defaults: `admin` / `changeme`). You'll be redirected to `/login` — use those credentials, then walk through the first-run wizard.

> **WARNING**: Before any non-local deployment, change `ADMIN_USERNAME`,
> `ADMIN_PASSWORD`, `SECRET_KEY`, and `TOTP_ENCRYPTION_KEY`. Production startup
> also requires HTTPS, secure cookies, CSRF protection, and a valid host
> allowlist.

### Diagnostics

Run the read-only environment doctor to check common local setup issues:

```bash
python scripts/doctor.py
```

For machine-readable output:

```bash
python scripts/doctor.py --json
```

The doctor checks Python, dependencies, `.env`, database connectivity, Alembic
schema status, upload directory writability, logging config, email reminder
configuration, and production deployment templates. It does not create files,
install packages, run migrations, or modify databases.

### Running tests

The test suite needs the `homebase_test` database to exist (step 5 above).

```bash
pytest -v                              # all tests
pytest tests/test_assets.py -v         # one file
pytest tests/test_models.py::test_user_password_hashing -v   # one test
```

### Frontend assets

Runtime JavaScript and CSS are served from `app/static/`; production pages do
not load Tailwind, HTMX, Chart.js, fonts, or icons from third-party CDNs. If you
change templates, Tailwind classes, CSS tokens, HTMX, or Chart.js versions,
rebuild the committed static assets:

```bash
npm install
npm run build:frontend
```

`package-lock.json` pins frontend dependencies. The generated files under
`app/static/css/` and `app/static/vendor/` are committed so Docker production
builds do not need Node.js.

### Linting

```bash
ruff check app/ tests/
ruff format app/ tests/
```

### Dev seed data

Populate a local database with a realistic two-person household (assets,
service history, maintenance tasks in every state) for feature testing:

```bash
python -m app.cli.seed_dev --reset
```

Logs in as `demo_admin` / `seeddev` or `demo_user` / `seeddev`. Refuses to run
in production-equivalent settings.

### Maintenance digests

Email delivery is disabled by default. Preview the digest without calling Resend:

```bash
python -m app.cli.send_digests --frequency daily --dry-run
```

For Docker production, run the command from the app container or adapt your
host scheduler to call `docker compose -f compose.prod.yaml exec app ...`.
For manual Python deployments, copy the units in `deploy/systemd/` to
`/etc/systemd/system/` and enable the timers. See
[deploy/systemd/README.md](deploy/systemd/README.md) for the full runbook.

### Logging

Every HTTP response includes an `X-Request-ID` header. Use that value to find
the matching access log or exception log when troubleshooting a failed request.
Local logs default to readable plain text:

```bash
LOG_LEVEL=INFO
LOG_FORMAT=plain
LOG_SQL=false
```

For production, set `LOG_FORMAT=json` to emit newline-delimited JSON records to
stdout/stderr for Docker, systemd, or your log collector. Request logs include
method, path without query string, status, duration, request ID, and
authenticated user ID when available. Request bodies, cookies, CSRF tokens,
upload contents, and secrets are intentionally not logged.

Inspect production logs with:

```bash
docker compose -f compose.prod.yaml logs -f app
journalctl -u homebase.service -n 100 --no-pager
journalctl -u homebase.service --since "1 hour ago" | grep REQUEST_ID_HERE
```

### Schema guard

The app checks the database schema on startup and exits with a clear error if
Alembic migrations are behind. Run `alembic upgrade head` before starting or
restarting the app.

### Manual Python deploy order

This applies only to custom systemd/Python deployments. For the recommended
Docker + Caddy deployment, use:

```bash
git pull
docker compose -f compose.prod.yaml up -d --build
```

For a manual Python service:

```bash
git pull
source venv/bin/activate
alembic upgrade head
sudo systemctl restart homebase
```

## Manual Setup Troubleshooting

These notes apply to the manual Python setup above. For Docker + Caddy
deployment issues, use the
[Docker self-hosting troubleshooting section](docs/self-hosting-docker.md#troubleshooting).

- **`The term 'C:\Program Files\PostgreSQL\17\bin\psql.exe' is not recognized...`** — PostgreSQL isn't installed (or is installed at a different version path). Run `winget install PostgreSQL.PostgreSQL.17` from step 1, then **open a new PowerShell window** so `PATH` refreshes.
- **`source : The term 'source' is not recognized...`** — You're on Windows but using a POSIX command. Use `.\venv\Scripts\Activate.ps1` (PowerShell) or `venv\Scripts\activate.bat` (cmd) instead.
- **`python3 : The term 'python3' is not recognized...`** — On Windows, the Python launcher is `python` or `py`, not `python3`.
- **`createdb : The term 'createdb' is not recognized...`** — `createdb` ships with PostgreSQL but isn't on `PATH` on Windows by default. Use the full `psql.exe` path shown in step 5, or add `C:\Program Files\PostgreSQL\17\bin` to your `PATH`.
- **PowerShell blocks `Activate.ps1`** — Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` in the same session, then re-run the activate command.
- **`FATAL: password authentication failed for user "homebase"`** — The DB user/password in your `.env` doesn't match what's in Postgres. Either create the `homebase` role with the SQL in step 5, or change `DATABASE_URL` to match an existing user.
- **`psql: error: connection to server ... failed: Connection refused`** — PostgreSQL is installed but the service isn't running. On Windows, open Services (`services.msc`) and start `postgresql-x64-17`. On macOS run `brew services start postgresql@17`. On Linux run `sudo systemctl start postgresql`.

## Security Notes

- Uploaded files are stored under `UPLOAD_DIR`, but they are not mounted as public static files. Asset photos and documents are served through authenticated routes that enforce shared/personal asset visibility.
- CSRF protection is enabled automatically outside local debug mode. Forms include hidden CSRF tokens, including HTMX forms.
- TOTP secrets are encrypted with `TOTP_ENCRYPTION_KEY`, a server-side deployment key. Users set up two-factor authentication from Settings in the web UI.
  Back up this key with your private deployment secrets and keep it stable after
  users enable two-factor authentication.
- Login attempts are rate-limited in process. For multi-worker deployments, move this counter to shared storage.
- Put a request body limit in the reverse proxy as well as the app-level 10 MB upload limit. For Caddy, use a site-level `request_body` limit appropriate for the deployment.

## Contributing

HomeBase isn't actively developed anymore, but it's in decent shape and there's
plenty of useful work left. There are two good ways to help:

- **Open a pull request.** Anything from a one-line fix to a whole feature is
  welcome. I review pull requests when I can, so it may take a while.
- **Fork it and carry it forward.** If you want to take HomeBase in your own
  direction, or need changes faster than I can review them, a fork is just as
  welcome. The [MIT license](LICENSE) allows it.

### How to contribute

1. Fork the repo and create a branch from `main`.
2. Follow [Manual Development Setup](#manual-development-setup), then load demo
   data with `python -m app.cli.seed_dev --reset`.
3. Make sure `ruff check app/` passes.
4. Open a pull request that explains what changed and how you tested it.

AI-assisted contributions are fine. Please read the [AI Policy](AI_POLICY.md).
Report security issues privately as described in [SECURITY.md](SECURITY.md).

### What needs doing

As of September 2026. Pick anything that interests you.

**Bugs**

- [ ] **Assets can't be made personal.** Personal assets are hidden correctly
  everywhere, but the asset form has no visibility field and `visibility` isn't
  in `ASSET_ALLOWED_FIELDS` (`app/services/assets.py`), so every asset is saved
  as shared.
- [ ] **Retired assets keep showing overdue tasks** on the dashboard, the
  Maintenance page, and in digest emails (`dashboard_tasks` and
  `list_tasks_for_user` in `app/services/maintenance_tasks.py`).
- [ ] **Disabled users still get digest emails.** The recipient queries in
  `app/services/email_reminders.py` don't check `is_active`.
- [ ] **Usage-based tasks only work for vehicles.** Due status only reads vehicle
  mileage, so a task measured in, say, HVAC hours never comes due.
- [ ] **Some bad input causes a 500 error instead of a form error:** non-numeric
  mileage when completing a task, and a blank title when editing a document.
  Document `doc_type` isn't validated either.

**Testing and tooling**

- [ ] **No tests in the repo.** `/tests` is listed in `.gitignore`, so the
  `pytest` steps above find nothing. Removing that entry and adding a test
  suite would be the most valuable contribution.
- [ ] **No CI.** A GitHub Actions workflow that runs `ruff` and `pytest` against
  PostgreSQL would catch regressions.
- [ ] Remove the unused `app/jobs/send_maintenance_digests.py`, which
  `app/cli/send_digests.py` replaced.

**Docs that promise more than the code does**

- [ ] The Reports page labels its JSON download "Full backup", but it leaves
  out vehicle details, components, users, photos, and uploaded files, and it
  can't be imported. Either relabel it as an export, or make it complete and
  add a restore.
- [ ] `SECURITY.md` says the 10 MB upload limit is enforced at the proxy, but
  `deploy/caddy/Caddyfile` has no `request_body` limit.
- [ ] Email digests don't run on their own in the Docker deployment because
  `compose.prod.yaml` has no scheduler.

**Ideas**

- [ ] Un-retire an asset, and record a reason when retiring one.
- [ ] Metric units (liters, kilometers) and currencies other than USD.
- [ ] Search across maintenance tasks, fuel logs, and vehicle VIN/plate.
- [ ] Self-service password reset.
- [ ] Protect CSV exports against spreadsheet formula injection.
- [ ] Shared-storage login rate limiting for multi-worker deployments.

## Reporting a Vulnerability

Please do not open a public GitHub issue for security reports. Use **GitHub
Security Advisories** (Security → Report a vulnerability) so a fix can land
before the issue is public. See [SECURITY.md](SECURITY.md) for what's in and
out of scope.

## Acknowledgments

This project was developed with assistance from [Claude Code](https://claude.ai/claude-code), Anthropic's AI coding assistant. Claude Code helped with code review, security hardening, bug fixes, and documentation but the core functionality and architecture were human-designed and directed. 

See [AI_POLICY](AI_POLICY.md) for A.I. coding guidance.

## License

See [LICENSE](LICENSE) for details.
