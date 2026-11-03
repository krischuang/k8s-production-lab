# Live security verification run — 2026-11-03

This records an actual execution of the 17 live security tests that
`tests/security/conftest.py` marks `skipif` when no matching cluster is
reachable. Earlier UTS 43030 Assessment Task 3 evidence (P2, A3 report §2.2)
reported these as **skipped**, not passed, because no suitable local cluster
was available at the time. This document is the first run against a real
cluster and records what was actually observed, not a retrospective claim.

## Scope and honesty statement

- All commands below were run against a dedicated, disposable kind cluster
  named `inventory-prod`, created solely for this verification and deleted
  immediately afterward (see "Teardown" below).
- No other Kubernetes cluster or kubeconfig context was read, modified, or
  deleted. `kind get clusters` showed no existing clusters before this run.
- Every result in this document is copied from an actual command output in
  this session. Nothing here is inferred or reconstructed from code reading.
- Zero cloud cost: everything ran on local Docker Desktop (kind nodes are
  containers); no cloud account, managed Kubernetes service, or paid API was
  used.

## Environment

| Component | Version |
|---|---|
| Docker | Client 29.1.3 / Server 29.1.3 (Docker Desktop 4.55.0) |
| kind | v0.33.0 |
| kubectl (client) | v1.34.1 |
| Kubernetes (kind node / server) | v1.37.0 |
| Calico CNI | v3.28.0 (pinned in `scripts/setup-cluster.sh`) |
| OS | macOS (darwin/arm64) |
| Repository commit under test | `117427b1557f552eceee4739d4b048dec3bb39b0` (branch `feat/uts-a3-security-evidence`) |

Note: `kubectl version` reported a client/server minor-version skew warning
(client v1.34 vs server v1.37, outside the documented ±1 support window).
This is a benign version mismatch between the locally installed `kubectl`
binary and the kind node image's bundled server version — it did not affect
any test result; every test below communicated successfully with the
apiserver.

## Steps performed

1. `kind get clusters` → confirmed no cluster existed yet.
2. `kubectl config get-contexts` → confirmed no kubeconfig context existed yet.
3. `./scripts/setup-cluster.sh` → created the `inventory-prod` kind cluster
   (1 control-plane + 2 workers), installed Calico v3.28.0, ingress-nginx,
   and metrics-server. All nodes reached `Ready`.
4. `kubectl config current-context` → confirmed `kind-inventory-prod` before
   running any further kubectl command, so no command could land on an
   unrelated cluster.
5. `./scripts/deploy.sh` → built `inventory-api:local` and
   `demo-observer:local` images locally, loaded them into the kind nodes
   (no registry push), and applied every manifest in `k8s/` in dependency
   order. `postgres`, `inventory-api` (3/3 replicas), and `demo-observer`
   all reached `Ready`/`Available`.
6. `pytest tests/security -v -m integration` → ran exactly the 17 tests
   `conftest.requires_live_cluster` would otherwise skip.
7. `pytest tests/security -v` → full 36-test suite (19 static + 17 live) run
   together as a final consistency check.
8. `./scripts/verify.sh` → functional smoke check (health, readiness, API,
   observer dashboard API) via port-forward, not part of the security suite
   but run as corroborating evidence that the deployment was genuinely live.
9. `kind delete cluster --name inventory-prod` → teardown (see below).

## Results — 17 live security tests

