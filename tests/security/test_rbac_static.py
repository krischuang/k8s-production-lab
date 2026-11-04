"""Static assertions over k8s/rbac.yaml and k8s/observer-rbac.yaml.

These parse the committed manifests directly -- no cluster required -- so
a regression that widens RBAC (a wildcard verb/resource, a ClusterRole, a
write verb creeping into a read-only Role) fails CI immediately instead of
only being caught by manual review of a diff.
"""
from conftest import find_by_name, load_manifests

WRITE_VERBS = {"create", "update", "patch", "delete", "deletecollection"}


def _assert_no_wildcards(role: dict, role_name: str) -> None:
    for i, rule in enumerate(role["rules"]):
        for field in ("verbs", "resources", "apiGroups"):
            values = rule.get(field, [])
            assert "*" not in values, (
                f"{role_name} rule[{i}].{field} contains a wildcard ('*'): {values} -- "
                "least-privilege RBAC must enumerate exact verbs/resources/apiGroups."
            )


def test_inventory_api_role_is_namespaced_not_cluster_scoped():
    docs = load_manifests("rbac.yaml")
    role = find_by_name(docs, "Role", "inventory-api-config-reader")
    assert role["kind"] == "Role", (
        "inventory-api-config-reader must be a Role (namespace-scoped), not a ClusterRole"
    )
    assert role["metadata"]["namespace"] == "inventory-prod"


def test_inventory_api_role_has_no_wildcards():
    docs = load_manifests("rbac.yaml")
    role = find_by_name(docs, "Role", "inventory-api-config-reader")
    _assert_no_wildcards(role, "inventory-api-config-reader")


def test_inventory_api_role_has_no_write_verbs():
    docs = load_manifests("rbac.yaml")
    role = find_by_name(docs, "Role", "inventory-api-config-reader")
    for i, rule in enumerate(role["rules"]):
        granted_writes = WRITE_VERBS & set(rule.get("verbs", []))
        assert not granted_writes, (
            f"inventory-api-config-reader rule[{i}] grants write verb(s) {granted_writes} -- "
            "this Role is documented as read-only (get/watch) config access."
        )


def test_inventory_api_role_restricts_to_named_objects():
    """Every rule must use resourceNames to lock onto one named object --
    otherwise `get`/`watch` on 'secrets' would mean every Secret in the
    namespace, not just inventory-db-credentials."""
    docs = load_manifests("rbac.yaml")
    role = find_by_name(docs, "Role", "inventory-api-config-reader")
    for i, rule in enumerate(role["rules"]):
        resource_names = rule.get("resourceNames", [])
        assert resource_names, (
            f"inventory-api-config-reader rule[{i}] (resources={rule.get('resources')}) has no "
            "resourceNames -- this would grant access to every object of that kind in the "
            "namespace, not a single named ConfigMap/Secret."
        )


def test_inventory_api_rolebinding_targets_correct_serviceaccount():
    docs = load_manifests("rbac.yaml")
    binding = find_by_name(docs, "RoleBinding", "inventory-api-config-reader")
    subjects = binding["subjects"]
    assert len(subjects) == 1
    assert subjects[0] == {
        "kind": "ServiceAccount",
        "name": "inventory-api",
        "namespace": "inventory-prod",
    }


def test_observer_role_is_namespaced_not_cluster_scoped():
    docs = load_manifests("observer-rbac.yaml")
    role = find_by_name(docs, "Role", "demo-observer-read-only")
    assert role["kind"] == "Role"
    assert role["metadata"]["namespace"] == "inventory-prod"


def test_observer_role_has_no_wildcards():
    docs = load_manifests("observer-rbac.yaml")
    role = find_by_name(docs, "Role", "demo-observer-read-only")
    _assert_no_wildcards(role, "demo-observer-read-only")


def test_observer_role_is_strictly_read_only():
    """demo-observer backs a browser-facing dashboard. If this Role ever
    grants a write verb, the dashboard becomes a path to mutate cluster
    state from an unauthenticated HTTP endpoint (README: 'the dashboard has
    no auth of its own') -- this must fail loudly, not be caught by review."""
    docs = load_manifests("observer-rbac.yaml")
    role = find_by_name(docs, "Role", "demo-observer-read-only")
    allowed_verbs = {"get", "list", "watch"}
    for i, rule in enumerate(role["rules"]):
        verbs = set(rule.get("verbs", []))
        disallowed = verbs - allowed_verbs
        assert not disallowed, (
            f"demo-observer-read-only rule[{i}] grants {disallowed}, outside the allowed "
            f"read-only set {allowed_verbs}."
        )


def test_observer_role_does_not_grant_secrets_or_configmaps_access():
    """demo-observer is a separate identity specifically so the dashboard's
    read access never overlaps with inventory-api's credential-bearing
    Role (see k8s/observer-rbac.yaml comment). A rule granting configmaps
    or secrets here would collapse that isolation."""
    docs = load_manifests("observer-rbac.yaml")
    role = find_by_name(docs, "Role", "demo-observer-read-only")
    for i, rule in enumerate(role["rules"]):
        resources = set(rule.get("resources", []))
        assert "secrets" not in resources, f"rule[{i}] must never grant access to secrets"
        assert "configmaps" not in resources, f"rule[{i}] must never grant access to configmaps"


def test_observer_role_limited_to_four_documented_resource_kinds():
    docs = load_manifests("observer-rbac.yaml")
    role = find_by_name(docs, "Role", "demo-observer-read-only")
    seen = {(rule.get("apiGroups", [""])[0], r) for rule in role["rules"] for r in rule.get("resources", [])}
    expected = {
        ("", "pods"),
        ("apps", "deployments"),
        ("apps", "replicasets"),
        ("autoscaling", "horizontalpodautoscalers"),
    }
    assert seen == expected, f"observer Role resource set changed: {seen} != {expected}"


def test_observer_rolebinding_targets_correct_serviceaccount():
    docs = load_manifests("observer-rbac.yaml")
    binding = find_by_name(docs, "RoleBinding", "demo-observer-read-only")
    subjects = binding["subjects"]
    assert len(subjects) == 1
    assert subjects[0] == {
        "kind": "ServiceAccount",
        "name": "demo-observer",
        "namespace": "inventory-prod",
    }


def test_no_clusterrole_or_clusterrolebinding_anywhere():
    """This project's design is explicitly namespace-scoped Roles only
    (README: 'never a ClusterRole'). A ClusterRole appearing in either file
    would silently widen blast radius cluster-wide."""
    for filename in ("rbac.yaml", "observer-rbac.yaml"):
        docs = load_manifests(filename)
        kinds = {doc.get("kind") for doc in docs}
        assert "ClusterRole" not in kinds, f"{filename} must not define a ClusterRole"
        assert "ClusterRoleBinding" not in kinds, f"{filename} must not define a ClusterRoleBinding"
