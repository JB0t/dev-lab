"""Tests for config/dask/gpu_warm.py and config/dask/gpu_metrics.py (no cluster needed)."""

import csv
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASK_DIR = REPO_ROOT / "config" / "dask"


def load_module(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


warm = load_module("gpu_warm", DASK_DIR / "gpu_warm.py")
metrics = load_module("gpu_metrics", DASK_DIR / "gpu_metrics.py")


class WarmDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.deployment = warm.warm_deployment(
            "gpu-warm", "dask", 4, ["acr.example/team/dask:1", "acr.example/team/client:1"],
            {"agentpool": "t4"}, [{"key": "sku", "operator": "Equal", "value": "gpu", "effect": "NoSchedule"}],
            {"devlab.io/dask-autoscaler": "gpu"})
        self.pod = self.deployment["spec"]["template"]["spec"]

    def test_one_pod_per_node_on_the_pool(self):
        self.assertEqual(self.deployment["spec"]["replicas"], 4)
        term = self.pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][0]
        self.assertEqual(term["topologyKey"], "kubernetes.io/hostname")
        self.assertEqual(term["labelSelector"]["matchLabels"], {"devlab.io/warm": "gpu-warm"})
        self.assertEqual(self.deployment["spec"]["selector"]["matchLabels"], {"devlab.io/warm": "gpu-warm"})
        self.assertEqual(self.pod["nodeSelector"], {"agentpool": "t4"})
        self.assertEqual(self.pod["tolerations"][0]["key"], "sku")
        # Rolling updates would need an extra node because of the anti-affinity
        self.assertEqual(self.deployment["spec"]["strategy"], {"type": "Recreate"})

    def test_every_image_is_pulled_and_held_cheaply(self):
        containers = self.pod["containers"]
        self.assertEqual([c["image"] for c in containers], ["acr.example/team/dask:1", "acr.example/team/client:1"])
        self.assertEqual(len({c["name"] for c in containers}), 2)
        for container in containers:
            self.assertEqual(container["imagePullPolicy"], "IfNotPresent")
            self.assertEqual(container["command"][:2], ["sh", "-c"])
            self.assertNotIn("nvidia.com/gpu", json.dumps(container["resources"]))
            self.assertEqual(container["resources"]["requests"]["cpu"], "1m")

    def test_autoscaler_keeps_the_nodes(self):
        annotations = self.deployment["spec"]["template"]["metadata"]["annotations"]
        self.assertEqual(annotations["cluster-autoscaler.kubernetes.io/safe-to-evict"], "false")
        self.assertEqual(self.deployment["metadata"]["annotations"], {"devlab.io/dask-autoscaler": "gpu"})

    def test_no_selector_or_tolerations_when_not_given(self):
        pod = warm.warm_deployment("w", "dask", 1, ["img"], None, None)["spec"]["template"]["spec"]
        self.assertNotIn("nodeSelector", pod)
        self.assertNotIn("tolerations", pod)

    def test_pulled_event_times(self):
        self.assertEqual(warm.pulled_seconds(
            'Successfully pulled image "acr.example/team/dask:1" in 1m2.345s (1m2.345s including waiting). '
            'Image size: 2500000000 bytes.'), "1m2.345s")
        self.assertEqual(warm.pulled_seconds('Successfully pulled image "alpine:3.20" in 812ms'), "812ms")
        self.assertEqual(warm.pulled_seconds('Container image "alpine:3.20" already present on machine'), "cached")
        self.assertIsNone(warm.pulled_seconds("Pulling image \"alpine\""))

    def test_pod_state(self):
        pod = {"metadata": {"name": "gpu-warm-a"},
               "spec": {"nodeName": "n1", "containers": [{"name": "image-0"}]},
               "status": {"containerStatuses": [{"imageID": "sha256:abc"}]}}
        nodes = {"n1": {"metadata": {"labels": {"topology.kubernetes.io/zone": "westeurope-2"}},
                        "status": {"allocatable": {"nvidia.com/gpu": "1"}}}}
        state = warm.pod_state(pod, nodes, "nvidia.com/gpu")
        self.assertTrue(state["pulled"] and state["gpu_ready"])
        self.assertEqual(state["zone"], "westeurope-2")
        nodes["n1"]["status"]["allocatable"] = {}
        self.assertFalse(warm.pod_state(pod, nodes, "nvidia.com/gpu")["gpu_ready"])
        self.assertTrue(warm.pod_state(pod, nodes, None)["gpu_ready"])
        pod["status"]["containerStatuses"] = [{"imageID": ""}]
        self.assertFalse(warm.pod_state(pod, nodes, None)["pulled"])

    def test_durations(self):
        self.assertEqual(warm.parse_duration("30m"), 1800)
        self.assertEqual(warm.parse_duration("1h30m"), 5400)
        self.assertEqual(warm.parse_duration("90"), 90)
        with self.assertRaises(ValueError):
            warm.parse_duration("ten minutes")

    def test_dry_run_prints_the_deployment(self):
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            code = warm.main(["up", "--nodes", "3", "--node-selector", "agentpool=t4", "--toleration", "all",
                              "--image", "img:1", "--dry-run"])
        self.assertEqual(code, 0)
        deployment = json.loads(out.getvalue())
        self.assertEqual(deployment["spec"]["replicas"], 3)
        self.assertEqual(deployment["spec"]["template"]["spec"]["tolerations"], [{"operator": "Exists"}])


