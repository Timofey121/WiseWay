ARG PYTHON_IMAGE=python:3.11.15-alpine3.24@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4
FROM ghcr.io/astral-sh/uv:0.11.2@sha256:c4f5de312ee66d46810635ffc5df34a1973ba753e7241ce3a08ef979ddd7bea5 AS uv
FROM ${PYTHON_IMAGE} AS python
RUN apk add --no-cache libcrypto3=3.5.8-r0 libssl3=3.5.8-r0 libuuid=2.42.3-r1
FROM python AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/wiseway backend/wiseway
COPY contracts/openapi/wiseway-v1.yaml contracts/openapi/wiseway-v1.yaml
RUN uv sync --frozen --no-dev --no-editable

FROM python AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    WISEWAY_DATA_DIR=/var/lib/wiseway/state WISEWAY_SANDBOX_DIR=/srv/wiseway/sandbox
RUN python -m pip uninstall --yes pip setuptools \
    && addgroup -S -g 10001 wiseway && adduser -S -D -H -u 10001 -G wiseway wiseway \
    && mkdir -p /var/lib/wiseway/state /srv/wiseway/sandbox /backups \
    && chown 10001:10001 /var/lib/wiseway/state /srv/wiseway/sandbox /backups \
    && chmod 0700 /var/lib/wiseway/state /srv/wiseway/sandbox /backups
COPY --from=build /opt/venv /opt/venv
COPY infra/scripts/healthcheck.py infra/scripts/snapshot.py /usr/local/lib/wiseway/
WORKDIR /opt/wiseway
USER 10001:10001
STOPSIGNAL SIGTERM
ENTRYPOINT ["wiseway"]
CMD ["serve"]
