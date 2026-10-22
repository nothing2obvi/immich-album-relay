# Development

## Local development and private test deployment

Use a source checkout named `immich-album-relay` and a separate sibling
`immich-album-relay_test` directory for private deployment.

```sh
uv sync --frozen --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check .
./scripts/deploy-test.sh
```

Tests use fake credentials and mocked Immich responses; no live credentials are
needed. Dependencies are locked in `uv.lock`; Docker uses the corresponding
pinned runtime `requirements.lock`. After changing dependencies, run `uv lock`
and `uv export --no-dev --no-emit-project --no-hashes --no-header -o requirements.lock`.

The deploy script uses an application allowlist, validates copied file hashes,
builds the local image, validates the private config offline, recreates/starts
**`immich-album-relay_test`**, and checks Docker health. It never copies private
settings back into development, deletes private files, or overwrites `config.yml`,
`.env`, state, logs or custom deployment files. Source symlinks and destination
symlink paths are refused. No Git commit is needed. Application files are
replaced. A private `.relay-managed.json` manifest tracks file hashes; only unchanged,
previously managed application files are removed when retired from the source.
Unknown private files are preserved. Privately edited retired application files
block synchronization so they can be preserved deliberately.

Initially copy the examples to private `config.yml` and `.env`, then edit them:

```sh
cp config.example.yml ../immich-album-relay_test/config.yml
cp .env.example ../immich-album-relay_test/.env
chmod 700 ../immich-album-relay_test
chmod 600 ../immich-album-relay_test/.env
chmod 644 ../immich-album-relay_test/config.yml
./scripts/deploy-test.sh
```

When private configuration is absent, deployment still builds the image, then
exits with code 2 and reports live startup blocked. It never invents credentials.
The default test directory is the main repository's sibling; set `RELAY_TEST_DIR`
to another separate directory if needed. The test state volume is
`immich-album-relay_test-state`. Rebuild/redeploy after each completed set of code
changes using the script; passing unit tests alone is not deployment verification.
The documented script is the automatic development handoff; it is intentionally
not a file watcher or a mandatory post-commit hook.

## Multiarchitecture builds and updating

```sh
# Local verification of both architectures; builds/loads each separately, never pushes.
./scripts/build-multiarch.sh
# Export a combined OCI archive without a registry or local multiarch-load assumption.
docker buildx build --platform linux/amd64,linux/arm64 \
  --output type=oci,dest=/tmp/immich-album-relay.oci.tar .
```

Buildx needs native support or QEMU emulation for each platform. Both runtime
images use the same pure-Python app with official Python base images and
architecture-specific dependency wheels. The private deployment builds for the
local Docker host. To update an installed source checkout, review changes, then
`docker compose build && docker compose up -d --force-recreate`. Private test
updates must use the deploy script. Preserve your private config and state.

GitHub Actions runs tests on Python 3.12, 3.13 and 3.14. Pushing a `v*` tag
runs those checks before publishing Linux AMD64/ARM64 images to GHCR with the
exact Git tag as the image tag. Publishing uses the repository's `GITHUB_TOKEN`;
no personal registry credentials are required. Release tags must point to tested
commits, and new GHCR packages must be made public in their package settings.
