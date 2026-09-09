#!/usr/bin/env bash
# Prints cluster state and exercises the health/API endpoints through a
# port-forward, so it works whether or not the ingress host is wired up
# locally (/etc/hosts, etc).
set -euo pipefail

NAMESPACE="inventory-prod"

echo "==> Pods"
kubectl get pods -n "${NAMESPACE}" -o wide

echo
echo "==> Deployments"
kubectl get deployment -n "${NAMESPACE}"

echo
echo "==> Services"
kubectl get svc -n "${NAMESPACE}"

echo
echo "==> HPA"
kubectl get hpa -n "${NAMESPACE}"

echo
echo "==> PodDisruptionBudget"
kubectl get pdb -n "${NAMESPACE}"

echo
echo "==> NetworkPolicies"
kubectl get networkpolicy -n "${NAMESPACE}"

PORT=18080
echo
echo "==> Port-forwarding svc/inventory-api to localhost:${PORT}"
kubectl -n "${NAMESPACE}" port-forward svc/inventory-api "${PORT}:80" >/tmp/inventory-api-port-forward.log 2>&1 &
PF_PID=$!
trap 'kill ${PF_PID} 2>/dev/null || true' EXIT

for _ in $(seq 1 10); do
  if curl -sf "http://localhost:${PORT}/health/live" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo
echo "==> GET /health/live"
curl -sf "http://localhost:${PORT}/health/live" | tee /dev/stderr
echo
echo "==> GET /health/ready"
curl -sf "http://localhost:${PORT}/health/ready" | tee /dev/stderr
echo
echo "==> GET /api/items"
curl -sf "http://localhost:${PORT}/api/items" | tee /dev/stderr
echo

kill "${PF_PID}" 2>/dev/null || true
trap - EXIT
echo
echo "==> Verification complete"
