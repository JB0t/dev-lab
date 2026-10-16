#!/usr/bin/env bash
# dev-lab distribution builder (the shape of the veliotech services').
# Creates one tarball per architecture with everything a host needs to run
# the lab and nothing else (no Go source):
#   bin/devlab                     the dev-lab CLI (static Go binary)
#   bin/kubectl helm linkerd flux  bundled CLIs (scripts/fetch-tools.sh)
#   cluster/ config/ clusters/     kind, Helm and Kubernetes config
#   apps/                          sample applications
#   *.md                           README and guides
#   licenses/                      third-party notices
#   manifest.txt                   version, branch, arch, contents
#
# Usage: scripts/build-distribution.sh [--arch all|x86_64|aarch64] [VERSION]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/build"

TARGET_ARCH="all"
VERSION="0.0.0.dev"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)
      TARGET_ARCH="$2"
      shift 2
      ;;
    --help|-h)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      VERSION="$1"
      shift
      ;;
  esac
done
VERSION="${VERSION#v}"

case "$TARGET_ARCH" in
  all|x86_64|aarch64) ;;
  amd64) TARGET_ARCH=x86_64 ;;
  arm64) TARGET_ARCH=aarch64 ;;
  *)
    echo "Error: invalid --arch '$TARGET_ARCH'"
    exit 1
    ;;
esac

# BUILD_BRANCH comes from scripts/ci/build-version.sh (main for a release tag)
BRANCH_NAME="${BUILD_BRANCH:-$(cd "$PROJECT_ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)}"
BRANCH_SLUG="${BRANCH_NAME//\//-}"
PACKAGE_PREFIX="dev-lab_${BRANCH_SLUG}"

# Runtime files copied into every tarball, relative to the repository root
RUNTIME_PATHS=(
  cluster/kind-config.yaml
  cluster/nvkind-config-template.yaml
  cluster/nvkind-values.yaml
  cluster/README.md
  config
  clusters
  apps
  README.md
  DASK-GPU-RUNBOOK.md
  GITOPS-GUIDE.md
  CANARY-DEPLOYMENT-GUIDE.md
  CHANGELOG.md
)

echo "========================================"
echo "dev-lab Distribution Builder"
echo "========================================"
echo "Version: ${VERSION}"
echo "Branch: ${BRANCH_NAME}"
echo "Arch: ${TARGET_ARCH}"
echo ""

mkdir -p "$BUILD_DIR"

# copy_module_licenses <go arch> <dest>: the license files of every module
# linked into bin/devlab, from the module cache
copy_module_licenses() {
  local go_arch="$1" dest="$2" path dir
  while read -r path dir; do
    [[ -n "$dir" ]] || continue
    mkdir -p "$dest/$path"
    find "$dir" -maxdepth 1 -type f \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
      -exec cp {} "$dest/$path/" \;
    if [[ -z "$(ls -A "$dest/$path")" ]]; then
      echo "Error: no license file for Go module $path" >&2
      exit 1
    fi
  done < <(cd "$PROJECT_ROOT" && GOOS=linux GOARCH="$go_arch" CGO_ENABLED=0 go list -deps \
    -f '{{with .Module}}{{if not .Main}}{{.Path}} {{.Dir}}{{end}}{{end}}' ./cmd/devlab | sort -u)
}

create_distribution() {
  local arch="$1" go_arch="$2"
  local staging_dir="$BUILD_DIR/${PACKAGE_PREFIX}_${arch}"
  local archive_name="${PACKAGE_PREFIX}_v${VERSION}_${arch}.tar.gz"

  echo "Creating ${arch} distribution..."
  rm -rf "$staging_dir"
  mkdir -p "$staging_dir/bin" "$staging_dir/licenses"

  (cd "$PROJECT_ROOT" && GOOS=linux GOARCH="$go_arch" CGO_ENABLED=0 go build \
    -trimpath \
    -ldflags "-w -s -X main.version=${VERSION}" \
    -o "$staging_dir/bin/devlab" \
    ./cmd/devlab)

  "$SCRIPT_DIR/fetch-tools.sh" "$arch" "$staging_dir/bin"
  mv "$staging_dir/bin/.Apache-2.0.txt" "$staging_dir/licenses/Apache-2.0.txt"
  mv "$staging_dir/bin/.tool-versions" "$staging_dir/licenses/tool-versions.txt"
  cp "$SCRIPT_DIR/dist/THIRD_PARTY_NOTICES.md" "$staging_dir/licenses/"
  copy_module_licenses "$go_arch" "$staging_dir/licenses/go-modules"

  # Only tracked files, so local scratch (venvs, node_modules, caches) never ships
  (cd "$PROJECT_ROOT" && git ls-files -z -- "${RUNTIME_PATHS[@]}" | tar --null -T - -cf -) |
    tar -xf - -C "$staging_dir"

  local leaked
  leaked="$(cd "$staging_dir" && find . \( -name '*.go' -o -name go.mod -o -name go.sum -o -name '__pycache__' -o -name node_modules \) -print)"
  if [[ -n "$leaked" ]]; then
    echo "Error: files that must not ship:" >&2
    echo "$leaked" >&2
    exit 1
  fi

  cat > "$staging_dir/manifest.txt" <<EOF
service=dev-lab
version=${VERSION}
branch=${BRANCH_NAME}
arch=${arch}
binary=bin/devlab
tools=$(awk '{printf "%s%s=%s", (NR>1?" ":""), $1, $2}' "$staging_dir/licenses/tool-versions.txt")
commit=$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo unknown)
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

  (cd "$BUILD_DIR" && tar -czf "$archive_name" "$(basename "$staging_dir")")
  echo "Created: $BUILD_DIR/$archive_name"
  rm -rf "$staging_dir"
}

if [[ "$TARGET_ARCH" == "all" || "$TARGET_ARCH" == "x86_64" ]]; then
  create_distribution x86_64 amd64
fi
if [[ "$TARGET_ARCH" == "all" || "$TARGET_ARCH" == "aarch64" ]]; then
  create_distribution aarch64 arm64
fi

echo ""
echo "Distribution build complete."
ls -lh "$BUILD_DIR"/*.tar.gz
