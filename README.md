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
Cron, membership polling, startup runs and optional ntfy notifications are supported.
This is an independent community project, unaffiliated with Immich.

## Required API permissions

Create a dedicated API key for each source user with **`user.read`, `album.read`,
`asset.read`, and `albumAsset.create`**. Users must own the assets they contribute
and be owners or invited **editors** of every destination album.

An optional key used only to validate destination metadata needs **`user.read`
and `album.read`**. Keep keys in `.env`; reference them from `config.yml`.

## Docker Compose

```sh
git clone https://github.com/nothing2obvi/immich-album-relay.git
cd immich-album-relay
cp .env.example .env
cp config.example.yml config.yml
chmod 600 .env
chmod 644 config.yml
```

Edit `.env` with your Immich URL and API keys. Edit `config.yml` with your user
and album UUIDs, removing unused example entries. Keep `dry_run: true` while testing.

```sh
docker compose pull
docker compose run --rm relay validate
docker compose run --rm relay run --dry-run
docker compose up -d
docker compose logs -f relay
```

After reviewing the preview, set `dry_run: false` to enable additions and run
`docker compose up -d --force-recreate`. Enabled jobs run on container startup/restart
by default; set `run_on_startup: false` to disable this.

## Docker run: individual jobs and dry-run

Use the same `.env` and `config.yml` prepared above. The image supports AMD64 and ARM64.

```sh
# Preview one job.
docker run --rm --init --read-only --env-file .env \
  -v "$PWD/config.yml:/config/config.yml:ro" \
  -v immich-album-relay_relay-state:/data \
  ghcr.io/nothing2obvi/immich-album-relay:v0.1 \
  run --job family-photos --dry-run

# Run one job; config.yml must have dry_run: false to make additions.
docker run --rm --init --read-only --env-file .env \
  -v "$PWD/config.yml:/config/config.yml:ro" \
  -v immich-album-relay_relay-state:/data \
  ghcr.io/nothing2obvi/immich-album-relay:v0.1 \
  run --job family-photos
```

Replace `family-photos` with your job ID, or omit `--job` to run all enabled jobs.
The named volume shares job locks with the default Compose setup.

## Quick start without Docker

Install Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Clone the repository and prepare `.env` and `config.yml` as above. Set `state_dir`
in `config.yml` to a writable local path, such as `./state`.

```sh
uv sync --frozen
# Export your .env variables into the shell (quote values using shell syntax).
set -a
. ./.env
set +a
uv run immich-album-relay --config ./config.yml validate
uv run immich-album-relay --config ./config.yml run --job family-photos --dry-run
# Start automatic scheduling, polling and startup runs.
uv run immich-album-relay --config ./config.yml serve
```

See the [config example](config.example.yml) and [configuration guide](docs/CONFIGURATION.md)
for all options. [MIT license](LICENSE).
