"""Collect CPU, memory and GPU use of running worker pods, to compare runs.

Every few seconds it finds the pods matching a label selector (by default the
Dask workers in namespace dask), runs a small probe in each, and appends one
row per pod and GPU to a CSV:

    python3 config/dask/gpu_metrics.py collect --label workers=4 --out w4.csv
    #  ... run the job; collection stops 60s after the last worker is gone,
    #  when --job is done, after --duration, or on Ctrl-C
    python3 config/dask/gpu_metrics.py summary w1.csv w2.csv w4.csv w8.csv

The summary has one line per run: workers, GPU utilization, GPU memory used
and CPU, so the runs of one job at different worker counts line up.

The probe needs only `sh` in the pod's container; it reads
  - CPU and memory from the container's cgroup (cpu.stat, memory.current minus
    inactive file cache: the working set, as the kubelet counts it), so CPU is
    exact over each interval, not the metrics-server's 15-60s average;
  - GPU from `nvidia-smi` (in images run with NVIDIA_DRIVER_CAPABILITIES
    including utility, as the Dask image is): utilization, memory-controller
    utilization, memory used and total, per GPU the container sees.
GPU numbers are per GPU, not per process: a GPU shared by several pods (time
slicing, MPS) shows the same numbers in each; the summary counts each GPU once.
Nothing is Dask-specific: --selector and --container point it at any pods.

Where it runs:
  - anywhere with kubectl (`--context`), through `kubectl exec`; or
  - in the cluster, e.g. on the CPU pool beside the scheduler, through the API
    server with the pod's service account (`job` prints the Job and RBAC):

    python3 config/dask/gpu_metrics.py job --label workers=4 \\
      --node-selector agentpool=general --toleration all \\
      --image myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1 | kubectl apply -f -
    kubectl -n dask logs -f job/gpu-metrics > w4.csv     # the CSV is the Job's output

    The Job runs this file from the devlab-dask ConfigMap
    (kubectl apply -k config/dask) with any image that has python3.
"""

import argparse
import base64
import csv
import json
import os
import re
import socket
import ssl
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

SERVICE_ACCOUNT = "/var/run/secrets/kubernetes.io/serviceaccount"
DEFAULT_SELECTOR = "dask.org/component=worker"
DEFAULT_IMAGE = "localhost:5000/devlab-dask-gpu:2026.1.1"

# One shell run per pod and sample, shell builtins only apart from nvidia-smi;
# sections the parser splits on '@'
PROBE = r"""
echo @uptime; read uptime idle < /proc/uptime; echo "$uptime"
echo @cpu
if [ -f /sys/fs/cgroup/cpu.stat ]; then
  while read key value; do [ "$key" = usage_usec ] && echo "usage_usec $value"; done < /sys/fs/cgroup/cpu.stat
else
  for f in /sys/fs/cgroup/cpuacct/cpuacct.usage /sys/fs/cgroup/cpu,cpuacct/cpuacct.usage; do
    [ -f "$f" ] && { read value < "$f"; echo "usage_ns $value"; break; }
  done
fi
echo @mem
for f in /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory/memory.usage_in_bytes; do
  [ -f "$f" ] && { read value < "$f"; echo "$value"; break; }
done
echo @memstat
for f in /sys/fs/cgroup/memory.stat /sys/fs/cgroup/memory/memory.stat; do
  [ -f "$f" ] && while read key value; do
    case "$key" in inactive_file|total_inactive_file) echo "$key $value";; esac
  done < "$f"
done
echo @gpu
nvidia-smi --query-gpu=index,uuid,utilization.gpu,utilization.memory,memory.used,memory.total \
  --format=csv,noheader,nounits 2>&1 || true
"""

COLUMNS = [
    "time", "elapsed_s", "sample", "label", "pod", "node", "workers",
    "cpu_cores", "cpu_request", "cpu_limit", "cpu_pct_request",
    "mem_bytes", "mem_limit", "mem_pct_limit",
    "gpus_requested", "gpu_index", "gpu_uuid", "gpu_util_pct", "gpu_mem_ctrl_pct",
    "gpu_mem_used_mib", "gpu_mem_total_mib", "gpu_mem_pct", "error",
]


