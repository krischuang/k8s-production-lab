#!/usr/bin/env bash
# Generates sustained load against the Ingress (the same path real traffic
# takes) to push CPU usage past the HPA's 60% target. Hitting the Ingress
# instead of port-forwarding straight to a pod matters here: nginx
# load-balances across all inventory-api pods, so CPU load actually spreads
# the way it would under real traffic. A port-forward to the Service, by
# contrast, pins the whole session to a single pod and never triggers a
# realistic scale-out.
set -euo pipefail

DURATION_SECONDS="${1:-180}"
CONCURRENCY="${2:-40}"
INGRESS_URL="http://localhost:8080/api/items"
HOST_HEADER="inventory.local"

if ! curl -sf -H "Host: ${HOST_HEADER}" "${INGRESS_URL}" >/dev/null 2>&1; then
  echo "ERROR: cannot reach ${INGRESS_URL} (Host: ${HOST_HEADER})." >&2
  echo "Is the kind cluster up with the ingress-nginx hostPort mapping (infra/kind-config.yaml)?" >&2
  exit 1
fi

echo "==> Generating load for ${DURATION_SECONDS}s with ${CONCURRENCY} concurrent workers"
echo "    Watch it with:  kubectl get hpa -n inventory-prod -w"
echo "    Or:             kubectl top pods -n inventory-prod"

cleanup() {
  echo "==> Stopping load generators"
  kill $(jobs -p) 2>/dev/null || true
}
trap cleanup EXIT

END=$((SECONDS + DURATION_SECONDS))
for _ in $(seq 1 "${CONCURRENCY}"); do
  (
    while [[ ${SECONDS} -lt ${END} ]]; do
      curl -sf -H "Host: ${HOST_HEADER}" "${INGRESS_URL}" -o /dev/null || true
    done
  ) &
done

wait $(jobs -p) 2>/dev/null || true
echo "==> Load generation finished. HPA scale-down is gradual -- see README 'Autoscaling' for why."
