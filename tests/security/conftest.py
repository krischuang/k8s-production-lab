"""Shared helpers for the security test suite.

Static tests (test_rbac_static.py, test_networkpolicy_static.py) parse the
committed YAML directly and need no cluster -- they run in CI.

Live tests (test_rbac_live.py, test_networkpolicy_live.py) exercise real
authorization decisions against a running cluster and are skipped
automatically when no cluster matching this project is reachable, rather
than failing or silently touching whatever context happens to be current.
"""
import pathlib
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
K8S_DIR = REPO_ROOT / "k8s"
NAMESPACE = "inventory-prod"


def load_manifests(filename: str) -> list[dict]:
    """Parse a multi-document manifest file, dropping empty documents."""
    text = (K8S_DIR / filename).read_text()
    return [doc for doc in yaml.safe_load_all(text) if doc]


def find_by_name(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"{kind} '{name}' not found in manifest set")


def _cluster_matches_this_project() -> bool:
    """True only if kubectl is configured against a cluster that actually
    has this project's namespace -- never run live checks against an
    arbitrary/unknown current-context."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "namespace", NAMESPACE, "-o", "jsonpath={.metadata.name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == NAMESPACE


requires_live_cluster = pytest.mark.skipif(
    not _cluster_matches_this_project(),
    reason=(
        f"no reachable cluster with namespace '{NAMESPACE}' -- run "
        "./scripts/setup-cluster.sh && ./scripts/deploy.sh first"
    ),
)