# --- Quantities and parsing -------------------------------------------------

def parse_cpu(text: Optional[str]) -> Optional[float]:
    """Kubernetes CPU quantity (``500m``, ``3``) as cores"""
    if not text:
        return None
    text = str(text)
    if text.endswith("m"):
        return float(text[:-1]) / 1000
    if text.endswith("n"):
        return float(text[:-1]) / 1e9
    return float(text)


_MEMORY_UNITS = {"Ki": 2 ** 10, "Mi": 2 ** 20, "Gi": 2 ** 30, "Ti": 2 ** 40, "Pi": 2 ** 50,
                 "k": 10 ** 3, "K": 10 ** 3, "M": 10 ** 6, "G": 10 ** 9, "T": 10 ** 12, "P": 10 ** 15}


def parse_memory(text: Optional[str]) -> Optional[int]:
    """Kubernetes memory quantity (``20Gi``, ``512M``, ``1e9``) as bytes"""
    if not text:
        return None
    match = re.fullmatch(r"([0-9.eE+-]+)([A-Za-z]*)", str(text))
    if not match:
        return None
    number, unit = match.groups()
    return int(float(number) * _MEMORY_UNITS.get(unit, 1))


def parse_duration(text: str) -> float:
    """``90``, ``90s``, ``5m``, ``1h`` or ``1h30m`` as seconds"""
    text = str(text).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = re.findall(r"(\d+(?:\.\d+)?)([hms])", text)
    if not parts or "".join(number + unit for number, unit in parts) != text:
        raise ValueError(f"not a duration: {text!r} (e.g. 90s, 5m, 1h)")
    return sum(float(number) * {"h": 3600, "m": 60, "s": 1}[unit] for number, unit in parts)


def _number(text: str) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None  # [N/A], [Not Supported]


def parse_probe(output: str) -> dict:
    """The probe's output as uptime (s), cpu_seconds, mem_bytes (working set), gpus and gpu_error"""
    sections: Dict[str, List[str]] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("@") and line[1:].strip().isidentifier():
            current = line[1:].strip()
            sections[current] = []
        elif current is not None and line.strip():
            sections[current].append(line.strip())
    result = {"uptime": None, "cpu_seconds": None, "mem_bytes": None, "gpus": [], "gpu_error": None}
    if sections.get("uptime"):
        result["uptime"] = _number(sections["uptime"][0].split()[0])
    for line in sections.get("cpu", []):
        name, _, value = line.partition(" ")
        if name == "usage_usec" and _number(value) is not None:
            result["cpu_seconds"] = float(value) / 1e6
        elif name == "usage_ns" and _number(value) is not None:
            result["cpu_seconds"] = float(value) / 1e9
    usage = _number(sections["mem"][0]) if sections.get("mem") else None
    if usage is not None:
        inactive = 0.0
        for line in sections.get("memstat", []):
            name, _, value = line.partition(" ")
            if name in ("inactive_file", "total_inactive_file") and _number(value) is not None:
                inactive = float(value)
        result["mem_bytes"] = int(max(usage - inactive, 0))
    gpu_lines = sections.get("gpu", [])
    for line in gpu_lines:
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 6 and fields[0].isdigit():
            index, uuid, util, ctrl, used, total = fields
            result["gpus"].append({"index": int(index), "uuid": uuid, "util": _number(util),
                                   "mem_ctrl": _number(ctrl), "mem_used": _number(used), "mem_total": _number(total)})
    if gpu_lines and not result["gpus"]:
        result["gpu_error"] = gpu_lines[0][:120]
    return result


