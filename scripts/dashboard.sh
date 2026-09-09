#!/usr/bin/env bash
# Opens the live demo dashboard. Uses kubectl port-forward rather than the
# Ingress: it's the simplest thing that reliably works for a screen-share
# (no /etc/hosts edits, no custom Host headers), and it doesn't require
# punching an inbound hole in default-deny-all just to view a dashboard --
# see k8s/observer-networkpolicy.yaml for why that trade-off was made.
set -euo pipefail

NAMESPACE="inventory-prod"
PORT="${1:-8090}"

echo "==> Port-forwarding svc/demo-observer to http://localhost:${PORT}"
echo "    Ctrl-C to stop."
echo

if command -v open >/dev/null 2>&1; then
  ( sleep 1.5 && open "http://localhost:${PORT}/" ) &
fi

kubectl -n "${NAMESPACE}" port-forward svc/demo-observer "${PORT}:80"
