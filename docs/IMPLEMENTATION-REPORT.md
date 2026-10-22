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

- 82 automated tests pass, including a real HTTP/CLI integration test against a
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
permissions and limitations. Read-only validation now passes against the private Immich 3.3.0 server for
both configured users and all enabled-job source/destination album reads and roles.

Inspected workflow trigger definitions do not include an album-membership event.
Automatic detection therefore uses polling of actual configured album membership,
not upload/tag webhooks or unsupported database/socket integrations.

## Outstanding and publication status

Private configuration is now supplied. Read-only validation passes against Immich
3.3.0 for both configured user keys. A live dry-run finds two missing memberships,
one from each source user, with zero failures. `dry_run: true` remains enabled;
no live memberships were changed. Actual write scopes/per-asset sharing permission
remain untested until live writes are deliberately enabled.

The application is synchronized and the native private Docker image rebuilt.
`immich-album-relay_test` was recreated and is running healthy on the current image.
Default-enabled `run_on_startup` was verified through successful dry-run startup
executions both on initial launch and after an actual container restart (two
startup completions). Global and per-job opt-outs are documented and tested, as
are startup notifications, dry-run preservation and coalescing initial triggers.

Private configuration repairs were limited to wrapping a destination reference in
a list, removing unused broken example definitions, and correcting a URL port
separator. A private backup is retained beside the private configuration. `.env`
permissions are owner-only. No private configuration or credentials were copied
into this repository.

## Release preparation

The v0.1 release includes a concise README, TZ-based default configuration,
MIT license, and a tag-triggered GHCR publication workflow. The workflow runs the
Python test matrix before publishing Linux AMD64 and ARM64 images. Live read-only
validation is verified; actual additive-write integration remains deferred while
the private configuration is in dry-run mode.
