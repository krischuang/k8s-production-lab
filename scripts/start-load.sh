#!/usr/bin/env bash
# Thin wrapper around load-test.sh with names matching what you'd type
# mid-demo. Runs in the foreground for DURATION_SECONDS; run it with `&` or
# in a second terminal if you want your prompt back immediately.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/load-test.sh" "${1:-300}" "${2:-60}"