def container_limits(pod: dict, container_name: Optional[str]) -> dict:
    """The probed container's name, CPU request and limit, memory limit and GPUs requested"""
    containers = pod["spec"]["containers"]
    container = next((c for c in containers if c["name"] == container_name), None) if container_name else containers[0]
    if container is None:
        return {"name": None}
    resources = container.get("resources", {})
    requests, limits = resources.get("requests", {}), resources.get("limits", {})
    gpus = sum(float(v) for k, v in {**requests, **limits}.items() if k.endswith("/gpu"))
    return {
        "name": container["name"],
        "cpu_request": parse_cpu(requests.get("cpu")),
        "cpu_limit": parse_cpu(limits.get("cpu")),
        "mem_limit": parse_memory(limits.get("memory")),
        "gpus_requested": gpus or None,
    }


def pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    return round(100 * part / whole, 1) if part is not None and whole else None


def sample_rows(pod: dict, probe: dict, previous: Optional[dict], limits: dict, base: dict,
                error: Optional[str] = None) -> List[dict]:
    """CSV rows for one pod and sample: one per GPU, or one without GPU columns"""
    cpu = None
    if previous and probe.get("cpu_seconds") is not None and previous.get("cpu_seconds") is not None:
        span = (probe.get("uptime") or 0) - (previous.get("uptime") or 0)
        if span > 0:
            cpu = max(probe["cpu_seconds"] - previous["cpu_seconds"], 0) / span
    row = {
        **base,
        "pod": pod["metadata"]["name"],
        "node": pod["spec"].get("nodeName", ""),
        "cpu_cores": round(cpu, 3) if cpu is not None else None,
        "cpu_request": limits.get("cpu_request"),
        "cpu_limit": limits.get("cpu_limit"),
        "cpu_pct_request": pct(cpu, limits.get("cpu_request")),
        "mem_bytes": probe.get("mem_bytes"),
        "mem_limit": limits.get("mem_limit"),
        "mem_pct_limit": pct(probe.get("mem_bytes"), limits.get("mem_limit")),
        "gpus_requested": limits.get("gpus_requested"),
        "error": error or probe.get("gpu_error"),
    }
    if not probe.get("gpus"):
        return [row]
    return [{**row,
             "gpu_index": gpu["index"], "gpu_uuid": gpu["uuid"], "gpu_util_pct": gpu["util"],
             "gpu_mem_ctrl_pct": gpu["mem_ctrl"], "gpu_mem_used_mib": gpu["mem_used"],
             "gpu_mem_total_mib": gpu["mem_total"], "gpu_mem_pct": pct(gpu["mem_used"], gpu["mem_total"])}
            for gpu in probe["gpus"]]


# --- Kubernetes access ------------------------------------------------------

