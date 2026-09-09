#!/usr/bin/env bash
# Deletes the local kind cluster and everything in it.
set -euo pipefail

CLUSTER_NAME="inventory-prod"

echo "==> Deleting kind cluster '${CLUSTER_NAME}'"
kind delete cluster --name "${CLUSTER_NAME}"
