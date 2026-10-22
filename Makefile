.PHONY: test lint build multiarch deploy-test

test:
	uv run --extra dev pytest -q

lint:
	uv run --extra dev ruff check .

build:
	docker buildx build --load -t immich-album-relay:local .

multiarch:
	./scripts/build-multiarch.sh

deploy-test:
	./scripts/deploy-test.sh