class KubectlApi:
    """Through kubectl: wherever a kubeconfig works"""

    def __init__(self, context: Optional[str] = None):
        self.base = ["kubectl"] + (["--context", context] if context else [])

    def get(self, path: str) -> dict:
        result = subprocess.run(self.base + ["get", "--raw", path], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"kubectl get --raw {path} failed")
        return json.loads(result.stdout)

    def exec(self, namespace: str, pod: str, container: str, command: List[str], timeout: float = 30) -> str:
        result = subprocess.run(self.base + ["exec", "-n", namespace, pod, "-c", container, "--"] + command,
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 and not result.stdout:
            raise RuntimeError(result.stderr.strip()[:200] or f"exec exit {result.returncode}")
        return result.stdout


class InClusterApi:
    """Straight to the API server with the pod's service account; exec over a WebSocket"""

    def __init__(self, root: str = SERVICE_ACCOUNT):
        self.host = os.environ["KUBERNETES_SERVICE_HOST"]
        self.port = int(os.environ.get("KUBERNETES_SERVICE_PORT", "443"))
        with open(os.path.join(root, "token")) as handle:
            self.token = handle.read().strip()
        self.context = ssl.create_default_context(cafile=os.path.join(root, "ca.crt"))
        host = f"[{self.host}]" if ":" in self.host else self.host
        self.url = f"https://{host}:{self.port}"

    def get(self, path: str) -> dict:
        request = urllib.request.Request(self.url + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(request, context=self.context, timeout=60) as response:
            return json.load(response)

    def exec(self, namespace: str, pod: str, container: str, command: List[str], timeout: float = 30) -> str:
        query = [("container", container), ("stdout", "true"), ("stderr", "true")] + [("command", c) for c in command]
        path = f"/api/v1/namespaces/{namespace}/pods/{pod}/exec?{urllib.parse.urlencode(query)}"
        raw = socket.create_connection((self.host, self.port), timeout=timeout)
        with self.context.wrap_socket(raw, server_hostname=self.host) as sock:
            key = base64.b64encode(os.urandom(16)).decode()
            sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
                          f"Authorization: Bearer {self.token}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                          f"Sec-WebSocket-Protocol: v4.channel.k8s.io\r\n\r\n").encode())
            stdout, stderr, status = websocket_exec(SocketReader(sock))
        if status.get("status") == "Failure" and not stdout:
            raise RuntimeError((status.get("message") or stderr or "exec failed")[:200])
        return stdout


class SocketReader:
    """Exact reads from a socket, keeping what arrives past what was asked for"""

    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def read_until(self, marker: bytes) -> bytes:
        while marker not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buffer += chunk
        data, _, self.buffer = self.buffer.partition(marker)
        return data

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)


def websocket_exec(reader) -> Tuple[str, str, dict]:
    """Read a Kubernetes exec stream (v4.channel.k8s.io) to its end: stdout, stderr, status"""
    head = reader.read_until(b"\r\n\r\n").decode(errors="replace")
    status_line = head.split("\r\n", 1)[0]
    if " 101 " not in f"{status_line} ":
        body = reader.buffer.decode(errors="replace")[:300]
        raise RuntimeError(f"exec refused: {status_line} {body}".strip())
    channels = {1: b"", 2: b"", 3: b""}
    channel = None
    while True:
        try:
            first, second = reader.read(2)
        except EOFError:
            break
        opcode, length = first & 0x0F, second & 0x7F
        if length == 126:
            length = int.from_bytes(reader.read(2), "big")
        elif length == 127:
            length = int.from_bytes(reader.read(8), "big")
        mask = reader.read(4) if second & 0x80 else None
        payload = reader.read(length) if length else b""
        if mask:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        if opcode == 0x8:  # close
            break
        if opcode == 0x9:  # ping: pong with the same payload, masked as a client must
            pong_mask = os.urandom(4)
            reader.send(bytes([0x8A, 0x80 | len(payload)]) + pong_mask
                        + bytes(b ^ pong_mask[i % 4] for i, b in enumerate(payload)))
            continue
        if opcode in (0x1, 0x2) and payload:
            channel, payload = payload[0], payload[1:]
        if opcode in (0x0, 0x1, 0x2) and channel in channels:
            channels[channel] += payload
    status = {}
    if channels[3]:
        try:
            status = json.loads(channels[3])
        except ValueError:
            status = {"status": "Failure", "message": channels[3].decode(errors="replace")}
    return channels[1].decode(errors="replace"), channels[2].decode(errors="replace"), status


def make_api(mode: str, context: Optional[str]):
    in_cluster = os.path.exists(os.path.join(SERVICE_ACCOUNT, "token")) and "KUBERNETES_SERVICE_HOST" in os.environ
    if mode == "in-cluster" or (mode == "auto" and in_cluster and not context):
        return InClusterApi()
    return KubectlApi(context)


# --- Collecting -------------------------------------------------------------

def running_pods(api, namespace: str, selector: str) -> List[dict]:
    pods = api.get(f"/api/v1/namespaces/{namespace}/pods?labelSelector={urllib.parse.quote(selector)}")["items"]
    return [pod for pod in pods
            if pod.get("status", {}).get("phase") == "Running" and not pod["metadata"].get("deletionTimestamp")]


def job_finished(api, namespace: str, name: str) -> Optional[str]:
    """'Complete' or 'Failed' once the Job has finished, else None"""
    try:
        job = api.get(f"/apis/batch/v1/namespaces/{namespace}/jobs/{name}")
    except Exception:  # not created yet, or gone
        return None
    for condition in job.get("status", {}).get("conditions") or []:
        if condition.get("type") in ("Complete", "Failed") and condition.get("status") == "True":
            return condition["type"]
    return None


def fmt(value) -> str:
    return "" if value is None else value


def live_line(rows: List[dict], workers: int) -> str:
    gpus = {}
    for row in rows:
        if row.get("gpu_uuid"):
            gpus[row["gpu_uuid"]] = row
    pods = {row["pod"]: row for row in rows}
    cpu = [row["cpu_cores"] for row in pods.values() if row.get("cpu_cores") is not None]
    util = [row["gpu_util_pct"] for row in gpus.values() if row.get("gpu_util_pct") is not None]
    mem = [row["gpu_mem_pct"] for row in gpus.values() if row.get("gpu_mem_pct") is not None]
    parts = [f"workers {workers}"]
    if util:
        parts.append(f"GPU util {statistics.mean(util):3.0f}% (min {min(util):.0f})")
    if mem:
        parts.append(f"GPU mem {statistics.mean(mem):3.0f}% (max {max(mem):.0f})")
    if cpu:
        parts.append(f"CPU {statistics.mean(cpu):.2f} cores/worker")
    errors = {row["error"] for row in rows if row.get("error")}
    if errors:
        parts.append(f"errors: {'; '.join(sorted(errors))[:100]}")
    return "  ".join(parts)


def collect(api, namespace: str, selector: str, container: Optional[str], interval: float, out, label: str,
            duration: Optional[float], idle_stop: Optional[float], wait_for_pods: Optional[float],
            job: Optional[str], log) -> List[dict]:
    writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    out.flush()
    previous: Dict[str, dict] = {}
    known: Dict[str, str] = {}
    all_rows: List[dict] = []
    start = time.monotonic()
    last_seen = None
    sample = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=16) as pool:
        while True:
            tick = time.monotonic()
            elapsed = tick - start
            try:
                pods = running_pods(api, namespace, selector)
            except Exception as error:  # API hiccup: try again next interval
                log(f"  {elapsed:6.0f}s  listing pods failed: {error}")
                pods = []
            names = {pod["metadata"]["name"]: pod for pod in pods}
            for name in sorted(set(names) - set(known)):
                known[name] = names[name]["spec"].get("nodeName", "")
                log(f"  {elapsed:6.0f}s  + {name} on {known[name]}")
            for name in sorted(set(known) - set(names)):
                log(f"  {elapsed:6.0f}s  - {name}")
                known.pop(name)
                previous.pop(name, None)
            if pods:
                last_seen = tick
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                base = {"time": now, "elapsed_s": round(elapsed, 1), "sample": sample, "label": label,
                        "workers": len(pods)}

                def probe(pod):
                    limits = container_limits(pod, container)
                    name = pod["metadata"]["name"]
                    if limits["name"] is None:
                        return sample_rows(pod, {}, None, limits, base, error=f"no container {container}")
                    try:
                        result = parse_probe(api.exec(namespace, name, limits["name"], ["sh", "-c", PROBE]))
                        error = None
                    except Exception as exc:
                        result, error = {}, str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__
                    with lock:
                        before = previous.get(name)
                        if result.get("cpu_seconds") is not None:
                            previous[name] = result
                    return sample_rows(pod, result, before, limits, base, error)

                rows = [row for rows in pool.map(probe, pods) for row in rows]
                rows = [{key: (round(value, 1) if isinstance(value, float) and key.endswith("_pct") else value)
                         for key, value in row.items()} for row in rows]
                writer.writerows({key: fmt(value) for key, value in row.items()} for row in rows)
                out.flush()
                all_rows.extend(rows)
                log(f"  {elapsed:6.0f}s  {live_line(rows, len(pods))}")
                sample += 1
            if duration is not None and elapsed >= duration:
                log(f"Stopped after --duration {duration:.0f}s")
                break
            if job and sample and job_finished(api, namespace, job):
                log(f"Stopped: job {job} finished")
                break
            if idle_stop is not None and last_seen is not None and not pods and tick - last_seen >= idle_stop:
                log(f"Stopped: no matching pods for {idle_stop:.0f}s")
                break
            if wait_for_pods is not None and last_seen is None and elapsed >= wait_for_pods:
                log(f"Stopped: no pods matching {selector} in {namespace} after {wait_for_pods:.0f}s")
                break
            time.sleep(max(interval - (time.monotonic() - tick), 0.2))
    return all_rows


