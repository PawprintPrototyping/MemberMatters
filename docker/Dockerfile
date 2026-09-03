# syntax=docker/dockerfile:1.7
# Multi-stage Dockerfile for MemberMatters.
#
# Layout:
#   system-base        Debian + python + runtime libraries (nginx, mysql/pg
#                      client libs). Shared by python-deps and runtime so
#                      the venv links against the exact same libc/openssl
#                      it will resolve at runtime.
#   python-deps        Adds build toolchain + uv, resolves the runtime deps
#                      from uv.lock into a self-contained /opt/venv.
#   frontend-builder   node + `npm ci` + `quasar build` -> dist/spa/.
#   runtime            system-base + /opt/venv + dist/ + django source.
#                      This is the only stage published.
#
#
# Enable BuildKit before building (docker >= 23 or DOCKER_BUILDKIT=1).

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=24.20.0
ARG UV_VERSION=0.11.8

##############################################################################
# uv-bin: alias for the official uv image so we can pin the version via
# ARG. BuildKit expands ARGs in `FROM` but not directly in `COPY --from=`,
# so we route the version pin through a named stage.
##############################################################################
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin

##############################################################################
# system-base: runtime OS + shared libs. Kept minimal because everything
# installed here is copied into the final image.
##############################################################################
FROM python:${PYTHON_VERSION}-bullseye AS system-base

# Keep apt's package cache around so BuildKit cache mounts can persist it
# across builds (the default docker-clean hook wipes it on every apt run).
RUN rm -f /etc/apt/apt.conf.d/docker-clean

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update -y \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       libmariadb3 \
       libpq5 \
       nginx

##############################################################################
# python-deps: resolve and install runtime python dependencies from uv.lock 
##############################################################################
FROM system-base AS python-deps

# Build toolchain + headers for compiled deps (mysqlclient, psycopg2 if
# ever unpinned from the -binary wheel, pillow). Removed in the final
# image because we don't COPY --from=python-deps outside /opt/venv.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update -y \
    && apt-get install -y --no-install-recommends \
       build-essential \
       default-libmysqlclient-dev \
       git \
       libpq-dev \
       pkg-config

# uv itself lives in an official minimal image; copying the binary in is
# both faster and gives us a deterministic uv version pinned by tag.
COPY --from=uv-bin /uv /uvx /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    # cache mount lives on a separate filesystem, so hard-linking would
    # fail; copy instead.
    UV_LINK_MODE=copy \
    # Precompile .pyc so first request in production doesn't pay the
    # bytecode-compile cost.
    UV_COMPILE_BYTECODE=1 \
    # Never let uv silently pull a python interpreter behind our back;
    # the base image already supplies one.
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build/memberportal

COPY memberportal/pyproject.toml memberportal/uv.lock ./

# BuildKit cache for uv's wheel/index cache. Combined with GHA cache
# export (cache-to: type=gha,mode=max) in the workflows this survives
# across workflow runs.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

##############################################################################
# frontend-builder: install npm deps and produce the quasar SPA bundle.
##############################################################################
FROM node:${NODE_VERSION}-bookworm AS frontend-builder

WORKDIR /build/frontend

# npm ci layer is cached until package-lock.json changes.
COPY src-frontend/package.json src-frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY src-frontend/ ./
COPY package.json /build/package.json
RUN npm run build
# Source maps are uploaded from CI, we don't need to ship them in the image
RUN find dist -name '*.map' -type f -delete

##############################################################################
# runtime: the only stage that actually ships. Pulls the built venv and
# built frontend from the previous stages and adds the django source.
##############################################################################
FROM system-base AS runtime

LABEL maintainer="Jaimyn Mayer (github@jaimyn.dev)"
LABEL description="Runtime image for the MemberMatters software."

VOLUME /usr/src/data/
VOLUME /usr/src/logs/

RUN mkdir -p /usr/src/app/frontend /usr/src/logs /usr/src/data

# Runtime venv - contains django, daphne, celery, and everything else
# from uv.lock. Putting it on PATH means container_start.sh's plain
# `daphne` and `celery` calls resolve to the venv's binaries.
COPY --from=python-deps /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Built frontend (dist/spa/ is what nginx.conf points root at).
COPY --from=frontend-builder /build/frontend/dist /usr/src/app/frontend/dist
COPY package.json /usr/src/app/package.json

# Django source and docker helpers.
COPY memberportal /usr/src/app/memberportal
COPY docker /usr/src/app/docker
COPY docker/nginx.conf /etc/nginx/nginx.conf

WORKDIR /usr/src/app/memberportal
RUN python3 manage.py collectstatic --noinput

# Short commit SHA baked in at build time; consumed by the Sentry init
# in memberportal/membermatters/urls.py as the release tag. Kept last
# so it doesn't invalidate earlier layers when the SHA changes.
ARG SENTRY_RELEASE=""
ENV SENTRY_RELEASE=${SENTRY_RELEASE}

EXPOSE 8000
CMD ["sh", "/usr/src/app/docker/container_start.sh"]
