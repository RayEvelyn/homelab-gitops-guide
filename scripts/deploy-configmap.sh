#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
: "${KUBECONFIG:?Protected scoped kubeconfig required}"
: "${EXPECTED_CONTEXT:?Expected exact context required}"
[[ ${DEPLOY_NAMESPACE:-demo} == demo ]] || exit 1
kubectl config use-context "$EXPECTED_CONTEXT" >/dev/null
for verb in get create patch; do
 [[ $(kubectl auth can-i "$verb" configmaps --namespace demo) == yes ]] || exit 1
done
if kubectl auth can-i get secrets --namespace demo; then
 echo 'Unexpected Secret-read access; refusing deployment.' >&2; exit 1
fi
kubectl apply --dry-run=server --namespace demo -f examples/manifests/
kubectl apply --namespace demo -f examples/manifests/
kubectl get configmap demo-settings --namespace demo