PROBE_V2 = """@uptime
1000.50
@cpu
usage_usec 5000000
@mem
3221225472
@memstat
inactive_file 1073741824
@gpu
0, GPU-aaaa, 87, 41, 5120, 15360
"""

PROBE_V1_NO_GPU = """@uptime
2000.00
@cpu
usage_ns 7000000000
@mem
1000
@memstat
total_inactive_file 400
@gpu
sh: 1: nvidia-smi: not found
"""


class ProbeTests(unittest.TestCase):
    def test_cgroup_v2_and_gpu(self):
        probe = metrics.parse_probe(PROBE_V2)
        self.assertEqual(probe["uptime"], 1000.5)
        self.assertEqual(probe["cpu_seconds"], 5.0)
        self.assertEqual(probe["mem_bytes"], 2 * 1024 ** 3)  # working set: usage minus inactive file cache
        self.assertEqual(probe["gpus"], [{"index": 0, "uuid": "GPU-aaaa", "util": 87.0, "mem_ctrl": 41.0,
                                          "mem_used": 5120.0, "mem_total": 15360.0}])
        self.assertIsNone(probe["gpu_error"])

    def test_cgroup_v1_without_gpu(self):
        probe = metrics.parse_probe(PROBE_V1_NO_GPU)
        self.assertEqual(probe["cpu_seconds"], 7.0)
        self.assertEqual(probe["mem_bytes"], 600)
        self.assertEqual(probe["gpus"], [])
        self.assertIn("nvidia-smi: not found", probe["gpu_error"])

    def test_not_supported_fields(self):
        probe = metrics.parse_probe("@gpu\n0, GPU-b, [N/A], [N/A], 100, 15360\n")
        self.assertIsNone(probe["gpus"][0]["util"])
        self.assertEqual(probe["gpus"][0]["mem_used"], 100.0)

    def test_probe_runs_in_a_posix_shell(self):
        # Shell syntax only; on a machine without cgroup files the sections are just empty
        import subprocess
        result = subprocess.run(["sh", "-n", "-c", metrics.PROBE], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_quantities(self):
        self.assertEqual(metrics.parse_cpu("500m"), 0.5)
        self.assertEqual(metrics.parse_cpu("3"), 3.0)
        self.assertEqual(metrics.parse_memory("20Gi"), 20 * 1024 ** 3)
        self.assertEqual(metrics.parse_memory("512M"), 512 * 10 ** 6)
        self.assertIsNone(metrics.parse_memory(None))


def worker_pod(name="w1", node="n1"):
    return {"metadata": {"name": name},
            "spec": {"nodeName": node, "containers": [{
                "name": "worker",
                "resources": {"requests": {"cpu": "3", "memory": "20Gi"},
                              "limits": {"memory": "20Gi", "nvidia.com/gpu": "1"}}}]}}


class RowTests(unittest.TestCase):
    def test_cpu_from_two_samples(self):
        pod = worker_pod()
        limits = metrics.container_limits(pod, None)
        self.assertEqual(limits["name"], "worker")
        self.assertEqual(limits["gpus_requested"], 1.0)
        first = metrics.parse_probe(PROBE_V2)
        second = dict(first, uptime=1005.5, cpu_seconds=20.0)  # 15 CPU-seconds in 5 seconds
        rows = metrics.sample_rows(pod, second, first, limits, {"sample": 1})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["cpu_cores"], 3.0)
        self.assertEqual(row["cpu_pct_request"], 100.0)
        self.assertEqual(row["mem_pct_limit"], 10.0)
        self.assertEqual(row["gpu_mem_pct"], 33.3)
        self.assertEqual(row["gpu_util_pct"], 87.0)

    def test_first_sample_has_no_cpu(self):
        pod = worker_pod()
        rows = metrics.sample_rows(pod, metrics.parse_probe(PROBE_V2), None, metrics.container_limits(pod, None), {})
        self.assertIsNone(rows[0]["cpu_cores"])

    def test_missing_container(self):
        self.assertIsNone(metrics.container_limits(worker_pod(), "sidecar")["name"])


