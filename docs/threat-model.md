# Threat Model — k8s-production-lab

This threat model is written against the implementation actually committed
to this repository, not an aspirational design. Every control cited below
has a file path; every gap is a real, currently-unmitigated gap, not a
hypothetical. Where a claim could not be verified without a live cluster
(none was running when this was written), it is marked **CANNOT VERIFY**
rather than assumed.

## 1. System Overview

`inventory-api` is a FastAPI service running as 3+ replicas behind an
nginx Ingress controller, backed by a single in-cluster Postgres instance.
A second, independent component, `demo-observer`, provides a read-only
dashboard over cluster state (pods, Deployment, HPA) for demo purposes,
reached only via `kubectl port-forward`, never through the Ingress.
Everything runs in a local `kind` cluster with Calico as the CNI (the
only CNI here that actually enforces `NetworkPolicy`).

```
Client --HTTP--> ingress-nginx --(NetworkPolicy allow)--> inventory-api pods --(NetworkPolicy allow)--> Postgres
Browser --(kubectl port-forward, no k8s creds)--> demo-observer --(ServiceAccount token, read-only)--> kube-apiserver
```

Source: `README.md` "Architecture" (lines 19-86).

## 2. Assets and Trust Boundaries

| Asset | Why it matters | Trust boundary crossed |
|---|---|---|
| `inventory-api` HTTP endpoints | Serves business data (`/api/items`) | Internet → Ingress → pod network |
| `inventory-db-credentials` Secret | Postgres username/password/connection string | Secret store → pod env |
| Postgres data | Application's only persistent data | Pod network → Postgres pod |
| `inventory-api` / `demo-observer` ServiceAccount tokens | Cryptographic identity presented to kube-apiserver | Pod filesystem → API server |
| kube-apiserver | Cluster control plane | Pod network → control plane (host-networked) |
| `demo-observer` dashboard | Read-only view of cluster state, no auth of its own | Operator's machine → pod (via port-forward, bypasses pod network) |
| CI pipeline / container images | Supply chain for what actually runs | GitHub Actions runner → built image → `kind load docker-image` |

Boundary enumeration source: `k8s/networkpolicy.yaml`, `k8s/observer-networkpolicy.yaml`, `k8s/rbac.yaml`, `k8s/observer-rbac.yaml`, `observer/k8s_client.py:12-32`.

## 3. STRIDE Threat Analysis