# --- Summary ----------------------------------------------------------------

def _float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def summarize(rows: List[dict], busy_threshold: float = 5.0) -> dict:
    """One run's figures: GPUs counted once per sample, pods once per sample"""
    gpu_samples: Dict[Tuple[str, str], dict] = {}
    pod_samples: Dict[Tuple[str, str], dict] = {}
    workers_by_sample: Dict[str, int] = {}
    elapsed = []
    for row in rows:
        sample = str(row.get("sample"))
        workers_by_sample[sample] = int(_float(row.get("workers")) or 0)
        pod_samples[(sample, row.get("pod", ""))] = row
        if row.get("gpu_uuid"):
            gpu_samples[(sample, row["gpu_uuid"])] = row
        if _float(row.get("elapsed_s")) is not None:
            elapsed.append(_float(row["elapsed_s"]))
    util = [_float(r.get("gpu_util_pct")) for r in gpu_samples.values()]
    util = [u for u in util if u is not None]
    busy = [u for u in util if u > busy_threshold]
    mem = [m for m in (_float(r.get("gpu_mem_pct")) for r in gpu_samples.values()) if m is not None]
    mem_used = [m for m in (_float(r.get("gpu_mem_used_mib")) for r in gpu_samples.values()) if m is not None]
    cpu = [c for c in (_float(r.get("cpu_cores")) for r in pod_samples.values()) if c is not None]
    cpu_pct = [c for c in (_float(r.get("cpu_pct_request")) for r in pod_samples.values()) if c is not None]
    host_mem = [m for m in (_float(r.get("mem_pct_limit")) for r in pod_samples.values()) if m is not None]
    workers = list(workers_by_sample.values())
    p95 = sorted(util)[int(0.95 * (len(util) - 1))] if util else None
    return {
        "samples": len(workers_by_sample),
        "seconds": (max(elapsed) - min(elapsed)) if elapsed else 0,
        "workers_max": max(workers) if workers else 0,
        "workers_mean": statistics.mean(workers) if workers else 0,
        "gpus": len({uuid for _, uuid in gpu_samples}),
        "gpu_util_mean": statistics.mean(util) if util else None,
        "gpu_util_busy": statistics.mean(busy) if busy else None,
        "gpu_util_p95": p95,
        "busy_share": len(busy) / len(util) if util else None,
        "gpu_mem_mean": statistics.mean(mem) if mem else None,
        "gpu_mem_max": max(mem) if mem else None,
        "gpu_mem_max_mib": max(mem_used) if mem_used else None,
        "cpu_mean": statistics.mean(cpu) if cpu else None,
        "cpu_pct_request": statistics.mean(cpu_pct) if cpu_pct else None,
        "host_mem_max": max(host_mem) if host_mem else None,
        "errors": sum(1 for r in pod_samples.values() if r.get("error")),
    }