```
collected 36 items / 19 deselected / 17 selected

tests/security/test_networkpolicy_live.py::test_unlabeled_pod_in_same_namespace_cannot_reach_api_directly PASSED
tests/security/test_networkpolicy_live.py::test_pod_labeled_as_ingress_nginx_app_still_blocked_without_matching_namespace PASSED
tests/security/test_networkpolicy_live.py::test_api_pod_itself_can_still_resolve_and_serve_health_check PASSED
tests/security/test_rbac_live.py::test_inventory_api_can_get_its_own_configmap PASSED
tests/security/test_rbac_live.py::test_inventory_api_can_get_its_own_secret PASSED
tests/security/test_rbac_live.py::test_observer_can_list_pods PASSED
tests/security/test_rbac_live.py::test_observer_can_get_deployments PASSED
tests/security/test_rbac_live.py::test_inventory_api_cannot_list_secrets_namespace_wide PASSED
tests/security/test_rbac_live.py::test_inventory_api_cannot_delete_its_own_secret PASSED
tests/security/test_rbac_live.py::test_inventory_api_cannot_get_unrelated_secret PASSED
tests/security/test_rbac_live.py::test_inventory_api_cannot_get_pods PASSED
tests/security/test_rbac_live.py::test_observer_cannot_get_secrets PASSED
tests/security/test_rbac_live.py::test_observer_cannot_get_configmaps PASSED
tests/security/test_rbac_live.py::test_observer_cannot_delete_pods PASSED
tests/security/test_rbac_live.py::test_observer_cannot_delete_deployments PASSED
tests/security/test_rbac_live.py::test_observer_cannot_patch_deployments PASSED
tests/security/test_rbac_live.py::test_neither_serviceaccount_has_namespace_wide_wildcard_access PASSED

====================== 17 passed, 19 deselected in 22.39s ======================
```

**17 / 17 live tests passed.** This means:

- NetworkPolicy enforcement (Calico, not kindnet) was confirmed live: an
  unlabeled pod inside the namespace could **not** reach `inventory-api`
  directly, and a pod that forged the `app: ingress-nginx` pod label (without
  being in the `ingress-nginx` namespace) was **also** blocked — the policy
  is genuinely keyed on `namespaceSelector`, not a spoofable pod label. The
  positive control (the API pod reaching its own health endpoint over
  loopback) succeeded, so the two negative results are not an artifact of a
  broken network — default-deny is actually doing the denying.
- RBAC enforcement was confirmed live via `kubectl auth can-i --as=<sa>`,
  which asks the real apiserver authorizer, not a simulation: both
  ServiceAccounts could do exactly what their Role grants (get their own
  named ConfigMap/Secret, list/get pods and deployments respectively) and
  were denied everything outside that — including the namespace-wide `list`
  on Secrets that scoped `get`/`watch` on one named object does not imply,
  cross-boundary access between the two ServiceAccounts, and wildcard
  (`*`/`*`) access for either identity.

## Results — full suite (static + live)

```
============================= 36 passed in 18.66s ==============================
```

19 static + 17 live = 36/36 passed. This matches the test counts already
reported in the A3 report and P2 portfolio evidence; what changes is that
the 17 live tests are now **actually executed and passed**, not skipped.

## Functional corroboration (`scripts/verify.sh`)

Port-forwarded health/readiness/API checks on `inventory-api` and
`demo-observer` all returned successful JSON responses (see
`verify_run1.log`, retained alongside this document's source commit in the
session scratchpad referenced in the A3 submission). This is not a security
test, but it confirms the stack the RBAC/NetworkPolicy tests ran against was
a genuinely working deployment, not an empty or crash-looping one.

## New security issues found

None. No new issue was discovered by this live run. The previously
documented residual finding (`postgres` container, `readOnlyRootFilesystem`
not set, Trivy `KSV-0014` HIGH, intentionally retained and explained in
`docs/threat-model.md` T13) was not re-scanned in this session — it is a
static configuration finding, independent of the live RBAC/NetworkPolicy
behaviour exercised here, and is already accurately documented as an open,
accepted risk rather than a gap this run was scoped to close.

## Teardown

```
$ kind get clusters        # before teardown
inventory-prod
$ kind delete cluster --name inventory-prod
Deleting cluster "inventory-prod" ...
$ kind get clusters        # after teardown
No kind clusters found.
$ kubectl config get-contexts
CURRENT   NAME   CLUSTER   AUTHINFO   NAMESPACE
```

Only the `inventory-prod` cluster created for this run existed at any point;
teardown removed it and left zero kind clusters and zero kubeconfig
contexts, confirming no other environment was touched.

## Reproduction

```
./scripts/setup-cluster.sh
./scripts/deploy.sh
pytest tests/security -v -m integration   # the 17 live tests
pytest tests/security -v                  # full 36-test suite
./scripts/verify.sh                       # optional functional corroboration
kind delete cluster --name inventory-prod # teardown
```
