# Configuration and operation

## Configuration and TZ

The fully commented [config.example.yml](../config.example.yml) contains two jobs,
two contributors and two destinations. [.env.example](../.env.example) uses only
fictional values. Reduce the examples to the users and jobs you actually need.

```dotenv
TZ=America/Phoenix
IMMICH_URL=https://photos.example.com
IMMICH_ALEX_API_KEY=your-private-key
IMMICH_SAM_API_KEY=your-other-private-key
```

| Timezone setting | Applies to | Priority |
| --- | --- | --- |
| `jobs[].cron.timezone` | That job's cron | Highest for its schedule |
| `cron.timezone` | Cron defaults | Overrides application timezone |
| `timezone` | Logs and cron fallback | Overrides `TZ` |
| `TZ` environment variable | Logs and cron fallback | Used when `timezone` is omitted |
| `UTC` | Logs and cron fallback | Default when neither is provided |

Use IANA names such as `America/Phoenix`, `Europe/London`, or `UTC`. Timezone data
is included in both image architectures. Phoenix is an example, never hardcoded
as the universal default. Poll intervals use a monotonic clock and are unaffected
by timezone changes. Python timestamps include an explicit UTC offset.

Users are reusable mapping entries with immutable `id`, optional friendly `name`,
and `api_key`. Sources reference their user and one or more album `{id, name}`
entries. Destinations are reusable `{id, name, user?}` definitions, referenced by
name from each job's `destinations` list. Labels help humans; UUIDs select albums.
A destination's optional `user` credential validates existence/readability;
**all writes still use the contributing source user's key**.

Jobs have unique safe IDs, optional names, enabled flags, sources and destinations.
Users/albums/destinations can be reused across jobs. Each user's source albums
should be combined in one source entry per job. Repeated assets across source
albums are written once per destination and attributed to the first source row.
Assets belonging to other users in a source album are explicitly skipped; list
that other user as a source with their own key to contribute those assets.

## API keys and sharing permissions

In each Immich user's account settings, open **API Keys**, create a dedicated key
and grant only the scopes needed below. Never use an administrator's credential
as a replacement for other contributors' keys.

| Credential role | Minimum API key scopes |
| --- | --- |
| Source contributor | `user.read`, `album.read`, `asset.read`, `albumAsset.create` |
| Destination metadata validation only | `user.read`, `album.read` |

The source user must be able to read every configured source album. For each
destination, they must be the owner or an explicitly invited **editor**, not a
viewer or anonymous public-link visitor. Immich additionally checks whether the
asset can be shared. Source ownership is checked locally; the server makes the
final decision. These permissions are based on the source implementation described
in [API-COMPATIBILITY.md](docs/API-COMPATIBILITY.md).

Discover accessible album UUIDs and sharing roles after configuring your user ID:

```sh
docker compose run --rm relay list-albums --user alex
```

The key's identity must match the configured UUID. `validate` checks identity,
server version, accessibility, editor roles, and membership reads without writes.
It cannot prove the write scope or every asset's sharing eligibility without an
actual run. An HTTP 403 or per-asset `no_permission` result gives a clear failure.

## Scheduling and automatic detection

Cron uses standard five-field expressions: minute, hour, day of month, month,
day of week. Both day fields follow conventional OR semantics when constrained.
Examples: `0 3 * * *` daily at 03:00, `*/15 * * * *` every 15 minutes.
Set `cron.enabled: false` to disable cron globally. Per-job cron settings override
the expression/timezone and may disable a job's cron, but cannot bypass the master
switch. A job with `enabled: false` is excluded from every execution method.

Automatic detection uses **polling**, independently controlled by
`polling.enabled`. The inspected Immich workflow SDK does not expose a reliable
album-membership trigger; upload/tag events are insufficient. No webhook listener
is exposed. Polls read only configured source albums, fingerprint their actual
asset IDs, and run only relevant jobs after membership settles for
`debounce_seconds`. With an interval of 60 and debounce of 10, a stable new change
usually runs on the following poll (about 60–120 seconds after the change).

`run_on_startup: true` (the default) executes every enabled job once as soon as
`serve` starts, including the initial container launch and each restart. Set it to
`false` globally to disable these runs, or set `run_on_startup: false` on a job to
opt that job out. Startup runs work independently of cron and polling, honor
`dry_run`, share the normal per-job lock, and log the `startup` trigger. Commands
such as `validate` and `list-albums` do not trigger a startup run. A cron tick in
the startup minute is covered by the startup run. Successful startup runs establish
the polling baseline from a fingerprint taken before execution, avoiding a redundant
initial polling run while detecting changes made during startup.

When startup runs are disabled, the first poll after restart reconciles sources
after debounce. Successful
runs checkpoint only in memory; failed/partial runs retry even if sources do not
change. `reconcile_seconds` forces periodic reconciliation to repair destination
changes without requiring a source edit. There is no persistent membership cache
that could hide a missed change. Polling uses one fingerprint per job, so jobs with
the same sources make independent reads. Large deployments should raise intervals.

Cron and polling can coexist. Runs of a job do not overlap; locks also cover
manual runs that mount the same state volume. A cron tick during an active job is
coalesced into one pending cron run, with scheduled and actual timestamps logged.
Different jobs may run concurrently. A restarted scheduler does not replay missed
cron occurrences; polling performs reconciliation. A skipped DST wall-clock time
is skipped; a repeated DST time runs at both UTC occurrences. A backward wall clock
adjustment does not replay minutes already seen by a running scheduler.

