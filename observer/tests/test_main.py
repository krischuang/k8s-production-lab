import httpx
from fastapi.testclient import TestClient

from observer import k8s_client, main

client = TestClient(main.app)


def _deployment(desired=3, ready=3, updated=3, available=3):
    return {
        "metadata": {"uid": "dep-uid-1"},
        "spec": {
            "replicas": desired,
            "template": {
                "metadata": {"labels": {"app.kubernetes.io/version": "v1.0.0"}}
            },
        },
        "status": {
            "readyReplicas": ready,
            "updatedReplicas": updated,
            "availableReplicas": available,
        },
    }


def _hpa(current=3, desired=3, current_cpu=21):
    return {
        "spec": {
            "minReplicas": 3,
            "maxReplicas": 10,
            "metrics": [
                {"type": "Resource", "resource": {"name": "cpu", "target": {"averageUtilization": 60}}}
            ],
        },
        "status": {
            "currentReplicas": current,
            "desiredReplicas": desired,
            "currentMetrics": [
                {"type": "Resource", "resource": {"name": "cpu", "current": {"averageUtilization": current_cpu}}}
            ],
        },
    }


def _pod(name, ready=True, node="kind-worker", restarts=0, phase="Running", extra_labels=None):
    labels = {"app": "inventory-api", "app.kubernetes.io/version": "v1.0.0"}
    if extra_labels:
        labels.update(extra_labels)
    return {
        "metadata": {
            "name": name,
            "labels": labels,
            "creationTimestamp": "2026-09-09T00:00:00Z",
        },
        "spec": {"nodeName": node},
        "status": {
            "phase": phase,
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "containerStatuses": [{"restartCount": restarts}],
        },
    }


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_api_status_reports_healthy_deployment(monkeypatch):
    async def fake_get_deployment():
        return _deployment()

    async def fake_get_hpa():
        return _hpa()

    monkeypatch.setattr(k8s_client, "get_deployment", fake_get_deployment)
    monkeypatch.setattr(k8s_client, "get_hpa", fake_get_hpa)

    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is True
    assert body["version"] == "v1.0.0"
    assert body["replicas"] == {"ready": 3, "desired": 3, "updated": 3, "available": 3}
    assert body["hpa"]["min"] == 3
    assert body["hpa"]["max"] == 10
    assert body["hpa"]["target_cpu_percent"] == 60
    assert body["hpa"]["current_cpu_percent"] == 21


def test_api_status_unhealthy_when_not_all_ready(monkeypatch):
    async def fake_get_deployment():
        return _deployment(desired=3, ready=2, updated=3, available=2)

    async def fake_get_hpa():
        return _hpa()

    monkeypatch.setattr(k8s_client, "get_deployment", fake_get_deployment)
    monkeypatch.setattr(k8s_client, "get_hpa", fake_get_hpa)

    resp = client.get("/api/status")
    assert resp.json()["healthy"] is False


def test_api_pods_summarizes_ready_and_not_ready(monkeypatch):
    async def fake_get_pods():
        return [_pod("inventory-api-aaa", ready=True), _pod("inventory-api-bbb", ready=False)]

    monkeypatch.setattr(k8s_client, "get_pods", fake_get_pods)

    resp = client.get("/api/pods")
    assert resp.status_code == 200
    pods = resp.json()["pods"]
    assert len(pods) == 2
    by_name = {p["name"]: p for p in pods}
    assert by_name["inventory-api-aaa"]["ready"] is True
    assert by_name["inventory-api-bbb"]["ready"] is False
    assert by_name["inventory-api-aaa"]["node"] == "kind-worker"
    assert by_name["inventory-api-aaa"]["version"] == "v1.0.0"


def test_api_deployment_stable_when_single_replicaset(monkeypatch):
    rs = {
        "metadata": {
            "uid": "rs-1",
            "creationTimestamp": "2026-09-09T00:00:00Z",
            "labels": {"pod-template-hash": "abc123"},
            "ownerReferences": [{"uid": "dep-uid-1"}],
        },
        "spec": {"replicas": 3},
        "status": {"replicas": 3, "readyReplicas": 3},
    }

    async def fake_get_deployment():
        return _deployment()

    async def fake_get_replicasets():
        return [rs]

    async def fake_get_pods():
        return [_pod(f"inventory-api-{i}", extra_labels={"pod-template-hash": "abc123"}) for i in range(3)]

    monkeypatch.setattr(k8s_client, "get_deployment", fake_get_deployment)
    monkeypatch.setattr(k8s_client, "get_replicasets", fake_get_replicasets)
    monkeypatch.setattr(k8s_client, "get_pods", fake_get_pods)

    resp = client.get("/api/deployment")
    body = resp.json()
    assert body["rolling_out"] is False
    assert body["ready_new_replicas"] == 3
    assert body["service_available"] is True


def test_api_deployment_detects_bad_rollout(monkeypatch):
    old_rs = {
        "metadata": {
            "uid": "rs-old",
            "creationTimestamp": "2026-09-09T00:00:00Z",
            "labels": {"pod-template-hash": "old111"},
            "ownerReferences": [{"uid": "dep-uid-1"}],
        },
        "spec": {"replicas": 2},
        "status": {"replicas": 2, "readyReplicas": 2},
    }
    new_rs = {
        "metadata": {
            "uid": "rs-new",
            "creationTimestamp": "2026-09-09T01:00:00Z",
            "labels": {"pod-template-hash": "new222"},
            "ownerReferences": [{"uid": "dep-uid-1"}],
        },
        "spec": {"replicas": 1},
        "status": {"replicas": 1, "readyReplicas": 0},
    }
    old_pods = [
        _pod("inventory-api-old-1", ready=True, extra_labels={"pod-template-hash": "old111"}),
        _pod("inventory-api-old-2", ready=True, extra_labels={"pod-template-hash": "old111"}),
    ]
    new_pod = _pod(
        "inventory-api-new-1",
        ready=False,
        phase="Running",
        extra_labels={"pod-template-hash": "new222"},
    )

    async def fake_get_deployment():
        return _deployment(desired=3, ready=2, updated=1, available=2)

    async def fake_get_replicasets():
        return [old_rs, new_rs]

    async def fake_get_pods():
        return old_pods + [new_pod]

    monkeypatch.setattr(k8s_client, "get_deployment", fake_get_deployment)
    monkeypatch.setattr(k8s_client, "get_replicasets", fake_get_replicasets)
    monkeypatch.setattr(k8s_client, "get_pods", fake_get_pods)

    resp = client.get("/api/deployment")
    body = resp.json()
    assert body["rolling_out"] is True
    assert body["healthy_old_replicas"] == 2
    assert body["new_replicas"] == 1
    assert body["ready_new_replicas"] == 0
    assert body["reason"] == "Readiness probe failing"
    assert body["service_available"] is True


def test_route_request_proxies_to_ingress_and_reports_pod(monkeypatch):
    async def fake_get(self, url, headers=None, **kwargs):
        assert headers == {"Host": "inventory.local"}
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={"pod": "inventory-api-xyz", "node": "kind-worker2", "namespace": "inventory-prod", "version": "v1.0.0"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    resp = client.post("/api/route-request")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pod"] == "inventory-api-xyz"
    assert body["node"] == "kind-worker2"
    assert "latency_ms" in body


def test_route_request_returns_502_on_upstream_failure(monkeypatch):
    async def fake_get(self, url, headers=None, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    resp = client.post("/api/route-request")
    assert resp.status_code == 502
