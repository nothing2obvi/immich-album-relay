# Local implementation report — October 21, 2026

## Delivered

Python package and CLI (`validate`, `list-albums`, `run`, per-job and dry-run
options, `serve`, healthcheck); additive-only multi-user/multi-album relay;
source ownership filtering; editor-role checks; cursor pagination; bounded batches,
retries and rate-limit handling; independently configurable cron and membership
polling with debounce/reconciliation; per-job locks and bounded worker concurrency;
timezone-aware redacted logs with optional rotating files; optional ntfy.

`TZ` is supported in `.env`, Compose and the image. Default is UTC. Explicit
application timezone overrides TZ for logs/cron; global and per-job cron timezone
settings override schedule defaults. Invalid names fail startup.

Main repository: `/Users/joncasas/GitHub/immich-album-relay`.
Private deployment: `/Users/joncasas/GitHub/immich-album-relay_test`.

New files include `src/immich_album_relay/`, `tests/`, Dockerfile, Compose production
and test definitions, config/env examples, dependency metadata and locks,
`scripts/` for deployment/synchronization/builds/smoke checks, README, MIT LICENSE,
contribution/security docs, compatibility notes, and two GitHub Actions workflows.

Synchronization uses a publishable-file allowlist and hash verification, preserving
private config, secrets, logs, state and unknown deployment files. A managed-file
manifest safely retires only unchanged previously managed application files.
The deploy script builds for the local host, recreates the exact test container
name when private config exists, then verifies Docker health. It works without
committing and is required after completed development changes.

## Verification

- 74 automated tests pass, including a real HTTP/CLI integration test against a
  local fake Immich server; no live credentials are needed.
- Ruff lint and formatting checks pass; shell syntax and dependency lock checks pass.
- Local Linux AMD64 and ARM64 image builds and command/import/timezone checks pass.
- Isolated idle-container smoke check passes with read-only root filesystem,
  capabilities dropped, UID 10001, healthy Docker status, Phoenix timezone and
  SIGTERM shutdown exit 0. This does not validate a live Immich connection.
- Private deployment application files synchronized and hash-verified; local
  test image rebuilt successfully.

## Immich findings

The supplied Immich reference checkout reports package 3.2.0; installed local
Immich image labels report v3.3.0. The implementation targets the v3.2/v3.3
structured album search API and source-user additions to shared destinations.
See [API-COMPATIBILITY.md](API-COMPATIBILITY.md) for verified source definitions,
permissions and limitations. Runtime authentication and permissions remain
unverified until private configuration is supplied.

Inspected workflow trigger definitions do not include an album-membership event.
Automatic detection therefore uses polling of actual configured album membership,
not upload/tag webhooks or unsupported database/socket integrations.

## Outstanding and publication status

Private `config.yml` and `.env` are absent. The deploy script reports this condition
and exits 2 after building; **`immich-album-relay_test` has not been started or
health-verified with live configuration**. Authenticated API validation, a private
dry-run and any live additive integration test remain pending. No IDs or keys have
been invented for the private deployment. The separately isolated smoke check uses
clearly fictional, disabled configuration and makes no Immich requests.

Repository, documentation, MIT license and workflows are prepared locally for
review. Final live validation is still pending, so full completion is not claimed.
There is no configured remote and nothing has been pushed or published. The Docker
workflow explicitly uses `push: false`. Remote publication requires explicit owner
authorization.
