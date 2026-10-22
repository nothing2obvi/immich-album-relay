# Contributing

Use Python 3.12+ and `uv sync --frozen --extra dev`. Run `make test` and `make lint`.
Keep API writes restricted to adding existing asset IDs to albums. Include tests
for behavior changes using fictional IDs and mocked responses. Never require live
credentials for standard tests. Update compatibility notes for API changes.

After completed code changes, run `./scripts/deploy-test.sh` and report build,
restart and health results. Preserve private config and state. Do not publish a
repository, push Git changes, trigger remote workflows, or publish images without
the project owner's explicit approval.
