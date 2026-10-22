FROM python:3.13-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock && \
    pip install --no-cache-dir --no-deps --prefix=/install .

FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/nothing2obvi/immich-album-relay" \
      org.opencontainers.image.title="immich-album-relay" \
      org.opencontainers.image.description="Additive multi-user Immich album membership relay" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC
COPY --from=builder /install /usr/local
RUN groupadd --gid 10001 relay && useradd --uid 10001 --gid relay --no-create-home relay && \
    mkdir -p /data /config && chown relay:relay /data /config
USER 10001:10001
WORKDIR /app
VOLUME ["/data"]
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD ["immich-album-relay", "healthcheck"]
ENTRYPOINT ["immich-album-relay"]
CMD ["serve"]
