#!/usr/bin/env bash
# Interview prep: checks the environment is actually ready for a live demo
# and prints the runbook, rather than assuming the cluster from a previous
# session is still in a good state. Does not deploy, tear down, or otherwise
# mutate anything -- it only checks and reports.
set -uo pipefail

NAMESPACE="inventory-prod"
CLUSTER_NAME="inventory-prod"
FAILED=0

pass() { echo "  [ok]   $1"; }
fail() { echo "  [FAIL] $1"; FAILED=1; }

echo "==> Checking prerequisites"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  pass "Docker is running"
else
  fail "Docker is not running -- start Docker Desktop (or dockerd) first"
fi

if command -v kind >/dev/null 2>&1; then
  pass "kind is installed ($(kind --version))"
else
  fail "kind is not installed"
fi

if command -v kubectl >/dev/null 2>&1; then
  pass "kubectl is installed ($(kubectl version --client --short 2>/dev/null || kubectl version --client))"
else
  fail "kubectl is not installed"
fi

echo
echo "==> Checking cluster state"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  pass "kind cluster '${CLUSTER_NAME}' exists"
else
  fail "kind cluster '${CLUSTER_NAME}' not found -- run ./scripts/setup-cluster.sh"
fi

if kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  pass "namespace '${NAMESPACE}' exists"
else
  fail "namespace '${NAMESPACE}' not found -- run ./scripts/deploy.sh"
fi

for deploy in inventory-api postgres demo-observer; do
  ready=$(kubectl -n "${NAMESPACE}" get deployment "${deploy}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "")
  desired=$(kubectl -n "${NAMESPACE}" get deployment "${deploy}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "")
  if [[ -n "${ready}" && "${ready}" == "${desired}" ]]; then
    pass "deployment/${deploy} is ${ready}/${desired} ready"
  else
    fail "deployment/${deploy} is not fully ready (${ready:-0}/${desired:-?}) -- run ./scripts/deploy.sh"
  fi
done

hpa_replicas=$(kubectl -n "${NAMESPACE}" get hpa inventory-api -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "")
if [[ "${hpa_replicas}" == "3" ]]; then
  pass "HPA is at baseline (3 replicas) -- good starting point for the load-test demo"
else
  echo "  [info] HPA currently at ${hpa_replicas:-unknown} replicas (baseline is 3)."
  echo "         If a previous load test is still scaling down, wait a few minutes,"
  echo "         or this is still a fine starting point -- just don't claim it's baseline."
fi

echo
if [[ "${FAILED}" -eq 1 ]]; then
  echo "==> Not ready. Fix the [FAIL] items above before starting the demo."
  exit 1
fi

echo "==> Environment is ready. Suggested flow (also in DEMO.md):"
cat <<'EOF'

  Terminal 1:                          Browser:
  ------------------------------       ---------------------------------
  ./scripts/dashboard.sh          -->  http://localhost:8090/

  Terminal 2 (run these in order, watching the browser after each):
  ------------------------------------------------------------------
  # 1. baseline -- point out HEALTHY, 3/3, HPA at 3
  # 2. click "Send Request" a few times -- pod name should rotate
  ./scripts/load-test.sh 240 60        # 3. watch replicas scale out, then back down
  ./scripts/simulate-bad-release.sh    # 4. watch Deployment Status flip to "Rollout in progress"
  ./scripts/rollback.sh                # 5. watch it recover to Stable / 3/3

See DEMO.md for a timed 5-minute version of this walkthrough.
EOF
