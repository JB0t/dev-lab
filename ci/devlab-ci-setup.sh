# Source this in a CI job (POSIX sh) to set up and bootstrap dev-lab.
# Used by ci/devlab.gitlab-ci.yml and ci/run-local.sh.
#
# Inputs (environment):
#   DEVLAB_DIR             dev-lab checkout, inside a directory the Docker daemon shares
#   DEVLAB_CA_CERT         optional path to a root CA file (TLS inspection)
#   DEVLAB_BOOTSTRAP_ARGS  optional extra `devlab bootstrap` flags
#   DEVLAB_SKIP_BOOTSTRAP  set to 1 to stop after setup
# Output: `devlab` on PATH, cluster bootstrapped with DEVLAB_PROFILE (default ci).

# Sourced, so it returns on failure instead of changing the caller's `set -e`.
: "${DEVLAB_DIR:?DEVLAB_DIR must point to the dev-lab checkout}"
export DEVLAB_PROFILE="${DEVLAB_PROFILE:-ci}"

if [ -n "${DEVLAB_CA_CERT:-}" ]; then
  # One certificate per file (update-ca-certificates needs that); CRLF and
  # missing newlines between certificates are tolerated. Tool images and KinD
  # nodes trust the certificates under python/certs.
  mkdir -p "$DEVLAB_DIR/python/certs/ci" || return 1
  tr -d '\r' < "$DEVLAB_CA_CERT" | sed 's/-----END CERTIFICATE-----/&\n/g' | awk -v dir="$DEVLAB_DIR/python/certs/ci" '/-----BEGIN CERTIFICATE-----/ { n++; file = sprintf("%s/devlab-ci-%02d.crt", dir, n) } n { print > file } /-----END CERTIFICATE-----/ { close(file) }' || return 1
  cp "$DEVLAB_DIR"/python/certs/ci/*.crt /usr/local/share/ca-certificates/ || return 1
  update-ca-certificates >/dev/null 2>&1 || return 1
  export PIP_CERT=/etc/ssl/certs/ca-certificates.crt
  export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
fi

# The dind service can start after the job container
echo "Waiting for the Docker daemon at ${DOCKER_HOST:-default}..."
timeout 120 sh -c 'until docker info >/dev/null 2>&1; do sleep 2; done' || {
  echo "Docker daemon not reachable at ${DOCKER_HOST:-default}"; return 1; }

python3 "$DEVLAB_DIR/python/setup.py" >/dev/null || return 1
export PATH="$DEVLAB_DIR/python:$PATH"

if [ "${DEVLAB_SKIP_BOOTSTRAP:-0}" != 1 ]; then
  # shellcheck disable=SC2086  # word splitting of the flags is intended
  devlab bootstrap ${DEVLAB_BOOTSTRAP_ARGS:-} || return 1
fi
