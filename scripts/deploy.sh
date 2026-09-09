#!/usr/bin/env bash
# Builds the API image, loads it into every kind node, and applies the
# manifests in dependency order (namespace/config before anything that
# references them, RBAC before the pods that use the ServiceAccount).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLUSTER_NAME="inventory-prod"
NAMESPACE="inventory-prod"
IMAGE="inventory-api:local"

echo "==> Building ${IMAGE}"
docker build -f "${REPO_ROOT}/app/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}"

echo "==> Loading image into kind cluster '${CLUSTER_NAME}'"
kind load docker-image "${IMAGE}" --name "${CLUSTER_NAME}"

echo "==> Applying namespace and config"
kubectl apply -f "${REPO_ROOT}/k8s/namespace.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/configmap.yaml"

if [[ -f "${REPO_ROOT}/k8s/secret.yaml" ]]; then
  echo "==> Applying k8s/secret.yaml (local, gitignored)"
  kubectl apply -f "${REPO_ROOT}/k8s/secret.yaml"
else
  echo "==> No k8s/secret.yaml found, applying secret.example.yaml placeholder credentials"
  echo "    (fine for this local demo; never do this with real credentials)"
  kubectl apply -f "${REPO_ROOT}/k8s/secret.example.yaml"
fi

echo "==> Applying ServiceAccount and RBAC"
kubectl apply -f "${REPO_ROOT}/k8s/serviceaccount.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/rbac.yaml"

echo "==> Applying Postgres"
kubectl apply -f "${REPO_ROOT}/k8s/postgres.yaml"
kubectl -n "${NAMESPACE}" rollout status deployment/postgres --timeout=120s

echo "==> Applying NetworkPolicies"
kubectl apply -f "${REPO_ROOT}/k8s/networkpolicy.yaml"

echo "==> Applying API Deployment, Service, Ingress, HPA, PDB"
kubectl apply -f "${REPO_ROOT}/k8s/deployment.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/service.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/ingress.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/hpa.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/pdb.yaml"

echo "==> Waiting for rollout"
kubectl -n "${NAMESPACE}" rollout status deployment/inventory-api --timeout=120s

echo "==> Deployed. Run scripts/verify.sh to check health."
