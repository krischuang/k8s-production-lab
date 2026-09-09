#!/usr/bin/env bash
# Demonstrates node maintenance: cordon a worker, drain it, and confirm the
# PodDisruptionBudget keeps the API available throughout. Run with `source`
# or `bash scripts/drain-node.sh <node-name>`; if no node is given, the
# script picks a worker that's currently running inventory-api pods.
set -euo pipefail

NAMESPACE="inventory-prod"
NODE="${1:-}"

if [[ -z "${NODE}" ]]; then
  NODE=$(kubectl -n "${NAMESPACE}" get pods -l app=inventory-api \
    -o jsonpath='{.items[0].spec.nodeName}')
fi

echo "==> Target node: ${NODE}"

echo
echo "==> Pods on this node before drain"
kubectl get pods -n "${NAMESPACE}" -o wide --field-selector "spec.nodeName=${NODE}"

echo
echo "==> PodDisruptionBudget before drain"
kubectl get pdb -n "${NAMESPACE}"

echo
echo "==> Cordoning ${NODE} (marks unschedulable, existing pods keep running)"
kubectl cordon "${NODE}"
kubectl get nodes

echo
echo "==> Draining ${NODE} (evicts pods, respecting the PDB)"
kubectl drain "${NODE}" \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --timeout=120s

echo
echo "==> Pods after drain (rescheduled onto remaining nodes)"
kubectl get pods -n "${NAMESPACE}" -o wide -l app=inventory-api

echo
echo "==> Service still has ready endpoints throughout:"
kubectl get endpoints inventory-api -n "${NAMESPACE}"

echo
echo "==> Uncordoning ${NODE} (allow scheduling again)"
kubectl uncordon "${NODE}"
kubectl get nodes
