"""Static assertions over k8s/networkpolicy.yaml and
k8s/observer-networkpolicy.yaml.

No cluster required. The point is to catch the specific regression that
makes a NetworkPolicy silently permissive: an empty `from`/`to` selector
(which Kubernetes treats as "allow everyone"), a dropped default-deny, or
a widened podSelector/namespaceSelector.
"""
from conftest import find_by_name, load_manifests


def _assert_selector_entries_are_scoped(entries: list[dict], context: str) -> None:
    """A `from`/`to` list entry with no podSelector/namespaceSelector/ipBlock
    key at all would match every source/destination -- this must never
    appear in a policy that claims to be narrow."""
    for i, entry in enumerate(entries):
        has_selector = any(k in entry for k in ("podSelector", "namespaceSelector", "ipBlock"))
        assert has_selector, f"{context}[{i}] has no selector -- this would allow traffic from/to anywhere"
        if "ipBlock" in entry:
            cidr = entry["ipBlock"].get("cidr", "")
            assert cidr != "0.0.0.0/0", f"{context}[{i}] ipBlock allows the entire internet (0.0.0.0/0)"


def test_default_deny_all_covers_both_directions_with_no_exceptions():
    docs = load_manifests("networkpolicy.yaml")
    policy = find_by_name(docs, "NetworkPolicy", "default-deny-all")
    spec = policy["spec"]
    assert spec["podSelector"] == {}, "default-deny-all must select every pod in the namespace"
    assert set(spec["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in spec, "default-deny-all must not carry any allow rules of its own"
    assert "egress" not in spec, "default-deny-all must not carry any allow rules of its own"


def test_allow_ingress_from_nginx_is_scoped_to_ingress_namespace_and_app_port():
    docs = load_manifests("networkpolicy.yaml")
    policy = find_by_name(docs, "NetworkPolicy", "allow-ingress-from-nginx")
    spec = policy["spec"]
    assert spec["podSelector"] == {"matchLabels": {"app": "inventory-api"}}
    assert spec["policyTypes"] == ["Ingress"]

    rule = spec["ingress"][0]
    _assert_selector_entries_are_scoped(rule["from"], "allow-ingress-from-nginx.ingress[0].from")
    assert rule["from"] == [
        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}
    ]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8000}]


def test_dns_egress_is_scoped_to_kube_system_on_port_53_only():
    docs = load_manifests("networkpolicy.yaml")
    policy = find_by_name(docs, "NetworkPolicy", "allow-dns-egress")
    rule = policy["spec"]["egress"][0]
    _assert_selector_entries_are_scoped(rule["to"], "allow-dns-egress.egress[0].to")
    ports = {(p["protocol"], p["port"]) for p in rule["ports"]}
    assert ports == {("UDP", 53), ("TCP", 53)}


def test_postgres_reachable_only_from_api_pods_not_namespace_wide():
    docs = load_manifests("networkpolicy.yaml")

    egress_policy = find_by_name(docs, "NetworkPolicy", "allow-api-egress-to-postgres")
    egress_rule = egress_policy["spec"]["egress"][0]
    _assert_selector_entries_are_scoped(egress_rule["to"], "allow-api-egress-to-postgres.egress[0].to")
    assert egress_rule["to"] == [{"podSelector": {"matchLabels": {"app": "postgres"}}}]
    assert egress_rule["ports"] == [{"protocol": "TCP", "port": 5432}]

    ingress_policy = find_by_name(docs, "NetworkPolicy", "allow-postgres-ingress-from-api")
    ingress_rule = ingress_policy["spec"]["ingress"][0]
    _assert_selector_entries_are_scoped(ingress_rule["from"], "allow-postgres-ingress-from-api.ingress[0].from")
    assert ingress_rule["from"] == [{"podSelector": {"matchLabels": {"app": "inventory-api"}}}]
    assert ingress_rule["ports"] == [{"protocol": "TCP", "port": 5432}]


def test_observer_egress_is_scoped_to_ingress_namespace_port_80_only():
    docs = load_manifests("observer-networkpolicy.yaml")
    policy = find_by_name(docs, "NetworkPolicy", "allow-observer-egress-to-ingress")
    spec = policy["spec"]
    assert spec["podSelector"] == {"matchLabels": {"app": "demo-observer"}}
    assert spec["policyTypes"] == ["Egress"]

    rule = spec["egress"][0]
    _assert_selector_entries_are_scoped(rule["to"], "allow-observer-egress-to-ingress.egress[0].to")
    assert rule["to"] == [
        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}
    ]
    assert rule["ports"] == [{"protocol": "TCP", "port": 80}]


def test_observer_networkpolicy_grants_no_ingress_rule():
    """README: 'Deliberately absent: any ingress rule for demo-observer' --
    the dashboard is reached via kubectl port-forward, not pod-to-pod
    traffic, so no inbound hole should exist in this file."""
    docs = load_manifests("observer-networkpolicy.yaml")
    policy = find_by_name(docs, "NetworkPolicy", "allow-observer-egress-to-ingress")
    assert "Ingress" not in policy["spec"]["policyTypes"]
    assert "ingress" not in policy["spec"]


def test_no_policy_allows_from_or_to_everywhere():
    """Cross-check every policy in both files: an entry present but with an
    empty list (`from: []` or omitted selectors) is a common way a 'narrow'
    policy regresses into allow-all without anyone noticing in review."""
    for filename in ("networkpolicy.yaml", "observer-networkpolicy.yaml"):
        for policy in load_manifests(filename):
            if policy.get("kind") != "NetworkPolicy":
                continue
            name = policy["metadata"]["name"]
            for direction, key in (("ingress", "from"), ("egress", "to")):
                for rule in policy["spec"].get(direction, []):
                    entries = rule.get(key)
                    assert entries, f"{name}.{direction} rule has no '{key}' selector list -- allows everyone"
                    _assert_selector_entries_are_scoped(entries, f"{name}.{direction}[].{key}")