| ID | STRIDE | Threat | Affected component | Existing control | Evidence |
|---|---|---|---|---|---|
| T1 | Spoofing | Client bypasses Ingress and hits an `inventory-api` pod directly from elsewhere in the cluster | `inventory-api` pods | `NetworkPolicy allow-ingress-from-nginx` restricts ingress to the `ingress-nginx` namespace only | `k8s/networkpolicy.yaml:21-39`; verified live in `README.md:383-392` and automated in `tests/security/test_networkpolicy_live.py::test_unlabeled_pod_in_same_namespace_cannot_reach_api_directly` |
| T2 | Spoofing | A pod already inside `inventory-prod` applies `app: inventory-api`-like labels to itself to satisfy a podSelector it doesn't legitimately belong to | `inventory-api` pods | Partial — NetworkPolicy matches on labels, not cryptographic identity | No admission control (OPA/Gatekeeper/Kyverno) restricts label usage — see §6 Residual Risks |
| T3 | Spoofing | Stolen ServiceAccount token (via container compromise) used to impersonate `inventory-api` or `demo-observer` to the API server | ServiceAccount tokens | RBAC scoping limits what a stolen token can do; token TTL/audience binding depends on cluster defaults | `k8s/rbac.yaml`, `k8s/observer-rbac.yaml`; **CANNOT VERIFY** actual token TTL/audience without inspecting a live cluster's kube-apiserver flags |
| T4 | Tampering | Unauthorized party attempts to call `inventory-api` to tamper with responses (no write endpoints exist today, but future-proofing matters) | `inventory-api` | Same `NetworkPolicy` default-deny as T1 | `k8s/networkpolicy.yaml:7-16`; `app/main.py` has no write/mutation endpoints as of this audit |
| T5 | Tampering | Man-in-the-middle tampering of Client↔Ingress or Ingress↔pod traffic (plaintext HTTP) | All HTTP traffic | **None** | `README.md:535` self-discloses "No TLS. The Ingress serves plain HTTP" — real, open gap |
| T6 | Tampering | Unauthorized write to `inventory-api-config` ConfigMap | ConfigMap | No identity in this repo's manifests holds `create`/`update`/`patch` on configmaps | `k8s/rbac.yaml` grants only `get`/`watch`; confirmed by `tests/security/test_rbac_static.py::test_inventory_api_role_has_no_write_verbs` |
| T7 | Repudiation | No record of who called which endpoint when, if an incident needs investigating after the fact | Whole system | **None at the application level** | `README.md:537` self-discloses "No observability stack... no centralized logging" |
| T8 | Information Disclosure | `demo-observer` dashboard (pod names, nodes, rollout state) is reachable with zero authentication of its own | `demo-observer` | Mitigated by *reachability*, not auth: only exposed via `kubectl port-forward`, no Ingress rule exists for it | `k8s/observer-networkpolicy.yaml:23-27` ("Deliberately absent: any ingress rule for demo-observer"); `README.md:542` self-discloses "The dashboard has no auth of its own" |
| T9 | Information Disclosure | Secret values readable from pod environment (`kubectl describe pod`, container exec) or at rest if etcd encryption isn't configured | `inventory-db-credentials` | Real Secret never committed to git; Secret object used (not a ConfigMap) | `k8s/secret.example.yaml` (placeholder only, `.gitignore` excludes the real file); **CANNOT VERIFY** etcd encryption-at-rest without live cluster/kube-apiserver config |
| T10 | Denial of Service | High-volume request flood exhausts capacity before HPA reacts, or past `maxReplicas: 10` | `inventory-api` | Partial — HPA scales legitimate load; no rate limiting, no WAF | `k8s/hpa.yaml:12-13` (`maxReplicas: 10` is a hard ceiling); no rate-limiting annotation on `k8s/ingress.yaml` |
| T11 | Elevation of Privilege | Compromised `inventory-api` pod attempts to read Secrets/ConfigMaps beyond its own two named objects | `inventory-api` ServiceAccount | RBAC Role scoped by `resourceNames`, `get`/`watch` only | `k8s/rbac.yaml:17-24`; verified by `tests/security/test_rbac_static.py` and (live, when run against a cluster) `tests/security/test_rbac_live.py::test_inventory_api_cannot_list_secrets_namespace_wide` |
| T12 | Elevation of Privilege | Compromised `demo-observer` pod attempts to mutate Deployments/pods it can only read | `demo-observer` ServiceAccount | RBAC Role limited to `get`/`list`/`watch` on 4 resource kinds, no write verbs, no ClusterRole | `k8s/observer-rbac.yaml:14-28`; verified by `tests/security/test_rbac_static.py::test_observer_role_is_strictly_read_only` and `tests/security/test_rbac_live.py::test_observer_cannot_delete_deployments` |
| T13 | Tampering | Attacker with exec/compromise access to the `postgres` container writes to its root filesystem (persistence, tooling install) | `postgres` container | Mitigated — `runAsNonRoot`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` all set, with `/tmp` and `/var/run/postgresql` `emptyDir` mounts for the paths Postgres needs to write to | `k8s/postgres.yaml`; `trivy config k8s/postgres.yaml` → 0 findings; verified live on a `kind` cluster — `postgres` deployment reaches `1/1 Running`, readiness/liveness probes (`pg_isready`) pass |

## 4. Threat Scenarios (narrative)

**Scenario A — Compromised `inventory-api` pod.** An attacker achieves code
execution inside an `inventory-api` container (e.g. a hypothetical future
dependency vulnerability — `trivy fs app/requirements.txt` found none at
the time of this audit). They have the pod's ServiceAccount token. RBAC
limits them to reading exactly `inventory-api-config` and
`inventory-db-credentials` (T11) — not every Secret in the namespace. They
cannot reach any pod outside `inventory-prod` (`NetworkPolicy` default-deny)
and cannot reach Postgres from any identity except the `inventory-api`
podSelector itself, which they already are. **Net effect: blast radius is
the Postgres credentials already available to this pod via env vars, not
lateral movement to other workloads or the API server.**

**Scenario B — Compromised `demo-observer` pod.** Same entry vector,
different component. RBAC limits them to `get`/`list`/`watch` on pods,
deployments, replicasets, HPAs — read-only, one namespace (T12). They
cannot scale, delete, or patch anything. They can, however, read Deployment
and pod metadata, which is deliberately treated as non-sensitive
(`k8s/configmap.yaml` comment: "Non-sensitive application configuration").

**Scenario C — Network-level attacker inside the cluster but outside
`inventory-prod`.** Blocked outright by `default-deny-all` (T1, T4) —
confirmed live in `README.md:383-392` and now automated in
`tests/security/test_networkpolicy_live.py`.

**Scenario D — Passive network observer on the same host/network as the
`kind` cluster.** Can read all HTTP traffic in cleartext (T5) — this
scenario is *not* mitigated and is the single largest gap this threat model
identifies, acceptable only because the entire system runs on a local,
single-operator `kind` cluster with no external network exposure.

## 5. Existing Security Controls (summary)

| Control | Scope | Evidence |
|---|---|---|
| Least-privilege RBAC, namespace-scoped Roles only | `inventory-api`, `demo-observer` | `k8s/rbac.yaml`, `k8s/observer-rbac.yaml`; `tests/security/test_rbac_static.py` |
| Default-deny NetworkPolicy + narrow allow rules | All pods in `inventory-prod` | `k8s/networkpolicy.yaml`, `k8s/observer-networkpolicy.yaml`; `tests/security/test_networkpolicy_static.py` |
| Hardened container `securityContext` (non-root, read-only rootfs, no priv-escalation, all capabilities dropped) | `inventory-api`, `demo-observer` containers | `k8s/deployment.yaml:98-104`, `k8s/observer-deployment.yaml:60-66` |
| Pod-level `seccompProfile: RuntimeDefault` | `inventory-api`, `demo-observer`, `postgres` pods | `k8s/deployment.yaml`, `k8s/observer-deployment.yaml`, `k8s/postgres.yaml` (added as part of this audit — confirmed by re-running `trivy config k8s/` after the change, see `docs/owasp-security-review.md`) |
| `postgres` container hardening (non-root UID, no priv-escalation, capabilities dropped) | `postgres` | `k8s/postgres.yaml` (added as part of this audit) |
| Secrets never committed to git | `inventory-db-credentials` | `k8s/secret.example.yaml` (placeholder), `.gitignore` |
| Automated IaC security scanning | All `k8s/*.yaml` | `trivy config k8s/`, wired into CI (`.github/workflows/ci.yml` `security-scan` job) |
| Automated negative RBAC/NetworkPolicy tests | `inventory-api`, `demo-observer` | `tests/security/` (static tests run in CI; live tests run against a real cluster, see `docs/README.md` §Security) |

## 6. Likelihood / Impact / Risk Rating

Scale: Likelihood and Impact each rated Low/Medium/High for this system's
actual deployment context (local `kind` cluster, no external exposure,
single operator) — not a generic internet-facing production rating.

| ID | Likelihood | Impact | Risk | Rationale |
|---|---|---|---|---|
| T1 | Low | Medium | Low | Requires in-cluster access already; blocked by enforced NetworkPolicy |
| T2 | Low | Medium | Low | Requires pod-create rights in-namespace already — a stronger position than this threat gains |
| T3 | Low | Medium | Low-Medium | Requires container compromise first; RBAC caps the blast radius regardless |
| T4 | Low | Low | Low | No write endpoints exist to tamper with |
| T5 | Medium | Medium | **Medium — open, undisclosed-no-longer** | Plaintext HTTP is real; mitigated only by the system being local-only |
| T6 | Low | Low | Low | No write verb granted to any identity |
| T7 | Medium | Low | Low-Medium | Matters for incident response, not for preventing the incident itself |
| T8 | Low | Low | Low | Only reachable via an already-trusted operator's `kubectl` access |
| T9 | Low | Medium | Low-Medium | Real credentials never committed; env-var exposure requires exec access already |
| T10 | Low | Medium | Low-Medium | `kind`/local demo context makes a real flood unlikely, but the HPA ceiling (`maxReplicas: 10`) is a real limit |
| T11 | Very Low | Medium | Low | Automated tests now assert this is denied |
| T12 | Very Low | Medium | Low | Automated tests now assert this is denied |
| T13 | Low | Medium | **Low — closed** | Fixed and verified live on a `kind` cluster; `trivy` finds 0 issues on `k8s/postgres.yaml` |

## 7. Residual Risks

These are not fixed by this audit and are stated plainly rather than
glossed over:

1. **T5 — No TLS.** Plaintext HTTP end-to-end. Acceptable only because this
   runs on a local, non-internet-exposed `kind` cluster. A real deployment
   would require cert-manager + a real Ingress TLS configuration.
2. **T2 — No admission control.** Nothing prevents a pod that already has
   create/patch rights in `inventory-prod` from applying misleading labels.
   `README.md:540` already self-discloses the absence of OPA/Gatekeeper/
   Kyverno/PodSecurity admission.
3. **T3/T9 — Token lifetime, audience binding, and etcd encryption at
   rest** could not be verified without a live cluster's kube-apiserver
   configuration. Marked CANNOT VERIFY rather than assumed safe.
4. **T7 — No observability/audit trail.** Already self-disclosed in
   `README.md:537`. There is no record to investigate after an incident
   beyond whatever `kubectl` happens to still show.
5. **T10 — No rate limiting / WAF.** The HPA's `maxReplicas: 10` is a hard
   ceiling, not a defense against an intentional flood.

## 8. Proposed Mitigations (prioritized, not yet implemented beyond this audit)

| Priority | Mitigation | Addresses |
|---|---|---|
| P1 | Add TLS termination at the Ingress (cert-manager + a real or self-signed CA for local use) | T5 |
| P2 | Add OPA/Gatekeeper or Kyverno admission policy enforcing the same `securityContext` hardening on any future workload in `inventory-prod` | T2 |
| P2 | Add basic rate limiting at the Ingress (`nginx.ingress.kubernetes.io/limit-rps`) | T10 |
| P3 | Add structured application logging + a minimal log-shipping sidecar or `kubectl logs`-compatible aggregation, even without a full Prometheus/Grafana stack | T7 |
| P3 | Verify ServiceAccount token audience/TTL and etcd encryption-at-rest configuration against the actual kind cluster | T3, T9 |

## 9. Evidence References

- RBAC: `k8s/rbac.yaml`, `k8s/observer-rbac.yaml`
- NetworkPolicy: `k8s/networkpolicy.yaml`, `k8s/observer-networkpolicy.yaml`
- SecurityContext: `k8s/deployment.yaml`, `k8s/observer-deployment.yaml`, `k8s/postgres.yaml`
- Secrets handling: `k8s/secret.example.yaml`, `.gitignore`
- IaC scanning results: `trivy config k8s/` (see `docs/owasp-security-review.md` for full findings and disposition), `.trivyignore`
- Automated authorization tests: `tests/security/test_rbac_static.py`, `tests/security/test_rbac_live.py`, `tests/security/test_networkpolicy_static.py`, `tests/security/test_networkpolicy_live.py`
- Manual live verification (predates this audit): `README.md` "NetworkPolicy" section, lines 365-392
