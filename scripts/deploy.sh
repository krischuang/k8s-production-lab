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
OBSERVER_IMAGE="demo-observer:local"

echo "==> Building ${IMAGE}"
docker build -f "${REPO_ROOT}/app/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}"

echo "==> Building ${OBSERVER_IMAGE}"
docker build -f "${REPO_ROOT}/observer/Dockerfile" -t "${OBSERVER_IMAGE}" "${REPO_ROOT}"

echo "==> Loading images into kind cluster '${CLUSTER_NAME}'"
kind load docker-image "${IMAGE}" --name "${CLUSTER_NAME}"
kind load docker-image "${OBSERVER_IMAGE}" --name "${CLUSTER_NAME}"

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

echo "==> Applying demo-observer (read-only dashboard backend, see README 'Kubernetes observer architecture')"
kubectl apply -f "${REPO_ROOT}/k8s/observer-rbac.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/observer-networkpolicy.yaml"

echo "==> Resolving the real kube-apiserver endpoint for the observer's egress NetworkPolicy"
# See k8s/observer-networkpolicy.yaml for why this is generated rather than a
# static ipBlock: Calico enforces this pod's egress against the apiserver's
# real (post-DNAT) node IP:port, not the 10.96.0.1 ClusterIP it dials.
APISERVER_ENDPOINT=$(kubectl get endpoints kubernetes -n default -o jsonpath='{.subsets[0].addresses[0].ip}:{.subsets[0].ports[0].port}')
APISERVER_IP="${APISERVER_ENDPOINT%%:*}"
APISERVER_PORT="${APISERVER_ENDPOINT##*:}"
echo "    apiserver endpoint: ${APISERVER_IP}:${APISERVER_PORT}"
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-observer-egress-to-apiserver
  namespace: ${NAMESPACE}
  annotations:
    generated-by: scripts/deploy.sh
spec:
  podSelector:
    matchLabels:
      app: demo-observer
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: ${APISERVER_IP}/32
      ports:
        - protocol: TCP
          port: ${APISERVER_PORT}
EOF

kubectl apply -f "${REPO_ROOT}/k8s/observer-deployment.yaml"
kubectl apply -f "${REPO_ROOT}/k8s/observer-service.yaml"
kubectl -n "${NAMESPACE}" rollout status deployment/demo-observer --timeout=120s

echo "==> Deployed. Run scripts/verify.sh to check health, or scripts/dashboard.sh to open the live demo."
