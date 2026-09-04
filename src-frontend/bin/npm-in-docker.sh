#!/usr/bin/env bash
# Run npm in a container matching CI's Node version, without touching the
# host's node_modules. Everything under /w/node_modules inside the container
# is a named Docker volume, as a crutch for native module polution.
#
#
# Usage from src-frontend/:
#     bin/npm-in-docker.sh install
#     bin/npm-in-docker.sh ci
#     bin/npm-in-docker.sh audit
#     bin/npm-in-docker.sh update
#     bin/npm-in-docker.sh -- ci --no-audit --no-fund   # pass raw args after --

set -euo pipefail

# Pin to whatever the Dockerfile's frontend-builder stage uses.
NODE_IMAGE="node:24.20.0-bookworm"

# Named volume scoped to this project.
VOLUME_NAME="mm-frontend-node-modules"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

exec docker run --rm -it \
    -v "${FRONTEND_DIR}:/w" \
    -v "${VOLUME_NAME}:/w/node_modules" \
    -w /w \
    "${NODE_IMAGE}" \
    npm "$@"
