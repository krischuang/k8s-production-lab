"""Live RBAC authorization checks against a running cluster.

Uses `kubectl auth can-i --as=<serviceaccount>` -- this asks the real
kube-apiserver to evaluate the actual RBAC decision for that identity, the
same mechanism that authorizes every real request. It is not a simulation
of RBAC; it IS the RBAC authorizer.

Skipped automatically (see conftest.requires_live_cluster) unless kubectl
is pointed at a cluster that actually has the inventory-prod namespace --
this suite must never run against an unrelated/unknown current-context.
"""
import subprocess

import pytest

from conftest import NAMESPACE, requires_live_cluster

pytestmark = [pytest.mark.integration, requires_live_cluster]

INVENTORY_API_SA = f"system:serviceaccount:{NAMESPACE}:inventory-api"
OBSERVER_SA = f"system:serviceaccount:{NAMESPACE}:demo-observer"


def _can_i(as_sa: str, verb: str, resource: str, resource_name: str | None = None) -> bool:
    target = f"{resource}/{resource_name}" if resource_name else resource
    cmd = ["kubectl", "auth", "can-i", verb, target, "-n", NAMESPACE, f"--as={as_sa}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout.strip() == "yes"


# --- Allowed actions succeed -------------------------------------------------

def test_inventory_api_can_get_its_own_configmap():
    assert _can_i(INVENTORY_API_SA, "get", "configmaps", "inventory-api-config") is True


def test_inventory_api_can_get_its_own_secret():
    assert _can_i(INVENTORY_API_SA, "get", "secrets", "inventory-db-credentials") is True


def test_observer_can_list_pods():
    assert _can_i(OBSERVER_SA, "list", "pods") is True


def test_observer_can_get_deployments():
    assert _can_i(OBSERVER_SA, "get", "deployments") is True


# --- Unauthorized actions are denied -----------------------------------------

def test_inventory_api_cannot_list_secrets_namespace_wide():
    """get/watch on one named Secret must not imply list on all Secrets."""
    assert _can_i(INVENTORY_API_SA, "list", "secrets") is False


def test_inventory_api_cannot_delete_its_own_secret():
    assert _can_i(INVENTORY_API_SA, "delete", "secrets", "inventory-db-credentials") is False


def test_inventory_api_cannot_get_unrelated_secret():
    assert _can_i(INVENTORY_API_SA, "get", "secrets", "some-other-secret") is False


def test_inventory_api_cannot_get_pods():
    """inventory-api's Role grants configmap/secret access only -- it must
    not be able to read pod state, which is demo-observer's job."""
    assert _can_i(INVENTORY_API_SA, "get", "pods") is False


def test_observer_cannot_get_secrets():
    assert _can_i(OBSERVER_SA, "get", "secrets", "inventory-db-credentials") is False


def test_observer_cannot_get_configmaps():
    assert _can_i(OBSERVER_SA, "get", "configmaps", "inventory-api-config") is False


def test_observer_cannot_delete_pods():
    assert _can_i(OBSERVER_SA, "delete", "pods") is False


def test_observer_cannot_delete_deployments():
    """The dashboard must never be able to mutate the Deployment it only
    displays -- this is the test for 'the dashboard has no mutation
    controls' being an authorization fact, not just a UI choice."""
    assert _can_i(OBSERVER_SA, "delete", "deployments", "inventory-api") is False


def test_observer_cannot_patch_deployments():
    assert _can_i(OBSERVER_SA, "patch", "deployments", "inventory-api") is False


def test_neither_serviceaccount_has_namespace_wide_wildcard_access():
    for sa in (INVENTORY_API_SA, OBSERVER_SA):
        assert _can_i(sa, "*", "*") is False, f"{sa} must not have cluster/namespace-wide wildcard access"