def read_runs(paths: List[str]) -> Dict[str, List[dict]]:
    runs: Dict[str, List[dict]] = {}
    for path in paths:
        with open(path, newline="") as handle:
            for row in csv.DictReader(handle):
                runs.setdefault(row.get("label") or os.path.basename(path), []).append(row)
    return runs


def summary_table(runs: Dict[str, List[dict]], busy_threshold: float = 5.0) -> str:
    def cell(value, spec, suffix=""):
        return "-" if value is None else f"{value:{spec}}{suffix}"

    header = (f"{'run':<20} {'time':>6} {'workers':>8} {'GPUs':>4} {'util':>5} {'busy':>5} {'p95':>4} "
              f"{'busy%':>5} {'GPUmem':>6} {'max':>4} {'maxMiB':>7} {'CPU':>5} {'%req':>5} {'RAM%':>5} {'err':>4}")
    lines = [header]
    for label, rows in sorted(runs.items(), key=lambda item: (summarize(item[1])["workers_max"], item[0])):
        s = summarize(rows, busy_threshold)
        lines.append(
            f"{label[:20]:<20} {s['seconds']:>5.0f}s {s['workers_mean']:>4.1f}/{s['workers_max']:<3} {s['gpus']:>4} "
            f"{cell(s['gpu_util_mean'], '4.0f', '%'):>5} {cell(s['gpu_util_busy'], '4.0f', '%'):>5} "
            f"{cell(s['gpu_util_p95'], '3.0f'):>4} {cell(None if s['busy_share'] is None else 100 * s['busy_share'], '4.0f', '%'):>5} "
            f"{cell(s['gpu_mem_mean'], '5.0f', '%'):>6} {cell(s['gpu_mem_max'], '3.0f'):>4} "
            f"{cell(s['gpu_mem_max_mib'], '7.0f'):>7} {cell(s['cpu_mean'], '5.2f'):>5} "
            f"{cell(s['cpu_pct_request'], '4.0f', '%'):>5} {cell(s['host_mem_max'], '4.0f', '%'):>5} {s['errors']:>4}")
    lines += [
        "",
        "time: first to last sample with workers. workers: mean/max running. GPUs: distinct GPUs seen.",
        f"util: mean GPU utilization over all GPU samples; busy: mean over samples above {busy_threshold:g}%; "
        "p95; busy%: share of samples above it.",
        "GPUmem: mean and max % of GPU memory used, maxMiB the most used. CPU: mean cores per worker, "
        "%req of its CPU request. RAM%: max working set as % of the memory limit. err: samples with a probe error.",
    ]
    return "\n".join(lines)


