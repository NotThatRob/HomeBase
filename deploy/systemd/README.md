# HomeBase systemd units

These units are for manual Python deployments where HomeBase runs from a
virtualenv on the host. If you use the recommended Docker + Caddy production
setup, run digest jobs from the app container or adapt these units to call
`docker compose -f compose.prod.yaml exec app python -m app.cli.send_digests`.

Digest delivery runs out-of-process on systemd timers so it survives restarts,
logs to journalctl, and does not hold DB connections in the web app.

## Install

Copy the four unit files to `/etc/systemd/system/` on the server:

```bash
sudo cp deploy/systemd/homebase-digest-*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now homebase-digest-daily.timer
sudo systemctl enable --now homebase-digest-weekly.timer
```

## Assumptions

- App lives at `/opt/homebase`, virtualenv at `/opt/homebase/venv`
- Env vars (including `RESEND_API_KEY`, `EMAIL_ENABLED=true`, `EMAIL_FROM`,
  `DATABASE_URL`, `BASE_URL`) are in `/opt/homebase/.env`
- Service runs as the `homebase` system user
- User digest times are interpreted in the server's local timezone
- Weekly digests are sent on Monday at each user's configured digest time

Adjust paths in the `.service` files if your deployment layout differs.

## Verify

```bash
# Fire once manually
sudo systemctl start homebase-digest-daily.service

# Inspect the run
journalctl -u homebase-digest-daily.service -n 50 --no-pager

# Confirm the next scheduled run
systemctl list-timers homebase-digest-*
```

Each run writes one JSON line per processed user to the journal, plus a
summary line on stderr. Exit code is non-zero if any send failed.

## Dry run

To preview all daily recipients without calling Resend:

```bash
sudo -u homebase /opt/homebase/venv/bin/python -m app.cli.send_digests \
    --frequency daily --dry-run
```

To preview only users due at a specific configured time:

```bash
sudo -u homebase /opt/homebase/venv/bin/python -m app.cli.send_digests \
    --frequency daily --due-now --at-time 09:30 --dry-run
```

## Current scheduling shape

- Daily timer: checks every minute and sends users whose configured digest time
  matches the current server-local `HH:MM`
- Weekly timer: checks every minute and sends matching users only on Mondays
- `Persistent=true` makes systemd fire after boot if a timer was missed, but
  digest selection still uses the current server-local `HH:MM`

Each run writes one JSON line per processed user to the journal, plus a summary
line on stderr. A run with no users due is normal and exits successfully.
