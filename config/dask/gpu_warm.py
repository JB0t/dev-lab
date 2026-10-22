"""Warm a GPU node pool: scale it to N nodes and pull the worker image on each.

A cold node costs a job minutes: the cluster autoscaler adds the VM, the GPU
driver and device plugin start, then the first worker pulls a multi-GB image.
Jobs measured on a cold pool time all of that. `up` does it beforehand:

    python3 config/dask/gpu_warm.py up --nodes 4 \\
      --node-selector agentpool=t4 --toleration sku=gpu:NoSchedule \\
      --image myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1 \\
      --dask-autoscaler gpu            # optional: also start the 4 Dask workers

It applies a Deployment of N tiny pods, one per node (required pod
anti-affinity), each running the image (`sleep`; a few millicores and MiB), so
the autoscaler adds nodes until there are N and every node pulls the image at
once. It waits until every pod is on a node with the image pulled and the node
advertises its GPU, printing each node as it comes up. The pods then stay: the
autoscaler cannot remove a node whose pod cannot move elsewhere, so the pool
stays at N, image cached, until `down`. They request no GPU, so workers still
fit beside them.

With --dask-autoscaler NAME, the DaskAutoscaler's minimum is raised to N as
well, so N workers start, connect to the scheduler and wait; `up` then also
waits for them. `down` puts the minimum back.

    python3 config/dask/gpu_warm.py status
    python3 config/dask/gpu_warm.py down      # pool scales down after the autoscaler's unneeded time

Only kubectl is needed (any context: --context). The image must have `sh`;
without it the pod crash-loops, but the image is still pulled and counted.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from devlab_dask import IMAGE, parse_selector, parse_tolerations  # noqa: E402

WARM_LABEL = "devlab.io/warm"
ANNOTATION_AUTOSCALER = "devlab.io/dask-autoscaler"
ANNOTATION_MINIMUM = "devlab.io/dask-autoscaler-minimum"
# Sleeps until stopped; exits at once on SIGTERM so `down` is quick
HOLD = "trap 'exit 0' TERM INT; while true; do sleep 3600 & wait $!; done"
ZONE_LABEL = "topology.kubernetes.io/zone"


def parse_duration(text: str) -> float:
    """``90``, ``90s``, ``5m``, ``1h`` or ``1h30m`` as seconds"""
    text = str(text).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = re.findall(r"(\d+(?:\.\d+)?)([hms])", text)
    if not parts or "".join(number + unit for number, unit in parts) != text:
        raise ValueError(f"not a duration: {text!r} (e.g. 90s, 5m, 1h)")
    return sum(float(number) * {"h": 3600, "m": 60, "s": 1}[unit] for number, unit in parts)


def clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds < 3600 else \
        f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def warm_deployment(name: str, namespace: str, nodes: int, images: List[str],
                    node_selector: Optional[Dict[str, str]], tolerations: Optional[List[dict]],
                    annotations: Optional[Dict[str, str]] = None) -> dict:
    """N pods, one per node, each running every image"""
    labels = {WARM_LABEL: name}
    pod_spec = {
        "affinity": {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
            {"labelSelector": {"matchLabels": labels}, "topologyKey": "kubernetes.io/hostname"},
        ]}},
        "terminationGracePeriodSeconds": 1,
        "automountServiceAccountToken": False,
        "containers": [{
            "name": f"image-{index}",
            "image": image,
            # The workers use IfNotPresent too, so they start from this copy
            "imagePullPolicy": "IfNotPresent",
            "command": ["sh", "-c", HOLD],
            "resources": {"requests": {"cpu": "1m", "memory": "4Mi"}, "limits": {"memory": "32Mi"}},
        } for index, image in enumerate(images)],
    }
    if node_selector:
        pod_spec["nodeSelector"] = dict(node_selector)
    if tolerations:
        pod_spec["tolerations"] = list(tolerations)
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace,
                     "labels": {**labels, "app.kubernetes.io/name": "gpu-warm"},
                     "annotations": dict(annotations or {})},
        "spec": {
            "replicas": nodes,
            "selector": {"matchLabels": labels},
            # A rolling update would need a node free of the old pods (anti-affinity),
            # i.e. one more node than N; replace them in place instead
            "strategy": {"type": "Recreate"},
            "template": {
                "metadata": {
                    "labels": labels,
                    # Belt and braces: the autoscaler never removes a node for these pods
                    "annotations": {"cluster-autoscaler.kubernetes.io/safe-to-evict": "false"},
                },
                "spec": pod_spec,
            },
        },
    }


class Kubectl:
    def __init__(self, context: Optional[str] = None):
        self.base = ["kubectl"] + (["--context", context] if context else [])

    def run(self, args: List[str], input_text: Optional[str] = None, check: bool = True) -> str:
        result = subprocess.run(self.base + args, input=input_text, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"kubectl {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout

    def json(self, args: List[str], check: bool = True) -> Optional[dict]:
        out = self.run(args + ["-o", "json"], check=check)
        return json.loads(out) if out.strip() else None


def pulled_seconds(message: str) -> Optional[str]:
    """The pull time of a kubelet Pulled event, or 'cached' when the image was already there"""
    if "already present" in message:
        return "cached"
    match = re.search(r'Successfully pulled image ".*?" in ((?:\d+h)?(?:\d+m)?[\d.]+(?:ms|s))', message)
    return match.group(1) if match else None


def pod_state(pod: dict, nodes: Dict[str, dict], gpu_resource: Optional[str]) -> dict:
    """Where a warm pod is: scheduled, image pulled, node GPU advertised"""
    statuses = pod.get("status", {}).get("containerStatuses") or []
    containers = pod["spec"]["containers"]
    node_name = pod["spec"].get("nodeName")
    node = nodes.get(node_name) if node_name else None
    gpus = None
    if node is not None and gpu_resource:
        gpus = node.get("status", {}).get("allocatable", {}).get(gpu_resource)
    return {
        "pod": pod["metadata"]["name"],
        "node": node_name,
        "zone": (node or {}).get("metadata", {}).get("labels", {}).get(ZONE_LABEL, ""),
        "pulled": len(statuses) == len(containers) and all(status.get("imageID") for status in statuses),
        "gpus": gpus,
        "gpu_ready": gpu_resource is None or (gpus not in (None, "", "0")),
    }


def pending_reasons(kubectl: Kubectl, namespace: str, pod_names: List[str]) -> List[str]:
    """Latest scheduling and scale-up messages of pods without a node"""
    events = kubectl.json(["get", "events", "-n", namespace], check=False) or {"items": []}
    latest = {}
    for event in events["items"]:
        involved = event.get("involvedObject", {})
        if involved.get("name") in pod_names and event.get("reason") in (
                "FailedScheduling", "NotTriggerScaleUp", "TriggeredScaleUp", "FailedCreate"):
            stamp = event.get("lastTimestamp") or event.get("eventTime") or ""
            key = event["reason"]
            if key not in latest or stamp >= latest[key][0]:
                latest[key] = (stamp, event.get("message", "").strip())
    return [f"{reason}: {message}" for reason, (_, message) in sorted(latest.items())]


def pull_times(kubectl: Kubectl, namespace: str) -> Dict[str, str]:
    """Pod name to the pull time of its Pulled events (the longest when several images)"""
    events = kubectl.json(["get", "events", "-n", namespace, "--field-selector", "reason=Pulled"],
                          check=False) or {"items": []}
    times = {}
    for event in events["items"]:
        pod = event.get("involvedObject", {}).get("name")
        seconds = pulled_seconds(event.get("message", ""))
        if pod and seconds and (pod not in times or times[pod] == "cached"):
            times[pod] = seconds
    return times


def dask_workers_ready(kubectl: Kubectl, namespace: str, cluster: str) -> int:
    pods = kubectl.json(["get", "pods", "-n", namespace, "-l",
                         f"dask.org/cluster-name={cluster},dask.org/component=worker"], check=False) or {"items": []}
    ready = 0
    for pod in pods["items"]:
        if pod["metadata"].get("deletionTimestamp"):
            continue  # terminating, e.g. from an earlier scale-down
        conditions = pod.get("status", {}).get("conditions") or []
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            ready += 1
    return ready


def wait_warm(kubectl: Kubectl, name: str, namespace: str, nodes_wanted: int, node_selector: Optional[Dict[str, str]],
              gpu_resource: Optional[str], timeout: float, dask_cluster: Optional[str] = None,
              dask_workers: int = 0, interval: float = 5.0) -> bool:
    start = time.monotonic()
    reported = set()
    last_line = None
    selector_arg = ",".join(f"{k}={v}" for k, v in (node_selector or {}).items())
    while True:
        pods = kubectl.json(["get", "pods", "-n", namespace, "-l", f"{WARM_LABEL}={name}"])["items"]
        pods = [pod for pod in pods if not pod["metadata"].get("deletionTimestamp")]
        node_args = ["get", "nodes"] + (["-l", selector_arg] if selector_arg else [])
        nodes = {node["metadata"]["name"]: node for node in kubectl.json(node_args)["items"]}
        states = [pod_state(pod, nodes, gpu_resource) for pod in pods]
        times = pull_times(kubectl, namespace) if any(s["pulled"] and s["pod"] not in reported for s in states) else {}
        elapsed = time.monotonic() - start
        for state in states:
            if state["pulled"] and state["gpu_ready"] and state["pod"] not in reported:
                reported.add(state["pod"])
                pulled = times.get(state["pod"])
                pull_text = "image already cached" if pulled == "cached" else \
                    f"image pulled in {pulled}" if pulled else "image pulled"
                gpu_text = f", {gpu_resource} {state['gpus']}" if gpu_resource else ""
                zone = f" ({state['zone']})" if state["zone"] else ""
                print(f"  {clock(elapsed):>6}  {state['node']}{zone}: {pull_text}{gpu_text}", flush=True)
        scheduled = sum(1 for s in states if s["node"])
        pulled = sum(1 for s in states if s["pulled"])
        gpu_ready = sum(1 for s in states if s["node"] and s["gpu_ready"])
        workers = dask_workers_ready(kubectl, namespace, dask_cluster) if dask_cluster else 0
        line = f"nodes {scheduled}/{nodes_wanted}, images {pulled}/{nodes_wanted}"
        if gpu_resource:
            line += f", GPUs {gpu_ready}/{nodes_wanted}"
        if dask_cluster:
            line += f", Dask workers {workers}/{dask_workers}"
        if line != last_line:
            print(f"  {clock(elapsed):>6}  {line}", flush=True)
            last_line = line
        done = len(reported) >= nodes_wanted and (not dask_cluster or workers >= dask_workers)
        if done:
            print(f"Warm after {clock(elapsed)}: {nodes_wanted} nodes with the image"
                  + (f" and {gpu_resource}" if gpu_resource else "")
                  + (f", {workers} Dask workers ready" if dask_cluster else "")
                  + f". They stay until `{os.path.basename(sys.argv[0])} down`.", flush=True)
            return True
        if elapsed > timeout:
            waiting = [s["pod"] for s in states if not s["node"]]
            print(f"Not warm after {clock(elapsed)}: {line}. The pods stay and keep trying; "
                  f"`down` removes them.", flush=True)
            for reason in pending_reasons(kubectl, namespace, waiting):
                print(f"  {reason}", flush=True)
            for state in states:
                if state["node"] and not state["pulled"]:
                    print(f"  {state['pod']} on {state['node']}: image not pulled yet "
                          f"(kubectl -n {namespace} describe pod {state['pod']})", flush=True)
                elif state["node"] and not state["gpu_ready"]:
                    print(f"  {state['node']}: no {gpu_resource} allocatable yet (device plugin?)", flush=True)
            return False
        time.sleep(interval)


def set_autoscaler_minimum(kubectl: Kubectl, namespace: str, name: str, minimum: int) -> None:
    kubectl.run(["patch", "daskautoscaler", name, "-n", namespace, "--type", "merge",
                 "-p", json.dumps({"spec": {"minimum": minimum}})])


def cmd_up(args, kubectl: Kubectl) -> int:
    images = args.image or [IMAGE]
    gpu_resource = None if args.gpu_resource.lower() == "none" else args.gpu_resource
    annotations = {}
    dask_cluster = None
    dask_workers = 0
    if args.dask_autoscaler:
        autoscaler = kubectl.json(["get", "daskautoscaler", args.dask_autoscaler, "-n", args.namespace])
        spec = autoscaler["spec"]
        existing = kubectl.json(["get", "deployment", args.name, "-n", args.namespace], check=False)
        previous = (existing or {}).get("metadata", {}).get("annotations", {}).get(ANNOTATION_MINIMUM)
        annotations = {ANNOTATION_AUTOSCALER: args.dask_autoscaler,
                       ANNOTATION_MINIMUM: previous if previous is not None else str(spec.get("minimum", 0))}
        dask_cluster = spec.get("cluster", args.dask_autoscaler)
        dask_workers = min(args.nodes, int(spec.get("maximum", args.nodes)))
        if dask_workers < args.nodes:
            print(f"DaskAutoscaler {args.dask_autoscaler} allows at most {dask_workers} workers; "
                  f"warming {args.nodes} nodes, starting {dask_workers} workers", flush=True)
    manifest = warm_deployment(args.name, args.namespace, args.nodes, images,
                               parse_selector(args.node_selector), parse_tolerations(args.toleration), annotations)
    if args.dry_run:
        json.dump(manifest, sys.stdout, indent=2)
        print()
        return 0
    print(f"Warming {args.nodes} nodes"
          + (f" ({args.node_selector})" if args.node_selector else "")
          + f" with {', '.join(images)}", flush=True)
    kubectl.run(["apply", "-f", "-"], input_text=json.dumps(manifest))
    if args.dask_autoscaler:
        set_autoscaler_minimum(kubectl, args.namespace, args.dask_autoscaler, dask_workers)
        print(f"DaskAutoscaler {args.dask_autoscaler}: minimum {dask_workers} "
              f"(was {annotations[ANNOTATION_MINIMUM]}; `down` restores it)", flush=True)
    if not args.wait:
        return 0
    ok = wait_warm(kubectl, args.name, args.namespace, args.nodes, parse_selector(args.node_selector),
                   gpu_resource, parse_duration(args.timeout), dask_cluster, dask_workers)
    return 0 if ok else 1


def cmd_status(args, kubectl: Kubectl) -> int:
    deployment = kubectl.json(["get", "deployment", args.name, "-n", args.namespace], check=False)
    if not deployment:
        print(f"No warm pool: deployment {args.namespace}/{args.name} not found")
        return 1
    gpu_resource = None if args.gpu_resource.lower() == "none" else args.gpu_resource
    pods = kubectl.json(["get", "pods", "-n", args.namespace, "-l", f"{WARM_LABEL}={args.name}"])["items"]
    nodes = {node["metadata"]["name"]: node for node in kubectl.json(["get", "nodes"])["items"]}
    times = pull_times(kubectl, args.namespace)
    print(f"{'pod':<34} {'node':<40} {'zone':<16} {'image':<14} {gpu_resource or ''}")
    for pod in pods:
        state = pod_state(pod, nodes, gpu_resource)
        if state["pulled"]:
            seconds = times.get(state["pod"])
            pulled = "cached" if seconds == "cached" else f"pulled {seconds}" if seconds else "pulled"
        else:
            pulled = "pulling" if state["node"] else "pending"
        print(f"{state['pod']:<34} {state['node'] or '-':<40} {state['zone'] or '-':<16} {pulled:<14} "
              f"{state['gpus'] if state['gpus'] is not None else ''}")
    annotations = deployment["metadata"].get("annotations", {})
    if ANNOTATION_AUTOSCALER in annotations:
        print(f"DaskAutoscaler {annotations[ANNOTATION_AUTOSCALER]}: minimum restored to "
              f"{annotations.get(ANNOTATION_MINIMUM, 0)} on `down`")
    return 0


def cmd_down(args, kubectl: Kubectl) -> int:
    deployment = kubectl.json(["get", "deployment", args.name, "-n", args.namespace], check=False)
    annotations = (deployment or {}).get("metadata", {}).get("annotations", {})
    autoscaler = args.dask_autoscaler or annotations.get(ANNOTATION_AUTOSCALER)
    if autoscaler:
        minimum = args.dask_minimum if args.dask_minimum is not None else int(annotations.get(ANNOTATION_MINIMUM, 0))
        set_autoscaler_minimum(kubectl, args.namespace, autoscaler, minimum)
        print(f"DaskAutoscaler {autoscaler}: minimum {minimum}")
    if deployment:
        kubectl.run(["delete", "deployment", args.name, "-n", args.namespace, "--wait=false"])
        print(f"Deleted {args.namespace}/{args.name}. Idle nodes go after the cluster autoscaler's "
              f"scale-down-unneeded-time (AKS default 10m).")
    else:
        print(f"No warm pool: deployment {args.namespace}/{args.name} not found")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--context", help="kubectl context (default the current one)")
    parser.add_argument("--namespace", "-n", default="dask", help="namespace of the warm pods (default dask)")
    parser.add_argument("--name", default="gpu-warm", help="name of the warm Deployment (default gpu-warm)")
    parser.add_argument("--gpu-resource", default="nvidia.com/gpu",
                        help="extended resource a warm node must advertise (default nvidia.com/gpu); none to skip")
    commands = parser.add_subparsers(dest="command", required=True)

    up = commands.add_parser("up", help="scale the pool to N nodes, pull the image on each, keep them")
    up.add_argument("--nodes", type=int, required=True, help="nodes to warm, e.g. the pool's max count")
    up.add_argument("--image", action="append", help=f"image to pull, repeatable (default {IMAGE})")
    up.add_argument("--node-selector", metavar="KEY=VALUE[,KEY=VALUE]", help="the pool's labels, e.g. agentpool=t4")
    up.add_argument("--toleration", metavar="KEY[=VALUE][:EFFECT]", action="append",
                    help="taint of the pool, repeatable, e.g. sku=gpu:NoSchedule; all for every taint")
    up.add_argument("--dask-autoscaler", metavar="NAME",
                    help="also raise this DaskAutoscaler's minimum to N (at most its maximum) and wait for the workers")
    up.add_argument("--timeout", default="30m", help="how long to wait (default 30m)")
    up.add_argument("--no-wait", dest="wait", action="store_false", help="apply and return")
    up.add_argument("--dry-run", action="store_true", help="print the Deployment and change nothing")

    commands.add_parser("status", help="the warm pods, their nodes and images")

    down = commands.add_parser("down", help="remove the warm pods and restore the DaskAutoscaler minimum")
    down.add_argument("--dask-autoscaler", metavar="NAME", help="DaskAutoscaler to reset (default the one `up` raised)")
    down.add_argument("--dask-minimum", type=int, help="minimum to set (default the one before `up`)")

    args = parser.parse_args(argv)
    kubectl = Kubectl(args.context)
    try:
        return {"up": cmd_up, "status": cmd_status, "down": cmd_down}[args.command](args, kubectl)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped waiting; the warm pods stay (`down` removes them).", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
