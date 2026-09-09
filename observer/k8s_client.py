"""Minimal Kubernetes REST API client using the pod's own ServiceAccount
token. Deliberately not the official kubernetes python client: the observer
only ever does a handful of read-only GETs, so a full client library would be
weight without benefit. This also makes the "what does this pod actually
have permission to do" question answerable by reading four functions instead
of a generated SDK.
"""
import os

import httpx

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
TOKEN_PATH = os.path.join(SA_DIR, "token")
CA_PATH = os.path.join(SA_DIR, "ca.crt")

NAMESPACE = os.getenv("OBSERVER_NAMESPACE", "inventory-prod")
APP_LABEL_SELECTOR = os.getenv("OBSERVER_APP_LABEL_SELECTOR", "app=inventory-api")
DEPLOYMENT_NAME = os.getenv("OBSERVER_DEPLOYMENT_NAME", "inventory-api")
HPA_NAME = os.getenv("OBSERVER_HPA_NAME", "inventory-api")
K8S_REQUEST_TIMEOUT = float(os.getenv("OBSERVER_K8S_TIMEOUT_SECONDS", "5"))


def _api_base() -> str:
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ["KUBERNETES_SERVICE_PORT"]
    return f"https://{host}:{port}"


def _headers() -> dict:
    with open(TOKEN_PATH) as f:
        token = f.read().strip()
    return {"Authorization": f"Bearer {token}"}


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(
        base_url=_api_base(), verify=CA_PATH, timeout=K8S_REQUEST_TIMEOUT
    ) as client:
        resp = await client.get(path, headers=_headers(), params=params or {})
        resp.raise_for_status()
        return resp.json()


async def get_deployment() -> dict:
    return await _get(
        f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{DEPLOYMENT_NAME}"
    )


async def get_hpa() -> dict:
    return await _get(
        f"/apis/autoscaling/v2/namespaces/{NAMESPACE}/horizontalpodautoscalers/{HPA_NAME}"
    )


async def get_pods() -> list[dict]:
    data = await _get(
        f"/api/v1/namespaces/{NAMESPACE}/pods",
        params={"labelSelector": APP_LABEL_SELECTOR},
    )
    return data.get("items", [])


async def get_replicasets() -> list[dict]:
    data = await _get(
        f"/apis/apps/v1/namespaces/{NAMESPACE}/replicasets",
        params={"labelSelector": APP_LABEL_SELECTOR},
    )
    return data.get("items", [])