def rows_for(label, samples):
    """CSV-like rows: samples is a list of (workers, [(pod, uuid, util, mem_pct, cpu)])"""
    rows = []
    for index, (workers, pods) in enumerate(samples):
        for pod, uuid, util, mem, cpu in pods:
            rows.append({"label": label, "sample": str(index), "elapsed_s": str(index * 5), "workers": str(workers),
                         "pod": pod, "gpu_uuid": uuid, "gpu_util_pct": str(util), "gpu_mem_pct": str(mem),
                         "gpu_mem_used_mib": str(mem * 150), "cpu_cores": str(cpu), "cpu_pct_request": "",
                         "mem_pct_limit": "", "error": ""})
    return rows


class SummaryTests(unittest.TestCase):
    def test_shared_gpu_counted_once(self):
        # Two pods on one time-sliced GPU report the same GPU
        rows = rows_for("shared", [(2, [("a", "GPU-1", 90, 40, 1.0), ("b", "GPU-1", 90, 40, 0.5)]),
                                   (2, [("a", "GPU-1", 70, 40, 1.0), ("b", "GPU-1", 70, 40, 0.5)])])
        summary = metrics.summarize(rows)
        self.assertEqual(summary["gpus"], 1)
        self.assertEqual(summary["gpu_util_mean"], 80)
        self.assertEqual(summary["cpu_mean"], 0.75)
        self.assertEqual(summary["workers_max"], 2)
        self.assertEqual(summary["seconds"], 5)

    def test_busy_excludes_idle_samples(self):
        rows = rows_for("w1", [(1, [("a", "GPU-1", 0, 5, 0.1)]), (1, [("a", "GPU-1", 100, 30, 1)]),
                               (1, [("a", "GPU-1", 80, 30, 1)])])
        summary = metrics.summarize(rows)
        self.assertEqual(summary["gpu_util_busy"], 90)
        self.assertAlmostEqual(summary["busy_share"], 2 / 3)
        self.assertEqual(summary["gpu_mem_max"], 30)

    def test_table_orders_runs_by_workers(self):
        runs = {"w4": rows_for("w4", [(4, [(p, f"GPU-{p}", 95, 30, 1) for p in "abcd"])]),
                "w1": rows_for("w1", [(1, [("a", "GPU-a", 99, 30, 1)])])}
        table = metrics.summary_table(runs).splitlines()
        self.assertTrue(table[1].startswith("w1"))
        self.assertTrue(table[2].startswith("w4"))
        self.assertIn("4.0/4", table[2])

    def test_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.csv")
            with open(path, "w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=metrics.COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows_for("workers=2", [(2, [("a", "GPU-a", 50, 20, 1), ("b", "GPU-b", 70, 20, 1)])]))
            runs = metrics.read_runs([path])
            self.assertEqual(list(runs), ["workers=2"])
            self.assertEqual(metrics.summarize(runs["workers=2"])["gpu_util_mean"], 60)


class FakeReader:
    """Feeds websocket_exec a recorded byte stream"""

    def __init__(self, data):
        self.buffer = data
        self.sent = b""

    def read(self, count):
        if len(self.buffer) < count:
            raise EOFError
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def read_until(self, marker):
        data, _, self.buffer = self.buffer.partition(marker)
        return data

    def send(self, data):
        self.sent += data


def frame(payload, opcode=0x2, masked=False):
    header = bytes([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header += bytes([(0x80 if masked else 0) | length])
    elif length < 65536:
        header += bytes([(0x80 if masked else 0) | 126]) + length.to_bytes(2, "big")
    else:
        header += bytes([(0x80 if masked else 0) | 127]) + length.to_bytes(8, "big")
    if masked:
        mask = b"\x01\x02\x03\x04"
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        header += mask
    return header + payload


class WebSocketTests(unittest.TestCase):
    HANDSHAKE = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n"

    def test_stdout_stderr_and_status(self):
        big = b"x" * 70000
        stream = (self.HANDSHAKE + frame(b"\x01") + frame(b"\x01hello ") + frame(b"\x01" + big)
                  + frame(b"\x02warn") + frame(b"ping", opcode=0x9)
                  + frame(b'\x03{"metadata":{},"status":"Success"}') + frame(b"", opcode=0x8))
        reader = FakeReader(stream)
        stdout, stderr, status = metrics.websocket_exec(reader)
        self.assertEqual(stdout, "hello " + "x" * 70000)
        self.assertEqual(stderr, "warn")
        self.assertEqual(status["status"], "Success")
        self.assertEqual(reader.sent[0], 0x8A)  # answered the ping with a pong

    def test_masked_frames_and_eof(self):
        reader = FakeReader(self.HANDSHAKE + frame(b"\x01masked", masked=True))
        self.assertEqual(metrics.websocket_exec(reader)[0], "masked")

    def test_refused_upgrade(self):
        reader = FakeReader(b"HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n"
                            b'{"message":"pods \\"w1\\" is forbidden"}')
        with self.assertRaises(RuntimeError) as raised:
            metrics.websocket_exec(reader)
        self.assertIn("403", str(raised.exception))
        self.assertIn("forbidden", str(raised.exception))


class JobManifestTests(unittest.TestCase):
    def test_job_runs_collect_in_cluster_with_rbac(self):
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            metrics.main(["job", "--label", "workers=4", "--job", "gpu-stress", "--node-selector",
                          "agentpool=general", "--toleration", "all", "--image", "acr.example/dask:1"])
        items = json.loads(out.getvalue())["items"]
        self.assertEqual([i["kind"] for i in items], ["ServiceAccount", "Role", "RoleBinding", "Job"])
        rules = items[1]["rules"]
        self.assertIn({"apiGroups": [""], "resources": ["pods/exec"], "verbs": ["get", "create"]}, rules)
        pod = items[3]["spec"]["template"]["spec"]
        self.assertEqual(pod["serviceAccountName"], "gpu-metrics")
        self.assertEqual(pod["nodeSelector"], {"agentpool": "general"})
        self.assertEqual(pod["tolerations"], [{"operator": "Exists"}])
        command = pod["containers"][0]["command"]
        self.assertEqual(command[:3], ["python3", "/devlab/gpu_metrics.py", "collect"])
        for expected in (["--api", "in-cluster"], ["--out", "-"], ["--label", "workers=4"], ["--job", "gpu-stress"]):
            index = command.index(expected[0])
            self.assertEqual(command[index:index + 2], expected)
        self.assertEqual(pod["volumes"][0]["configMap"]["name"], "devlab-dask")

    def test_configmap_ships_the_collector(self):
        self.assertIn("- gpu_metrics.py", (DASK_DIR / "kustomization.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
