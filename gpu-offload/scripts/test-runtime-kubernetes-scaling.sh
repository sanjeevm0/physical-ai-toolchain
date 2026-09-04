#!/usr/bin/env bash
# Run the remoter Kubernetes multiinstance scaling integration test
set -o errexit -o nounset

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$SCRIPT_DIR/../.." && pwd))"
# shellcheck source=../../scripts/lib/common.sh
source "$REPO_ROOT/scripts/lib/common.sh"

show_help() {
  cat << EOF
Usage: $(basename "$0") [OPTIONS]

Build and load the remoter scaling test image, install the mutate controller,
and run the Kubernetes scale-up distribution test.

OPTIONS:
    -h, --help               Show this help message
    --context NAME           Kubernetes context override
    --image-loader TYPE      Image loader: auto, containerd, k3s, or kind
    --use-existing-controller
                             Reuse the installed GPU offload mutator
    --config-preview         Print configuration and exit

EXAMPLES:
    $(basename "$0")
    $(basename "$0") --context kubernetes-admin@kubernetes \
      --image-loader containerd --use-existing-controller
EOF
}

config_preview=false
kube_context="${KUBERNETES_TEST_CONTEXT:-}"
image_loader="${KUBERNETES_TEST_IMAGE_LOADER:-auto}"
use_existing_controller="${KUBERNETES_TEST_USE_EXISTING_CONTROLLER:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)                  show_help; exit 0 ;;
    --context)                  kube_context="$2"; shift 2 ;;
    --image-loader)             image_loader="$2"; shift 2 ;;
    --use-existing-controller)  use_existing_controller=true; shift ;;
    --config-preview)           config_preview=true; shift ;;
    *)                          fatal "Unknown option: $1" ;;
  esac
done

require_tools podman kubectl helm uv

cd "$SCRIPT_DIR/.."
eval "$(scripts/detect-platform.sh --export)"
kube_context="${kube_context:-$GPU_OFFLOAD_KUBE_CONTEXT}"
test_image="localhost/remoter-k8s-scaling-test:local"
controller_release="gpu-offload"
controller_namespace="gpu-offload"
case "$(uname -m)" in
  x86_64)        node_arch="amd64" ;;
  aarch64|arm64) node_arch="arm64" ;;
  *)             fatal "Unsupported node architecture: $(uname -m)" ;;
esac

case "$image_loader" in
  auto)
    if [[ "$kube_context" == "$(kubectl config current-context)" ]] &&
      sudo -n ctr --namespace k8s.io images list > /dev/null 2>&1; then
      image_loader="containerd"
    else
      image_loader="$GPU_OFFLOAD_RUNTIME"
    fi
    ;;
  containerd|k3s|kind) ;;
  *) fatal "Invalid image loader: $image_loader" ;;
esac

if [[ "$config_preview" == "true" ]]; then
  section "Configuration Preview"
  print_kv "Kubernetes context" "$kube_context"
  print_kv "Image loader" "$image_loader"
  print_kv "Existing controller" "$use_existing_controller"
  print_kv "Node architecture" "$node_arch"
  print_kv "Test image" "$test_image"
  exit 0
fi

controller_changed=false
controller_existed=false
previous_controller_revision=""
if [[ "$use_existing_controller" != "true" ]]; then
  if helm --kube-context "$kube_context" status "$controller_release" \
    --namespace "$controller_namespace" > /dev/null 2>&1; then
    controller_existed=true
    previous_controller_revision="$(
      helm --kube-context "$kube_context" status "$controller_release" \
        --namespace "$controller_namespace" |
        awk '$1 == "REVISION:" {print $2}'
    )"
    [[ -n "$previous_controller_revision" ]] || fatal "Could not determine the current admission controller revision"
  fi
fi

