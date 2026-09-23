#!/usr/bin/env bash
# Autoscaling scenario tests for the dev-lab cluster.
#
# Requires: devlab addon enable keda node-autoscaler
#
# Usage: test-autoscaling.sh [queue|burst|limits|all]   (default: all)
#
#   queue   KEDA scales a real consumer from 0 on Redis list length, drains
#           the queue, and scales back to 0
#   burst   KEDA scales pods that only fit on KWOK nodes; cluster-autoscaler
#           adds nodes for the Pending pods, then removes them once idle
#   limits  More pods than the kwok-small pool (max 5 nodes) can hold; the
#           pool stops at its max size and the rest stay Pending
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEVLAB="${DEVLAB:-$REPO_ROOT/python/devlab}"
NAMESPACE=autoscaling-demo
cd "$REPO_ROOT"  # devlab kubectl mounts the current directory as /workspace

kubectl() { "$DEVLAB" kubectl "$@"; }
redis() { kubectl -n "$NAMESPACE" exec deploy/redis -- redis-cli "$@"; }
log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
pass() { printf '\033[1;32mPASS\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mFAIL\033[0m %s\n' "$*"; exit 1; }

# wait_for <description> <timeout seconds> <command...>
wait_for() {
  local description=$1 timeout=$2 start=$SECONDS
  shift 2
  printf '    waiting for %s ' "$description"
  until "$@"; do
    if (( SECONDS - start >= timeout )); then
      printf '\n'
      fail "$description (timed out after ${timeout}s)"
    fi
    printf '.'
    sleep 5
  done
  printf ' %ss\n' "$(( SECONDS - start ))"
}

ready_replicas() {
  local ready
  ready=$(kubectl -n "$NAMESPACE" get deployment "$1" -o jsonpath='{.status.readyReplicas}')
  echo "${ready:-0}"
}
pod_count() {  # <app label> <phase>
  kubectl -n "$NAMESPACE" get pods -l "app=$1" --field-selector="status.phase=$2" --no-headers 2>/dev/null | wc -l
}
kwok_nodes() {
  kubectl get nodes -l devlab.io/node-pool=kwok --no-headers 2>/dev/null | wc -l
}
list_length() { redis --raw LLEN "$1" | tr -d '\r'; }

# Predicates for wait_for
replicas_at_least() { (( $(ready_replicas "$1") >= $2 )); }
running_at_least() { (( $(pod_count "$1" Running) >= $2 )); }
no_pods() { [ -z "$(kubectl -n "$NAMESPACE" get pods -l "app=$1" --no-headers 2>/dev/null)" ]; }
list_empty() { [ "$(list_length "$1")" = 0 ]; }
no_kwok_nodes() { [ "$(kwok_nodes)" -eq 0 ]; }

check_prerequisites() {
  kubectl get crd scaledobjects.keda.sh >/dev/null 2>&1 \
    || fail "KEDA is not installed: run 'devlab addon enable keda'"
  kubectl -n kube-system get deployment cluster-autoscaler >/dev/null 2>&1 \
    || fail "cluster-autoscaler is not installed: run 'devlab addon enable node-autoscaler'"
  log "Deploying the autoscaling demo"
  kubectl apply -k apps/autoscaling-demo/k8s
  kubectl -n "$NAMESPACE" rollout status deployment/redis --timeout=120s
}

scenario_queue() {
  log "Scenario queue: KEDA scales a real consumer on queue length"
  redis DEL jobs >/dev/null
  redis RPUSH jobs $(seq 1 60) >/dev/null
  echo "    queued 60 jobs (target: 5 jobs per replica, max 10 replicas)"
  wait_for "consumer to scale out to at least 5 replicas" 120 replicas_at_least queue-consumer 5
  pass "scaled out to $(ready_replicas queue-consumer) replicas"
  wait_for "queue to drain" 240 list_empty jobs
  wait_for "consumer to scale back to 0" 180 no_pods queue-consumer
  pass "queue drained and consumer scaled to zero"
}

scenario_burst() {
  log "Scenario burst: KEDA adds pods, cluster-autoscaler adds KWOK nodes"
  local start_nodes
  start_nodes=$(kwok_nodes)
  redis DEL burst >/dev/null
  redis RPUSH burst $(seq 1 6) >/dev/null
  echo "    queued 6 items (1 pod each, 2 pods fit per kwok-small node)"
  wait_for "6 burst pods Running on new KWOK nodes" 240 running_at_least burst-workers 6
  pass "6 pods Running on $(kwok_nodes) KWOK nodes (was $start_nodes)"
  (( $(kwok_nodes) >= 3 )) || fail "expected at least 3 KWOK nodes"

  redis DEL burst >/dev/null
  echo "    emptied the list"
  wait_for "burst workers to scale to 0" 180 no_pods burst-workers
  pass "burst workers scaled to zero"
  wait_for "cluster-autoscaler to remove the idle KWOK nodes" 420 no_kwok_nodes
  pass "idle KWOK nodes removed"
}

scenario_limits() {
  log "Scenario limits: demand beyond the node pool's max size"
  redis DEL burst >/dev/null
  redis RPUSH burst $(seq 1 14) >/dev/null
  echo "    queued 14 items; kwok-small max is 5 nodes x 2 pods = 10"
  wait_for "pool to reach 5 nodes with 10 pods Running" 300 running_at_least burst-workers 10
  sleep 20  # give cluster-autoscaler a few more loops to (not) scale further
  local nodes pending
  nodes=$(kwok_nodes)
  pending=$(pod_count burst-workers Pending)
  [ "$nodes" -eq 5 ] || fail "expected the pool to stop at 5 nodes, found $nodes"
  [ "$pending" -eq 4 ] || fail "expected 4 Pending pods, found $pending"
  pass "pool capped at $nodes nodes, $pending pods left Pending"
  echo "    cluster-autoscaler events for the Pending pods:"
  kubectl -n "$NAMESPACE" get events --field-selector reason=NotTriggerScaleUp \
    -o custom-columns=MESSAGE:.message --no-headers | sort -u | head -3 | sed 's/^/      /'

  redis DEL burst >/dev/null
  wait_for "cluster-autoscaler to remove the idle KWOK nodes" 420 no_kwok_nodes
  pass "pool scaled back to 0 nodes"
}

scenario=${1:-all}
check_prerequisites
case "$scenario" in
  queue) scenario_queue ;;
  burst) scenario_burst ;;
  limits) scenario_limits ;;
  all) scenario_queue; scenario_burst; scenario_limits ;;
  *) fail "unknown scenario '$scenario' (queue|burst|limits|all)" ;;
esac
log "All requested scenarios passed"
