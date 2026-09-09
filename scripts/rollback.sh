#!/usr/bin/env bash
# Undoes the bad rollout triggered by simulate-bad-release.sh and confirms
# the Deployment converges back to 3/3 ready replicas.
set -euo pipefail

NAMESPACE="inventory-prod"
DEPLOYMENT="inventory-api"

echo "==> Rollout history before rollback"
kubectl -n "${NAMESPACE}" rollout history "deployment/${DEPLOYMENT}"

echo
echo "==> Rolling back"
kubectl -n "${NAMESPACE}" rollout undo "deployment/${DEPLOYMENT}"

echo
echo "==> Waiting for rollout to converge"
kubectl -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT}" --timeout=120s

echo
echo "==> Pods after rollback"
kubectl -n "${NAMESPACE}" get pods -l app=inventory-api -o wide

echo
echo "==> Confirming FAIL_READINESS is cleared"
kubectl -n "${NAMESPACE}" get deployment "${DEPLOYMENT}" \
  -o jsonpath='{.spec.template.spec.containers[0].env}' | tr ',' '\n'

echo
echo "==> Rollback verified."
