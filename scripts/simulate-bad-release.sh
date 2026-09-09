#!/usr/bin/env bash
# Rolls out a "bad" version of inventory-api whose readiness probe always
# fails (FAIL_READINESS=true), then walks through the standard kubectl
# diagnosis workflow. This is the failure scenario referenced in the README.
set -euo pipefail

NAMESPACE="inventory-prod"
DEPLOYMENT="inventory-api"

echo "==> Current rollout history"
kubectl -n "${NAMESPACE}" rollout history "deployment/${DEPLOYMENT}"

echo
echo "==> Triggering a bad release: setting FAIL_READINESS=true"
kubectl -n "${NAMESPACE}" set env "deployment/${DEPLOYMENT}" FAIL_READINESS=true

echo
echo "==> Rollout status (this will NOT converge -- Ctrl-C after ~20s, that's the point)"
timeout 20 kubectl -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT}" || true

echo
echo "==> kubectl get deployments"
kubectl -n "${NAMESPACE}" get deployment "${DEPLOYMENT}"

echo
echo "==> kubectl get pods"
kubectl -n "${NAMESPACE}" get pods -l app=inventory-api -o wide

echo
echo "==> kubectl describe pod (first new pod)"
BAD_POD=$(kubectl -n "${NAMESPACE}" get pods -l app=inventory-api \
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl -n "${NAMESPACE}" describe pod "${BAD_POD}" | tail -25

echo
echo "==> kubectl logs (new pod)"
kubectl -n "${NAMESPACE}" logs "${BAD_POD}" --tail=20 || true

echo
echo "==> kubectl get events (most recent)"
kubectl -n "${NAMESPACE}" get events --sort-by=.lastTimestamp | tail -15

echo
echo "==> Old pods are still serving traffic (Service only routes to Ready endpoints):"
kubectl -n "${NAMESPACE}" get endpoints inventory-api

echo
echo "==> Diagnosis complete. Run scripts/rollback.sh to recover."