# --- In-cluster Job ---------------------------------------------------------

def job_manifests(name: str, namespace: str, image: str, collect_args: List[str],
                  node_selector: Optional[Dict[str, str]], tolerations: Optional[List[dict]]) -> List[dict]:
    """ServiceAccount, Role, RoleBinding and the Job that runs `collect` in the cluster"""
    account = "gpu-metrics"
    pod_spec = {
        "serviceAccountName": account,
        "restartPolicy": "Never",
        "containers": [{
            "name": "collect",
            "image": image,
            "imagePullPolicy": "IfNotPresent",
            "command": ["python3", "/devlab/gpu_metrics.py", "collect", "--api", "in-cluster", "--out", "-",
                        "--quiet"] + collect_args,
            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "512Mi"}},
            "volumeMounts": [{"name": "devlab-dask", "mountPath": "/devlab"}],
        }],
        "volumes": [{"name": "devlab-dask", "configMap": {"name": "devlab-dask"}}],
    }
    if node_selector:
        pod_spec["nodeSelector"] = dict(node_selector)
    if tolerations:
        pod_spec["tolerations"] = list(tolerations)
    meta = {"namespace": namespace}
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": account, **meta}},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": {"name": account, **meta},
         "rules": [
             {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]},
             # WebSocket exec is a GET; older API servers check create
             {"apiGroups": [""], "resources": ["pods/exec"], "verbs": ["get", "create"]},
             {"apiGroups": ["batch"], "resources": ["jobs"], "verbs": ["get"]},
         ]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": account, **meta},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": account},
         "subjects": [{"kind": "ServiceAccount", "name": account, "namespace": namespace}]},
        {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, **meta},
         "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 86400, "template": {"spec": pod_spec}}},
    ]


# --- CLI --------------------------------------------------------------------

def add_collect_options(parser) -> None:
    parser.add_argument("--namespace", "-n", default="dask", help="namespace of the pods (default dask)")
    parser.add_argument("--selector", "-l", default=DEFAULT_SELECTOR,
                        help=f"label selector of the pods to watch (default {DEFAULT_SELECTOR})")
    parser.add_argument("--container", "-c", help="container to probe (default each pod's first)")
    parser.add_argument("--interval", type=float, default=5, help="seconds between samples (default 5)")
    parser.add_argument("--label", default="", help="run name in the CSV and summary, e.g. workers=4")
    parser.add_argument("--duration", help="stop after this long, e.g. 30m")
    parser.add_argument("--stop-after-idle", default="60s",
                        help="stop when no pod has matched for this long after some did (default 60s; 0 never)")
    parser.add_argument("--wait-for-pods", default="1h", help="give up when no pod matches within this (default 1h)")
    parser.add_argument("--job", help="stop when this Job (same namespace) has finished, e.g. gpu-stress")


