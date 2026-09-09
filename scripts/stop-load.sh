#!/usr/bin/env bash
# load-test.sh / start-load.sh stop on their own once the requested duration
# elapses. This just kills any that are still running early, e.g. if you
# started one with a long duration and want to cut a demo short.
set -euo pipefail

echo "==> Stopping any running load-test.sh processes"
pkill -f "scripts/load-test.sh" 2>/dev/null && echo "    stopped" || echo "    none were running"
