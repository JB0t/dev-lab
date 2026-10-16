#!/usr/bin/env bash
# Downloads the CLIs bundled next to devlab (kubectl, helm, linkerd, flux)
# for one architecture, verifying each download against a pinned SHA-256.
# Used by build-distribution.sh, and in a checkout to populate bin/:
#   scripts/fetch-tools.sh x86_64 bin
#
# To bump a tool: change its version, then replace both checksums with the
# values from the upstream checksum files (the script prints a mismatch).

set -euo pipefail

usage() {
  echo "Usage: $0 <x86_64|aarch64> <destination dir>"
  exit 1
}
[[ $# -eq 2 ]] || usage
ARCH="$1"
DEST="$2"
case "$ARCH" in
  x86_64|amd64) GO_ARCH=amd64 ;;
  aarch64|arm64) GO_ARCH=arm64 ;;
  *) usage ;;
esac

KUBECTL_VERSION=v1.28.3
HELM_VERSION=v3.13.1
LINKERD_VERSION=stable-2.14.10
FLUX_VERSION=2.3.0

# sha256 per "<tool>_<go arch>" of the downloaded file
declare -A SHA256=(
  [kubectl_amd64]=0c680c90892c43e5ce708e918821f92445d1d244f9b3d7513023bcae9a6246d1
  [kubectl_arm64]=06511f03e34d8ee350bd55717845e27ebec3116526db7c60092eeb33a475a337
  [helm_amd64]=98c363564d00afd0cc3088e8f830f2a0eeb5f28755b3d8c48df89866374a1ed0
  [helm_arm64]=8c4a0777218b266a7b977394aaf0e9cef30ed2df6e742d683e523d75508d6efe
  [linkerd_amd64]=15cc620084b07e2154d3f299b5c6c4cfdafe947d89355a60221eb98c2cf0b55f
  [linkerd_arm64]=33ff2a414e1078ad3a39f8d5c69fe4b895721f067e45a820bdd16ded560b99ed
  [flux_amd64]=51ef10a0ebf2078e52476c4d168200a1db73feef987e0bc8722f4ce4fcd4b6d9
  [flux_arm64]=29d2363cfdf13546d900986d265f336ed18c6bbb12d0530c624eaa2ff27b547e
)

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$DEST"

# fetch <tool> <url>: download to $WORK_DIR/<tool>.download and verify it
fetch() {
  local tool="$1" url="$2" file="$WORK_DIR/$1.download"
  local expected="${SHA256[${tool}_${GO_ARCH}]}"
  echo "Fetching ${tool} (${GO_ARCH}) from ${url}"
  curl -fsSL --retry 3 -o "$file" "$url"
  local actual
  actual="$(sha256sum "$file" | cut -d' ' -f1)"
  if [[ "$actual" != "$expected" ]]; then
    echo "Error: ${tool} checksum mismatch: expected ${expected}, got ${actual}" >&2
    exit 1
  fi
}

fetch kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${GO_ARCH}/kubectl"
install -m 0755 "$WORK_DIR/kubectl.download" "$DEST/kubectl"

fetch helm "https://get.helm.sh/helm-${HELM_VERSION}-linux-${GO_ARCH}.tar.gz"
tar -xzf "$WORK_DIR/helm.download" -C "$WORK_DIR" "linux-${GO_ARCH}/helm" "linux-${GO_ARCH}/LICENSE"
install -m 0755 "$WORK_DIR/linux-${GO_ARCH}/helm" "$DEST/helm"
# All four tools are Apache-2.0; helm's tarball carries the license text
cp "$WORK_DIR/linux-${GO_ARCH}/LICENSE" "$WORK_DIR/Apache-2.0.txt"

fetch linkerd "https://github.com/linkerd/linkerd2/releases/download/${LINKERD_VERSION}/linkerd2-cli-${LINKERD_VERSION}-linux-${GO_ARCH}"
install -m 0755 "$WORK_DIR/linkerd.download" "$DEST/linkerd"

fetch flux "https://github.com/fluxcd/flux2/releases/download/v${FLUX_VERSION}/flux_${FLUX_VERSION}_linux_${GO_ARCH}.tar.gz"
tar -xzf "$WORK_DIR/flux.download" -C "$WORK_DIR" flux
install -m 0755 "$WORK_DIR/flux" "$DEST/flux"

# Third-party license notice, picked up by build-distribution.sh
cp "$WORK_DIR/Apache-2.0.txt" "$DEST/.Apache-2.0.txt"
cat > "$DEST/.tool-versions" <<EOF
kubectl ${KUBECTL_VERSION}
helm ${HELM_VERSION}
linkerd ${LINKERD_VERSION}
flux v${FLUX_VERSION}
EOF

echo "Tools for ${GO_ARCH} in ${DEST}:"
cat "$DEST/.tool-versions"
