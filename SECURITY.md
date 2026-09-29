# Security Policy

## Supported Versions

HomeBase is no longer actively developed. Security reports are still welcome
and will be looked at when possible, but there is no guaranteed response time.
Any fixes land on the latest `main` branch only; there are no back-ported
patches to older commits.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security reports.** Public issues
expose a live vulnerability before a fix is available, putting existing
self-hosted deployments at risk.

Instead, report privately via **GitHub Security Advisories**:

1. Open the repository on GitHub.
2. Click **Security** → **Report a vulnerability**.
3. Fill in the details (affected version / commit, reproduction steps, impact).

GitHub will route the advisory to the maintainer privately. A public advisory
will be published once a fix is available.

## Scope

HomeBase is intended for small-scale self-hosted use (household or similar).
In scope for security reports:

- Authentication, authorization, and session handling bugs.
- Cross-user data leakage (e.g., a user seeing another user's personal asset,
  document, or service record).
- File upload escapes, path traversal, or content-type confusion.
- CSRF, XSS, SQL injection, or other injection vulnerabilities in the app.
- Insecure defaults in documented production configuration.

Out of scope:

- Issues that require physical access to the server or database.
- Missing rate limits on endpoints beyond the login flow (noted in `README.md`
  Security Notes).
- Denial-of-service via arbitrarily large uploads beyond the documented 10 MB
  limit enforced at both the proxy and app layer.
- Vulnerabilities in third-party dependencies without a demonstrated exploit
  path through HomeBase itself — please report those to the upstream project.
- Self-inflicted misconfiguration (e.g., deploying with default secrets, with
  CSRF disabled, or without HTTPS). HomeBase refuses to start in these states
  by design, but operators who disable the guards are responsible for the
  resulting exposure.

## No Bug Bounty

HomeBase is a personal project with no budget for a bounty program. Reports are
genuinely appreciated and will be credited, but no monetary reward is offered.
