#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
umask 077
: "${HOMELAB_KUBECONFIG:?Namespace-scoped kubeconfig secret required}"
: "${EXPECTED_CONTEXT:?Expected exact context required}"
work=$(mktemp -d); trap 'rm -rf -- "$work"' EXIT
printf '%s\n' "$HOMELAB_KUBECONFIG" > "$work/kubeconfig"
unset HOMELAB_KUBECONFIG
export KUBECONFIG="$work/kubeconfig"
./scripts/deploy-configmap.sh
