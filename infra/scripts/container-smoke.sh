#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec python3 infra/scripts/container_smoke.py "${1:?Usage: container-smoke.sh IMAGE}"
