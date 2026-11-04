"""Live NetworkPolicy enforcement checks against a running cluster.

This automates the manual test documented in README.md ("NetworkPolicy"
section): a throwaway pod with no matching labels, in the same namespace,
trying to reach inventory-api directly. Previously that was a one-off
`kubectl run` transcript pasted into the README; here it is a repeatable,
deterministic, CI-runnable-against-a-real-cluster check with pass/fail
assertions instead of a human reading curl's exit code.

Skipped automatically (see conftest.requires_live_cluster) unless kubectl
is pointed at a cluster that actually has the inventory-prod namespace.
"""
import subprocess

import pytest

from conftest import NAMESPACE, requires_live_cluster

pytestmark = [pytest.mark.integration, requires_live_cluster]

CURL_IMAGE = "curlimages/curl"
TARGET_URL = f"http://inventory-api.{NAMESPACE}.svc.cluster.local/health/live"


def _run_curl_pod(pod_name: str, extra_labels: dict[str, str] | None, timeout: int) -> subprocess.CompletedProcess:
    cmd = [
        "kubectl", "run", pod_name,
        "--rm", "--attach", "--restart=Never",
        f"--image={CURL_IMAGE}",
        "-n", NAMESPACE,
    ]
    if extra_labels:
        for k, v in extra_labels.items():
            cmd += ["--labels", f"{k}={v}"]
    cmd += ["--", "curl", "-sf", "--max-time", "5", TARGET_URL]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def test_unlabeled_pod_in_same_namespace_cannot_reach_api_directly():
    """No label matches `allow-ingress-from-nginx`'s podSelector or
    namespaceSelector, so default-deny-all must block this -- curl should
    time out (non-zero exit), not succeed."""
    result = _run_curl_pod("netpol-test-denied", extra_labels=None, timeout=30)
    assert result.returncode != 0, (
        "an unlabeled pod reached inventory-api directly -- default-deny-all / "
        "allow-ingress-from-nginx is not being enforced"
    )


def test_pod_labeled_as_ingress_nginx_app_still_blocked_without_matching_namespace():
    """allow-ingress-from-nginx matches on namespaceSelector
    (kubernetes.io/metadata.name: ingress-nginx), not a pod label -- a pod
    inside inventory-prod cannot forge its way in by copying the
    `app: inventory-api` label onto itself, because that label is the
    podSelector for the *target* of the policy, not a credential."""
    result = _run_curl_pod(
        "netpol-test-spoofed-label", extra_labels={"app": "ingress-nginx"}, timeout=30
    )
    assert result.returncode != 0, (
        "a pod spoofing an ingress-nginx-like label from inside inventory-prod reached the "
        "API -- the policy is matching on pod labels when it should require the "
        "ingress-nginx namespace"
    )


def test_api_pod_itself_can_still_resolve_and_serve_health_check():
    """Positive control for the two negative tests above: if this fails too,
    the negative results are meaningless (could be a DNS outage, not
    NetworkPolicy). Runs the same health check the Service's own readiness
    probe relies on, via `kubectl exec` into a running inventory-api pod --
    exercising the loopback path, which NetworkPolicy never restricts."""
    get_pod = subprocess.run(
        ["kubectl", "get", "pods", "-n", NAMESPACE, "-l", "app=inventory-api",
         "-o", "jsonpath={.items[0].metadata.name}"],
        capture_output=True, text=True, timeout=10,
    )
    pod_name = get_pod.stdout.strip()
    assert pod_name, "no inventory-api pod found -- is the stack deployed? (scripts/deploy.sh)"

    result = subprocess.run(
        ["kubectl", "exec", "-n", NAMESPACE, pod_name, "--",
         "python", "-c",
         "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=5)"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, (
        f"inventory-api pod {pod_name} could not serve its own health check locally -- "
        f"stderr: {result.stderr}"
    )