cleanup_controller() {
  if [[ "$controller_changed" != "true" ]]; then
    return
  fi
  if [[ "$controller_existed" == "true" ]]; then
    if ! helm --kube-context "$kube_context" rollback \
      "$controller_release" "$previous_controller_revision" \
      --namespace "$controller_namespace" \
      --wait \
      --timeout=180s; then
      warn "Failed to restore admission controller revision $previous_controller_revision"
    fi
  elif ! helm --kube-context "$kube_context" uninstall "$controller_release" \
    --namespace "$controller_namespace" \
    --wait; then
    warn "Failed to uninstall the test admission controller"
  fi
}
trap cleanup_controller EXIT

load_test_image() {
  local image="$1"
  local archive
  archive="$(mktemp --suffix=-remoter-k8s-scaling.tar)"
  if ! podman save --output "$archive" "$image"; then
    rm -f "$archive"
    fatal "Failed to export image $image"
  fi
  case "$image_loader" in
    containerd)
      if ! sudo -n ctr --namespace k8s.io images import "$archive"; then
        rm -f "$archive"
        fatal "Failed to import $image into containerd"
      fi
      ;;
    k3s)
      if ! sudo -n k3s ctr images import "$archive"; then
        rm -f "$archive"
        fatal "Failed to import $image into k3s"
      fi
      ;;
    kind)
      if ! KIND_EXPERIMENTAL_PROVIDER=podman kind load image-archive "$archive" \
        --name "${kube_context#kind-}"; then
        rm -f "$archive"
        fatal "Failed to import $image into kind"
      fi
      ;;
  esac
  rm -f "$archive"
}

section "Build Test Images"
if [[ "$use_existing_controller" != "true" ]]; then
  scripts/build-controller-image.sh
fi
scripts/build-runtime-image.sh
build_args=(--build-arg "REMOTER_IMAGE=localhost/pyremote:local")
if [[ -n "${UV_INDEX_URL:-}" ]]; then
  build_args+=(--build-arg "UV_INDEX_URL=$UV_INDEX_URL")
fi
podman build "${build_args[@]}" \
  --file runtime/tests/kubernetes/Containerfile \
  --tag "$test_image" \
  .

section "Load Test Images"
if [[ "$use_existing_controller" != "true" ]]; then
  load_test_image localhost/xavier-mutate:local
fi
load_test_image "$test_image"

section "Install Admission Controller"
if [[ "$use_existing_controller" == "true" ]]; then
  webhook_count="$(
    kubectl --context "$kube_context" get mutatingwebhookconfigurations \
      --output=jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
      grep -c 'gpu-offload-mutate' || true
  )"
  [[ "$webhook_count" -gt 0 ]] || fatal "No installed GPU offload mutator was found"
  info "Using the existing GPU offload mutator"
else
  controller_changed=true
  helm --kube-context "$kube_context" upgrade --install "$controller_release" helm/gpu-offload \
    --namespace "$controller_namespace" \
    --create-namespace \
    --wait \
    --timeout=180s \
    --set image.registry=localhost \
    --set mutate.image.repository=xavier-mutate \
    --set mutate.image.tag=local \
    --set image.pullPolicy=Never \
    --set "mutateScheduling.nodeSelector.kubernetes\\.io/arch=$node_arch"
  kubectl --context "$kube_context" rollout restart deployment/gpu-offload-mutate \
    --namespace "$controller_namespace"
  kubectl --context "$kube_context" rollout status deployment/gpu-offload-mutate \
    --namespace "$controller_namespace" \
    --timeout=180s
fi

section "Run Kubernetes Scaling Test"
RUN_KUBERNETES_TESTS=true \
KUBERNETES_TEST_CONTEXT="$kube_context" \
  uv run --project runtime --extra test pytest \
    -c runtime/pyproject.toml \
    runtime/tests/test_remoter_kubernetes.py \
    -q -s

section "Deployment Summary"
print_kv "Kubernetes context" "$kube_context"
print_kv "Image loader" "$image_loader"
print_kv "Existing controller" "$use_existing_controller"
print_kv "Test image" "$test_image"
info "Kubernetes multiinstance scaling test passed"
