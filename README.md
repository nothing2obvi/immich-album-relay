# immich-album-relay

**Disclaimer:** This project is vibecoded with ChatGPT Codex. I have tested it on
**Immich v3.3.0**, and it includes a **dry-run** mode.

This project addresses a longstanding Immich feature request:
[the ability to choose a sync destination album](https://github.com/immich-app/immich/discussions/12748).
Once this feature is implemented in Immich, this project should no longer be necessary.

**This project is in active development. There may be breaking changes.**

Relay existing photos and videos from multiple users' source albums into shared
or personal destination albums. It only adds album memberships: files are not
copied, ownership stays with the original user, and existing memberships are preserved.
This is an independent community project, unaffiliated with Immich.

- Multiple users, albums and jobs, each contributing with their own API key.
- Cron schedules, membership polling and runs on container startup/restart (enabled by default).
- Dry-run previews, optional ntfy notifications, retries and duplicate prevention.
- Docker images for **linux/amd64** and **linux/arm64**.

## Quick start

```sh
git clone https://github.com/nothing2obvi/immich-album-relay.git
cd immich-album-relay
cp .env.example .env
cp config.example.yml config.yml
chmod 600 .env
chmod 644 config.yml
```

Edit `.env` with your Immich URL, each user's API key, and `TZ` (for example,
`TZ=America/Phoenix`). Edit `config.yml` with the real user and album UUIDs;
remove unused example entries. Source users must own the assets they contribute
and be owners or invited **editors** of destination albums.

Source API keys need `user.read`, `album.read`, `asset.read`, and `albumAsset.create`.
An optional key used only to validate destination metadata needs `user.read` and `album.read`.

```sh
docker compose pull
docker compose run --rm relay validate
docker compose run --rm relay run --dry-run
docker compose up -d
docker compose logs -f relay
```

The example starts with `dry_run: true`, including automatic runs. Review the
preview, then set `dry_run: false` to enable additions. After editing `config.yml`,
restart with `docker compose restart relay`; after editing `.env`, recreate with
`docker compose up -d --force-recreate`. Keep API keys private.

**Timezone belongs in `.env`:** set `TZ`; it controls logs and the default cron
timezone. No `timezone` entry is needed in `config.yml`. Optional YAML overrides
are available for jobs using different timezones; the fallback is UTC.

Set `run_on_startup: false` to disable runs on startup/restart, globally or per job.
Cron and polling have independent `enabled` switches. Removing a source membership
does not remove anything from destination albums.

## Image and commands

Released image: `ghcr.io/nothing2obvi/immich-album-relay:v0.1`.
Compose uses this image; `docker compose build` builds from your checkout instead.

```sh
docker compose run --rm relay list-albums --user alex
docker compose run --rm relay run --job family-photos --dry-run
```

See the commented [config example](config.example.yml), [configuration and troubleshooting](docs/CONFIGURATION.md),
[API compatibility](docs/API-COMPATIBILITY.md), and [development guide](docs/DEVELOPMENT.md).
Validate upgrades in dry-run before enabling additions. [MIT license](LICENSE).
