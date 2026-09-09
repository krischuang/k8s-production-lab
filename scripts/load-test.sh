#!/usr/bin/env bash
# Generates sustained load against /api/items to push CPU usage past the
# HPA's 60% target. Uses plain curl in parallel loops so the only dependency
# is curl itself. Run scripts/watch-hpa.sh (or the kubectl commands it
# prints) in another terminal while this runs.
set -euo pipefail

NAMESPACE="inventory-prod"
DURATION_SECONDS="${1:-180}"
CONCURRENCY="${2:-20}"
PORT=18081

echo "==> Port-forwarding svc/inventory-api to localhost:${PORT}"
kubectl -n "${NAMESPACE}" port-forward svc/inventory-api "${PORT}:80" >/tmp/inventory-api-load-test-pf.log 2>&1 &
PF_PID=$!
cleanup() {
  echo "==> Stopping load generators and port-forward"
  kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT

sleep 2

echo "==> Generating load for ${DURATION_SECONDS}s with ${CONCURRENCY} concurrent workers"
echo "    Watch it with:  kubectl get hpa -n ${NAMESPACE} -w"
echo "    Or:             kubectl top pods -n ${NAMESPACE}"

END=$((SECONDS + DURATION_SECONDS))
for _ in $(seq 1 "${CONCURRENCY}"); do
  (
    while [[ ${SECONDS} -lt ${END} ]]; do
      curl -sf "http://localhost:${PORT}/api/items" -o /dev/null || true
    done
  ) &
done

wait $(jobs -p) 2>/dev/null || true
echo "==> Load generation finished. HPA scale-down is gradual -- see README 'Autoscaling' for why."
