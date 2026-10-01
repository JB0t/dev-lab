#!/usr/bin/env bash
# Run the CI profile locally the way a GitLab Kubernetes-executor job runs it:
# a privileged docker:dind "service" container and a job container that share
# one network namespace (like containers in a pod) and a /builds volume.
#
# Usage: ci/run-local.sh [command...]
#   ci/run-local.sh                                   # bootstrap, then devlab status
#   ci/run-local.sh 'devlab addon enable keda node-autoscaler && apps/autoscaling-demo/scripts/test-autoscaling.sh'
#
# Environment:
#   DEVLAB_DIND_IMAGE  dind image (default docker:29-dind; see ci/Dockerfile.dind)
#   KEEP=1             keep the dind container and volume afterwards
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME=devlab-ci-local
DIND_IMAGE="${DEVLAB_DIND_IMAGE:-docker:29-dind}"
JOB_IMAGE=docker:29-cli
COMMAND="${*:-devlab status}"

cleanup() {
  if [ "${KEEP:-0}" = 1 ]; then
    echo "Kept $NAME-dind and volume $NAME-builds (docker rm -f $NAME-dind; docker volume rm $NAME-builds)"
    return
  fi
  docker rm -f "$NAME-dind" >/dev/null 2>&1 || true
  docker volume rm "$NAME-builds" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker rm -f "$NAME-dind" >/dev/null 2>&1 || true
docker volume rm "$NAME-builds" >/dev/null 2>&1 || true
docker volume create "$NAME-builds" >/dev/null

echo "==> Starting the dind service ($DIND_IMAGE)"
docker run -d --privileged --name "$NAME-dind" \
  -e DOCKER_TLS_CERTDIR= -v "$NAME-builds:/builds" \
  "$DIND_IMAGE" --tls=false >/dev/null

echo "==> Copying the working tree into /builds/dev-lab"
# Local state (venv, kubeconfig, Helm and krew state) is left out, like a fresh clone.
# python/certs is included: it is ignored by Git but needed behind TLS inspection.
tar -C "$REPO_ROOT" -cf - \
  --exclude=./.git --exclude=./python/venv --exclude=./python/devlab \
  --exclude=./.kube --exclude=./.helm --exclude=./.krew --exclude='*/__pycache__' . \
  | docker run --rm -i -v "$NAME-builds:/builds" alpine:3.20 \
      sh -c 'mkdir -p /builds/dev-lab && tar -xf - -C /builds/dev-lab'

ca_args=()
if find "$REPO_ROOT/python/certs" -name '*.crt' 2>/dev/null | grep -q .; then
  # One bundle with every local CA, passed like a GitLab file-type variable
  find "$REPO_ROOT/python/certs" -name '*.crt' -exec cat {} + \
    | docker run --rm -i -v "$NAME-builds:/builds" alpine:3.20 sh -c 'cat > /builds/ca-bundle.crt'
  ca_args=(-e DEVLAB_CA_CERT=/builds/ca-bundle.crt)
fi

echo "==> Running the job"
docker run --rm --network "container:$NAME-dind" \
  -v "$NAME-builds:/builds" -w /builds/dev-lab \
  -e CI=true -e CI_PROJECT_DIR=/builds/dev-lab -e DOCKER_HOST=tcp://localhost:2375 \
  -e DEVLAB_PROFILE=ci "${ca_args[@]}" \
  "$JOB_IMAGE" sh -c "
    set -e
    # Same CA step as the first before_script entry in ci/devlab.gitlab-ci.yml
    if [ -n \"\${DEVLAB_CA_CERT:-}\" ]; then
      tr -d '\\r' < \"\$DEVLAB_CA_CERT\" | sed 's/-----END CERTIFICATE-----/&\\n/g' | awk '/-----BEGIN CERTIFICATE-----/ { n++; file = sprintf(\"/usr/local/share/ca-certificates/devlab-ci-%02d.crt\", n) } n { print > file } /-----END CERTIFICATE-----/ { close(file) }'
      update-ca-certificates >/dev/null 2>&1
    fi
    apk add --no-cache bash ca-certificates curl git python3 >/dev/null
    export DEVLAB_DIR=/builds/dev-lab
    . ci/devlab-ci-setup.sh
    $COMMAND
  "
