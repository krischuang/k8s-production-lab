"""demo-observer: a read-only view onto the inventory-api Deployment/HPA/pods,
built specifically so the browser dashboard never needs Kubernetes API
credentials of its own. See README "Live Demo" / "Kubernetes observer
architecture" for the security boundary this exists to enforce:

  browser  --(HTTP, no k8s credentials)-->  demo-observer  --(SA token, read-only)--> kube-apiserver

The inventory-api Deployment's own ServiceAccount/RBAC (k8s/rbac.yaml) is
untouched by any of this -- this is a separate component with its own,
narrower, read-only Role (k8s/observer-rbac.yaml).
"""
import os
import pathlib
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import k8s_client

app = FastAPI(title="demo-observer")

STATIC_DIR = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

INGRESS_BASE_URL = os.getenv(
    "OBSERVER_INGRESS_URL", "http://ingress-nginx-controller.ingress-nginx.svc.cluster.local"
)
INGRESS_HOST_HEADER = os.getenv("OBSERVER_INGRESS_HOST", "inventory.local")
PROXY_TIMEOUT_SECONDS = float(os.getenv("OBSERVER_PROXY_TIMEOUT_SECONDS", "5"))


def _pod_ready(pod: dict) -> bool:
    for condition in pod.get("status", {}).get("conditions", []) or []:
        if condition.get("type") == "Ready":
            return condition.get("status") == "True"
    return False


def _pod_restart_count(pod: dict) -> int:
    statuses = pod.get("status", {}).get("containerStatuses", []) or []
    return sum(s.get("restartCount", 0) for s in statuses)


def _pod_age_seconds(pod: dict) -> float | None:
    ts = pod.get("metadata", {}).get("creationTimestamp")
    if not ts:
        return None
    created = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - created).total_seconds(), 1)


def _pod_version(pod: dict) -> str:
    return pod.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/version", "unknown")


def _pod_not_ready_reason(pod: dict) -> str:
    for status in pod.get("status", {}).get("containerStatuses", []) or []:
        waiting = status.get("state", {}).get("waiting")
        if waiting:
            return waiting.get("reason", "ContainerNotStarted")
    if pod.get("status", {}).get("phase") == "Running":
        return "Readiness probe failing"
    return pod.get("status", {}).get("phase", "Unknown")


def _owned_by(obj: dict, uid: str) -> bool:
    for ref in obj.get("metadata", {}).get("ownerReferences", []) or []:
        if ref.get("uid") == uid:
            return True
    return False


def _summarize_pod(pod: dict) -> dict:
    return {
        "name": pod.get("metadata", {}).get("name", "unknown"),
        "ready": _pod_ready(pod),
        "node": pod.get("spec", {}).get("nodeName") or "unassigned",
        "version": _pod_version(pod),
        "restarts": _pod_restart_count(pod),
        "age_seconds": _pod_age_seconds(pod),
        "phase": pod.get("status", {}).get("phase", "Unknown"),
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def api_status() -> dict:
    deployment = await k8s_client.get_deployment()
    hpa = await k8s_client.get_hpa()

    spec = deployment.get("spec", {})
    status = deployment.get("status", {})
    desired = spec.get("replicas", 0)
    ready = status.get("readyReplicas", 0) or 0
    updated = status.get("updatedReplicas", 0) or 0
    available = status.get("availableReplicas", 0) or 0
    version = (
        spec.get("template", {})
        .get("metadata", {})
        .get("labels", {})
        .get("app.kubernetes.io/version", "unknown")
    )

    hpa_spec = hpa.get("spec", {})
    hpa_status = hpa.get("status", {})

    target_cpu = None
    for metric in hpa_spec.get("metrics", []) or []:
        if metric.get("type") == "Resource" and metric.get("resource", {}).get("name") == "cpu":
            target_cpu = metric.get("resource", {}).get("target", {}).get("averageUtilization")

    current_cpu = None
    for metric in hpa_status.get("currentMetrics", []) or []:
        if metric.get("type") == "Resource" and metric.get("resource", {}).get("name") == "cpu":
            current_cpu = metric.get("resource", {}).get("current", {}).get("averageUtilization")

    return {
        "healthy": desired > 0 and ready == desired and updated == desired,
        "version": version,
        "replicas": {
            "ready": ready,
            "desired": desired,
            "updated": updated,
            "available": available,
        },
        "hpa": {
            "current": hpa_status.get("currentReplicas", desired),
            "desired": hpa_status.get("desiredReplicas", desired),
            "min": hpa_spec.get("minReplicas"),
            "max": hpa_spec.get("maxReplicas"),
            "target_cpu_percent": target_cpu,
            "current_cpu_percent": current_cpu,
        },
    }


@app.get("/api/pods")
async def api_pods() -> dict:
    pods = await k8s_client.get_pods()
    summarized = sorted((_summarize_pod(p) for p in pods), key=lambda p: p["name"])
    return {"pods": summarized}


@app.get("/api/deployment")
async def api_deployment() -> dict:
    deployment = await k8s_client.get_deployment()
    replicasets = await k8s_client.get_replicasets()
    pods = await k8s_client.get_pods()

    deployment_uid = deployment.get("metadata", {}).get("uid")
    owned = [rs for rs in replicasets if _owned_by(rs, deployment_uid)]
    live = [
        rs
        for rs in owned
        if (rs.get("spec", {}).get("replicas") or 0) > 0
        or (rs.get("status", {}).get("replicas") or 0) > 0
    ]
    live.sort(key=lambda rs: rs["metadata"]["creationTimestamp"])

    new_rs = live[-1] if live else None
    old_rss = live[:-1]

    new_replicas = (new_rs.get("spec", {}).get("replicas") or 0) if new_rs else 0
    ready_new_replicas = (new_rs.get("status", {}).get("readyReplicas") or 0) if new_rs else 0
    healthy_old_replicas = sum((rs.get("status", {}).get("readyReplicas") or 0) for rs in old_rss)

    rolling_out = len(old_rss) > 0 and new_replicas > 0

    reason = None
    if rolling_out and ready_new_replicas < new_replicas and new_rs is not None:
        new_hash = new_rs.get("metadata", {}).get("labels", {}).get("pod-template-hash")
        new_pods = [
            p
            for p in pods
            if p.get("metadata", {}).get("labels", {}).get("pod-template-hash") == new_hash
        ]
        not_ready = [p for p in new_pods if not _pod_ready(p)]
        if not_ready:
            reason = _pod_not_ready_reason(not_ready[0])

    total_ready = healthy_old_replicas + ready_new_replicas if live else sum(
        1 for p in pods if _pod_ready(p)
    )

    return {
        "rolling_out": rolling_out,
        "healthy_old_replicas": healthy_old_replicas,
        "new_replicas": new_replicas,
        "ready_new_replicas": ready_new_replicas,
        "reason": reason,
        "service_available": total_ready > 0,
    }


@app.post("/api/route-request")
async def route_request() -> dict:
    """Proxies one real request through the same Ingress path a browser
    client would use, and reports which pod actually answered it -- the
    backend for the dashboard's "Send Request" button. This call goes
    Service -> Ingress -> inventory-api, load-balanced exactly like real
    traffic; the observer does not fabricate or guess the responding pod."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{INGRESS_BASE_URL}/api/whoami",
                headers={"Host": INGRESS_HOST_HEADER},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - surfaced to the dashboard as-is
        raise HTTPException(status_code=502, detail=f"upstream request failed: {exc}")

    return {**data, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
