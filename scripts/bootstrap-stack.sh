#!/usr/bin/env bash
set -euo pipefail
set +x
exec python3 "$(dirname "$0")/bootstrap-stack.py" "$@"
