# 5-Minute Interview Walkthrough

Prep, before the interview starts: run `./scripts/demo.sh`. It checks Docker/kind/kubectl are present, the cluster exists, and all three Deployments (`inventory-api`, `postgres`, `demo-observer`) are ready. Fix anything it flags before you're on the call — don't discover a stale cluster live.

Two windows, side by side: a terminal, and a browser at `http://localhost:8090/` (run `./scripts/dashboard.sh` to open it).

## Minute 0-1: Architecture and healthy baseline

Show the dashboard. Point at:
- **Application Health**: `HEALTHY`, version `v1.0.0`, `3 Ready / 3 Desired`
- **Autoscaling**: `Current: 3`, `Min: 3`, `Max: 10`, `Target: 60%`
- **Live Pods**: 3 rows, all `READY`, spread across `inventory-prod-worker` and `inventory-prod-worker2`

One sentence on the shape of it: FastAPI service, 3 replicas behind a ClusterIP Service and an nginx Ingress, backed by Postgres, all on a local kind cluster with Calico enforcing NetworkPolicy. The dashboard itself is a separate, read-only component (`demo-observer`) — worth a one-liner: "the browser never touches the Kubernetes API directly, it talks to a small backend with a scoped-down ServiceAccount."

## Minute 1-2: Request routing across replicas

Click **Send Request** in the Request Routing card 4-5 times, fairly quickly.

Narrate as it happens: each click sends one real HTTP request through the Ingress and the Service, and the response tells you which pod actually handled it. The pod name in the history should rotate — that's kube-proxy load balancing, observed live, not asserted from a diagram.

## Minute 2-3: HPA under load

In the terminal:

```
./scripts/load-test.sh 240 60
```

While it runs, keep the dashboard visible. CPU% climbs past the 60% target within ~20-30 seconds; Current replicas starts climbing shortly after (3 → 5 → 7 → 9 → 10 in the recorded run this repo ships with). New rows in the Live Pods table flash green as they appear.

You don't need to wait for the full scale-down on camera — mention that it happens gradually (one pod removed roughly every 60 seconds once load clears) by design, to avoid flapping, and move on. If there's time later, glance back at it.

## Minute 3-4: Broken release and readiness failure

In the terminal:

```
./scripts/simulate-bad-release.sh
```

Watch the **Deployment Status** card: it flips to `Rollout in progress`, shows `Healthy old replicas: 3`, `New replicas: 1`, `Ready new replicas: 0`, and a reason: `Readiness probe failing`.

The point to make explicitly: **Service still says "Still Available."** The new broken pod never receives traffic because the readiness probe keeps it out of the Service's endpoint list — that's why `maxUnavailable: 0` combined with readiness probes means a bad deploy doesn't cause an outage, it just... doesn't finish rolling out.

## Minute 4-5: Rollback and recovery

In the terminal:

```
./scripts/rollback.sh
```

Watch the dashboard settle back to `Stable`, `3 Ready / 3 Desired`, `HEALTHY` — no page reload, no manual refresh. That's the whole incident-and-recovery loop, timed, on camera.

---

**If asked "how do I know this isn't just a UI mockup?"**: point at the terminal running `kubectl get pods -n inventory-prod -o wide` alongside the dashboard and note the pod names and node assignments match exactly — the README's "Live Demo Dashboard" and "Kubernetes observer architecture" sections cover how (`demo-observer`'s read-only RBAC) and why (least privilege, mutations stay in the scripts, not the browser).
