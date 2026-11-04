# OWASP API Security Review — k8s-production-lab

Reviewed against the [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
plus Kubernetes-specific risks not covered by that list. Every row is
checked against the actual committed code (`app/main.py`, `observer/main.py`,
`observer/k8s_client.py`) and manifests (`k8s/*.yaml`), not against what the
README describes the system as intending to do. "N/A" items explain why the
risk category doesn't apply to this specific system rather than being
silently skipped.

Security scanning referenced below was performed with `trivy` v0.76.1
(`trivy config k8s/`, `trivy config app/Dockerfile`,
`trivy config observer/Dockerfile`, `trivy fs app/requirements.txt`,
`trivy fs observer/requirements.txt`) on 2026-11-01.

## OWASP API Security Top 10 (2023)

| Risk | Applicability | Current Implementation | Verified Evidence | Missing Control | Recommended Mitigation | Residual Risk |
|---|---|---|---|---|---|---|
| **API1:2023 — Broken Object Level Authorization** | N/A | `/api/items` returns a fixed, non-user-scoped list; no endpoint accepts an object ID owned by a specific caller | `app/main.py:81-83` (`list_items` takes no parameters) | — | — | None — there is no per-object ownership model to violate |
| **API2:2023 — Broken Authentication** | **Applicable — confirmed gap** | Zero authentication on any `inventory-api` or `demo-observer` endpoint | `app/main.py` has no auth dependency/middleware on any route; `observer/main.py` same; `README.md:542` self-discloses "the dashboard has no auth of its own" | API key / OAuth2 / mTLS on `inventory-api`; any auth at all on `demo-observer` | Add auth before either service is reachable from anything beyond a trusted local demo | **Medium** — mitigated today only by `NetworkPolicy` restricting *reachability*, not by authenticating *who* reaches it |
| **API3:2023 — Broken Object Property Level Authorization** | Applicable — minor | `/api/whoami` returns internal infra identifiers (pod name, node name, namespace) to any caller | `app/main.py:86-96` | Field-level filtering for non-trusted callers | If ever exposed beyond a trusted demo, drop `node`/`pod` from the public response | Low — useful recon data if the system were ever public-facing, but by design for this demo |
| **API4:2023 — Unrestricted Resource Consumption** | **Applicable — confirmed gap** | No per-client rate limiting anywhere; HPA provides a resource *ceiling*, not throttling | `k8s/ingress.yaml` has no `limit-rps`/`limit-connections` annotations; `k8s/hpa.yaml:12-13` `maxReplicas: 10` is a hard ceiling, not a defense | Rate limiting at the Ingress or app layer | Add `nginx.ingress.kubernetes.io/limit-rps` (see `docs/threat-model.md` P2 mitigation) | Medium in a public-facing scenario; low in this local-only context |
| **API5:2023 — Broken Function Level Authorization** | Partially applicable | K8s layer: RBAC strictly separates `inventory-api` (config/secret read) from `demo-observer` (cluster-state read); App layer: N/A, no privileged functions exist in `app/main.py`/`observer/main.py` to protect | `k8s/rbac.yaml`, `k8s/observer-rbac.yaml`; `tests/security/test_rbac_static.py` (19/19 passing, see test run below); `tests/security/test_rbac_live.py` (requires live cluster) | — at K8s layer; N/A at app layer | — | **Low** at K8s layer (automated tests assert denial); N/A at app layer |
| **API6:2023 — Unrestricted Access to Sensitive Business Flows** | N/A | No checkout/purchase/account-modification flow exists — this is a read-only inventory demo plus one proxy endpoint | `app/main.py`, `observer/main.py` — no mutating endpoints at all | — | — | None |
| **API7:2023 — Server-Side Request Forgery** | Applicable — reviewed, currently safe | `demo-observer`'s `POST /api/route-request` makes an outbound HTTP call, but the destination is built entirely from deployment-time env vars (`OBSERVER_INGRESS_URL`, `OBSERVER_INGRESS_HOST`), never from request input | `observer/main.py:208-227` — `route_request()` takes no parameters; the only free variables are the two env constants set in `k8s/observer-deployment.yaml:36-39` | A regression test asserting no future change lets request input reach the destination URL | Add a test that fails if `route_request`'s signature gains a parameter that flows into `INGRESS_BASE_URL`/`INGRESS_HOST_HEADER` | Low today; this is the kind of control that silently rots, so flagged explicitly as a watch-item in `docs/threat-model.md` |
| **API8:2023 — Security Misconfiguration** | **Applicable — confirmed findings, fixed during this review** | See "Security Scanning Results" below | `trivy config k8s/` | TLS (not fixed — see Residual Risk) | See `docs/threat-model.md` §8 Proposed Mitigations | **Medium** — TLS is the one item not fixed in this pass; it is real, open, and documented, not hidden |
| **API9:2023 — Improper Inventory Management** | **Applicable — confirmed gap** | FastAPI's default interactive docs/schema endpoints (`/docs`, `/redoc`, `/openapi.json`) are enabled and unauthenticated, exposing the full API surface to anyone who can reach the Ingress | `app/main.py:8` — `FastAPI(title="inventory-api")` with no `docs_url=None`/`openapi_url=None` override | Disable or auth-gate `/docs`/`/openapi.json` outside local development | Set `docs_url=None, redoc_url=None, openapi_url=None` for any non-local deployment profile | Low in this local-only demo; would matter the moment this is reachable beyond `kind` |
| **API10:2023 — Unsafe Consumption of APIs** | Applicable — reviewed, low risk | `demo-observer` consumes `kube-apiserver` responses via plain `.get()` field access with defaults, no schema validation | `observer/main.py:36-86`, `observer/k8s_client.py:44-69` | Schema validation if the upstream ever becomes less trusted | Not urgent — `kube-apiserver` is an internal, trusted source in this design | Low |

## Kubernetes-Specific Security Risks (not covered by the OWASP API list)

| Risk | Applicability | Current Implementation | Verified Evidence | Missing Control | Recommended Mitigation | Residual Risk |
|---|---|---|---|---|---|---|
| RBAC over-privilege | Applicable — controlled | Namespace-scoped Roles only, `resourceNames`-locked, no wildcards, no ClusterRole | `k8s/rbac.yaml`, `k8s/observer-rbac.yaml`; `tests/security/test_rbac_static.py` | — | — | Low |
| Network segmentation | Applicable — controlled | Default-deny-all + 5 narrow allow rules | `k8s/networkpolicy.yaml`; `tests/security/test_networkpolicy_static.py` | — | — | Low |
| Pod/container hardening (Pod Security Standards-equivalent) | Applicable — controlled after this review | `runAsNonRoot`, `allowPrivilegeEscalation: false`, capabilities dropped, `seccompProfile`, `readOnlyRootFilesystem` on all 3 workloads | `k8s/deployment.yaml`, `k8s/observer-deployment.yaml`, `k8s/postgres.yaml`; `trivy config k8s/` → 0 findings; `postgres` additionally verified live on a `kind` cluster (`1/1 Running`, probes pass with `/tmp` and `/var/run/postgresql` as `emptyDir` mounts) | — | — | Low |
| Secrets management | Applicable — controlled with caveats | Real credentials never committed; `Secret` object used, not `ConfigMap` | `k8s/secret.example.yaml`, `.gitignore` | External secrets manager (Vault/AWS Secrets Manager/Sealed Secrets); etcd encryption-at-rest unverified | Documented as a known limitation, not fixed (`README.md:294`) | Low-Medium — base64 is encoding, not encryption; **CANNOT VERIFY** etcd-at-rest encryption without live cluster inspection |
| Supply chain / image provenance | **Applicable — confirmed gap** | Images are built locally (`inventory-api:local`, `demo-observer:local`) and loaded directly into `kind`; no registry, no signing, no vulnerability scanning of the *built image* (only of the Dockerfile config and the Python dependency list) | `trivy config app/Dockerfile` / `observer/Dockerfile` → 0 findings (Dockerfile config only); `trivy fs app/requirements.txt` / `observer/requirements.txt` → 0 findings (dependency CVEs only); **no `trivy image` scan of the built container has been run**, since no container runtime was available during this review | Image vulnerability scanning (`trivy image`) in CI, where a container runtime is available | Added as a CI step in `.github/workflows/ci.yml` `security-scan` job (scans the Dockerfile/dependency surface on every push; image-layer scanning requires the `build` job's images and is a documented follow-up — see `docs/threat-model.md`) | Medium — base image CVEs in the final built image are currently unverified |
| Admission control / policy enforcement | **Applicable — confirmed gap, N/A reason given where relevant** | None — no OPA/Gatekeeper/Kyverno/PodSecurity admission configured | `README.md:540` self-discloses this | Namespace-level `PodSecurity` admission label at minimum | See `docs/threat-model.md` P2 mitigation | Medium — nothing *enforces* that a future workload in this namespace keeps the same hardening |
| Observability / audit logging | **Applicable — confirmed gap** | None — no Prometheus/Grafana/centralized logging/tracing | `README.md:537` self-discloses this | Any log aggregation beyond `kubectl logs` | See `docs/threat-model.md` P3 mitigation | Medium for incident response specifically, not for prevention |

## Security Scanning Results (this review)

Full detail and fix rationale: `docs/threat-model.md` §§5-8. Summary:

| File | Findings before this review | Findings after | Disposition |
|---|---|---|---|
| `k8s/postgres.yaml` | 6 (3 MEDIUM, 3 HIGH) — missing `securityContext` entirely | 0 | Fixed — added pod/container `securityContext` including `readOnlyRootFilesystem: true`, with `/tmp`/`/var/run/postgresql` `emptyDir` mounts; verified live on a `kind` cluster |
| `k8s/deployment.yaml` | 2 (1 MEDIUM, 1 HIGH) — missing pod-level `securityContext`/`seccompProfile` | 0 | Fixed — added pod-level `seccompProfile: RuntimeDefault` |
| `k8s/observer-deployment.yaml` | 2 (1 MEDIUM, 1 HIGH) — same as above | 0 | Fixed — same change |
| `k8s/rbac.yaml` | 1 (MEDIUM) — generic "Role touches secrets" heuristic | 0 (suppressed) | Reviewed and accepted: `resourceNames` scoping to one named Secret *is* the mitigation this rule checks for; see `.trivyignore` |
| `k8s/configmap.yaml` | 1 (MEDIUM) — `POSTGRES_PORT` flagged as "sensitive" by keyword heuristic | 0 (suppressed) | Reviewed and accepted: the value is a port number, not a credential; see `.trivyignore` |
| `app/Dockerfile`, `observer/Dockerfile` | 0 | 0 | Clean |
| `app/requirements.txt`, `observer/requirements.txt` (dependency CVEs) | 0 | 0 | Clean |

Every suppression in `.trivyignore` is tied to a specific finding ID and a
written justification in that file — nothing is suppressed without a
reason someone else can check.