With cron, polling and startup runs disabled, `serve` stays healthy and idle;
use manual runs. All methods remain additive: removing an asset from its source does not
remove its destination membership. Deleting the underlying Immich asset can still
affect its availability in every album. Cross-album chains converge through
idempotent additions; no webhook feedback loop exists.

## Command-line reference

Global `--config` comes **before** the subcommand. Default:
`/config/config.yml`, or set `RELAY_CONFIG`.

```sh
immich-album-relay --config ./config.yml validate --offline
immich-album-relay --config ./config.yml validate
immich-album-relay --config ./config.yml list-albums --user alex
immich-album-relay --config ./config.yml run
immich-album-relay --config ./config.yml run --job family-photos
immich-album-relay --config ./config.yml run --dry-run
immich-album-relay --config ./config.yml serve
```

Compose equivalents replace the executable with `docker compose run --rm relay`.
For a single job: `docker compose run --rm relay run --job family-photos`.
Disabled jobs cannot be forced through `--job`; enable the job in configuration.
Commands exit nonzero on configuration/API errors or partial failures. One failed
job does not prevent the other selected jobs from running.

## Logging and ntfy

Logs go to stdout with DEBUG, INFO, WARNING or ERROR levels. Every execution logs
job ID/name, trigger, scheduled/actual start timestamps, duration and overall status.
Rows identify source user, source album UUID/name, destination UUID/name, found,
already present, added, skipped (not owned), failed, and preview `would add` counts.
These are membership counts; adding one asset to two destinations counts as two
additions. Dry-run rows account for planned additions across overlapping sources.
Optional `logging.file` enables size-limited rotating files alongside stdout.

ntfy is disabled by default. Configure `ntfy.enabled`, `server_url`, `topic`,
`priority` (1–5), and optionally an environment-referenced Bearer `token` or
`username`/`password`. Job overrides control enabled, triggers, success/failure,
and unchanged-run notifications. The global enabled flag is a master switch.
Supported triggers are `manual`, `cron`, `polling`, and `startup`. Add `startup`
to an existing explicit `ntfy.triggers` list if startup notifications are desired;
the default trigger list includes it. Notifications include job,
status, trigger, users, source/destination rows, totals and bounded error summaries.
No-change success notifications are suppressed unless `on_no_changes: true`.
Failures can notify with zero additions; ntfy delivery failure never fails a
successful relay run. Dry-run notifications, when enabled for no changes, say
`dry-run` and report preview counts without claiming real additions.

## Reliability, storage and security

HTTP timeout, retries, exponential backoff, maximum retry delay, batch size and
page size are configurable under `http`. HTTP 408/425/429 and selected 5xx/network
failures retry a bounded number of times. `Retry-After` seconds or HTTP dates are
respected; delays above the configured limit defer work to a later run rather
than retrying early. Duplicate membership results are benign. Partial/missing
results count as failures and are retried by subsequent reconciliation. An
ambiguous timeout may have applied a batch; a retry is safe, but its already-present
count can include additions from the earlier response that was lost.

Only `PUT /albums/{id}/assets` changes Immich. No database access, file transfers,
asset uploads/deletions, ownership changes or album deletions are implemented.
Keys, tokens, authorization headers and remote error bodies are never logged.
Known credentials are redacted from logs and notifications; labels are sanitized
for single-line logs. Redirects are refused so credentials are never forwarded to
a redirect target. Use HTTPS for remote servers. Logs and notifications contain
album labels and UUIDs, so keep their destinations appropriately private.

The image runs as UID/GID 10001, drops capabilities, uses a read-only filesystem
and mounts config read-only. `/data` holds process locks, a health heartbeat and
optional logs. It contains no required membership database. All instances that
must coordinate need the same local state volume; distributed/network-filesystem
locking is outside this release's scope. Prefer the default named volume. For
bind mounts, grant UID 10001 write access. If changing `state_dir`, also set
`RELAY_STATE_DIR` for the container health check and mount that path. Health means
the scheduler loop is alive, not that Immich is reachable or every job succeeds.

SIGTERM/SIGINT stops scheduling, interrupts retry waits and waits for workers.
In-flight HTTP requests may take up to the request timeout to return; no new
batches start after shutdown. Compose allows two minutes for graceful stopping.
Adjust that grace period if using longer HTTP timeouts. API operations are safe
to repeat after a forced container termination.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing environment variable / invalid config | Export variables or populate private `.env`; check UUIDs, mapping references and example schema |
| Invalid timezone | Use an installed IANA name; `TZ=America/Phoenix` is supported |
| HTTP 401 | Key validity and matching configured user UUID |
| HTTP 403 or `no_permission` | Key scopes, destination editor role, and the asset owner's source key |
| HTTP 400/404 | Album UUID, accessibility, URL prefix and API version; inaccessible albums can appear missing |
| Network timeout / TLS failure | Hostname reachable from inside Docker, server health and certificate trust |
| No additions | Check dry-run, enabled flags, source ownership, existing membership, debounce and polling interval |
| Unsupported cursor response | Requires Immich >=3.2; inspect compatibility notes before upgrading |
| Overlap skipped | Another manual/scheduled run holds the same job's local state lock |
| Unhealthy container | Writable state directory, matching `RELAY_STATE_DIR`, startup configuration and container logs |
| ntfy delivery failure | URL/topic/authentication; delivery failure does not roll back additions |

Source pagination is not an atomic snapshot: concurrent album edits can be seen
on a subsequent poll. Very large albums require memory proportional to asset
metadata and repeated API reads. Tune polling/page sizes accordingly. There is
no upload-event substitute or undocumented database integration, and no automatic
removal when source membership shrinks. Verify a new Immich release in dry-run
before enabling live additions.