def collect_args_from(args) -> List[str]:
    """The collect options of `job`, passed on to the in-cluster run"""
    out = ["--namespace", args.namespace, "--selector", args.selector, "--interval", str(args.interval),
           "--stop-after-idle", args.stop_after_idle, "--wait-for-pods", args.wait_for_pods]
    for flag, value in (("--container", args.container), ("--label", args.label),
                        ("--duration", args.duration), ("--job", args.job)):
        if value:
            out += [flag, value]
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("collect", help="sample the pods until they are gone (or Ctrl-C), write a CSV")
    add_collect_options(run)
    run.add_argument("--out", "-o", help="CSV file; - for stdout (default gpu-metrics-<label or time>.csv)")
    run.add_argument("--context", help="kubectl context (default the current one)")
    run.add_argument("--api", choices=["auto", "kubectl", "in-cluster"], default="auto",
                     help="kubectl, or the service account when running in a pod (auto: in a pod without --context)")
    run.add_argument("--quiet", "-q", action="store_true", help="no progress on stderr")
    run.add_argument("--busy-threshold", type=float, default=5, help="GPU %% counted as busy in the summary (5)")

    show = commands.add_parser("summary", help="one line per run of one or more CSVs")
    show.add_argument("files", nargs="+")
    show.add_argument("--busy-threshold", type=float, default=5, help="GPU %% counted as busy (default 5)")

    job = commands.add_parser("job", help="print a Job (and its RBAC) that runs collect in the cluster")
    add_collect_options(job)
    job.add_argument("--name", default="gpu-metrics", help="Job name (default gpu-metrics)")
    job.add_argument("--image", default=DEFAULT_IMAGE, help=f"any image with python3 (default {DEFAULT_IMAGE})")
    job.add_argument("--node-selector", metavar="KEY=VALUE[,KEY=VALUE]", help="where the Job runs, e.g. the CPU pool")
    job.add_argument("--toleration", metavar="KEY[=VALUE][:EFFECT]", action="append",
                     help="taint the Job tolerates, repeatable; all for every taint")

    args = parser.parse_args(argv)

    if args.command == "summary":
        print(summary_table(read_runs(args.files), args.busy_threshold))
        return 0

    if args.command == "job":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from devlab_dask import parse_selector, parse_tolerations
        items = job_manifests(args.name, args.namespace, args.image, collect_args_from(args),
                              parse_selector(args.node_selector), parse_tolerations(args.toleration))
        json.dump({"apiVersion": "v1", "kind": "List", "items": items}, sys.stdout, indent=2)
        print()
        return 0

    idle = parse_duration(args.stop_after_idle)

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr, flush=True)

    api = make_api(args.api, args.context)
    path = args.out or "gpu-metrics-{}.csv".format(
        re.sub(r"[^A-Za-z0-9_.-]+", "-", args.label) if args.label else datetime.now().strftime("%Y%m%d-%H%M%S"))
    out = sys.stdout if path == "-" else open(path, "w", newline="")
    log(f"Watching pods {args.selector} in {args.namespace} every {args.interval:g}s"
        + (f", writing {path}" if path != "-" else "") + "; Ctrl-C stops")
    rows: List[dict] = []
    try:
        rows = collect(api, args.namespace, args.selector, args.container, args.interval, out, args.label,
                       parse_duration(args.duration) if args.duration else None, idle or None,
                       parse_duration(args.wait_for_pods), args.job, log)
    except KeyboardInterrupt:
        log("Stopped (Ctrl-C)")
    finally:
        if out is not sys.stdout:
            out.close()
    if path != "-":
        rows = read_runs([path]).get(args.label or os.path.basename(path), [])
    if rows:
        log(summary_table({args.label or os.path.basename(path): rows}, args.busy_threshold))
    return 0


if __name__ == "__main__":
    sys.exit(main())
