#!/usr/bin/env bash
# Creates the local kind cluster and installs the cluster-level dependencies
# the manifests in k8s/ assume are already present: a NetworkPolicy-enforcing
# CNI, an ingress controller, and metrics-server for the HPA.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLUSTER_NAME="inventory-prod"
CALICO_VERSION="v3.28.0"

echo "==> Creating kind cluster '${CLUSTER_NAME}' (1 control-plane + 2 workers)"
if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  echo "    cluster already exists, skipping creation"
else
  kind create cluster --config "${REPO_ROOT}/infra/kind-config.yaml"
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"

echo "==> Installing Calico CNI (kindnet does not enforce NetworkPolicy)"
kubectl apply -f "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/calico.yaml"

echo "==> Waiting for nodes to go Ready (Calico needs to come up first)"
kubectl wait --for=condition=Ready nodes --all --timeout=180s

echo "==> Installing ingress-nginx (kind-specific manifest)"
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=Ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=180s

echo "==> Installing metrics-server (required for HPA CPU metrics)"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# kind's kubelet serving certs aren't signed for a real hostname, so
# metrics-server needs --kubelet-insecure-tls to scrape them. This is a kind-
# only relaxation; a real cluster should never disable kubelet TLS verification.
kubectl -n kube-system patch deployment metrics-server --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl -n kube-system wait --for=condition=Available deployment/metrics-server --timeout=180s

echo "==> Cluster ready:"
kubectl get nodes -o wide
