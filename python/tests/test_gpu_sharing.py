import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GPU_DIR = REPO_ROOT / "config" / "gpu"
DASK_DIR = REPO_ROOT / "config" / "dask"

GIB = 1024 ** 3


def load_documents(path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def device_plugin_config():
    """devicePlugin.config of the GPU Operator values (the time-slicing ConfigMap)."""
    values = yaml.safe_load((GPU_DIR / "gpu-operator-values.yaml").read_text())
    return values["devicePlugin"]["config"]


def time_slicing_config(name=None):
    plugin_config = device_plugin_config()
    return yaml.safe_load(plugin_config["data"][name or plugin_config["default"]])


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flag_value(args, flag):
    return args[args.index(flag) + 1]


def parse_gib(text):
    assert text.endswith("GiB"), text
    return float(text[:-3])


class TimeSlicingTests(unittest.TestCase):
    def setUp(self):
        self.values = yaml.safe_load((GPU_DIR / "gpu-operator-values.yaml").read_text())
        self.config = self.values["devicePlugin"]["config"]

    def test_one_share_per_gib_of_gpu_memory(self):
        self.assertTrue(self.config["create"])
        self.assertEqual(self.config["default"], "time-sliced")
        resources = time_slicing_config()["sharing"]["timeSlicing"]["resources"]
        # devlab replaces the placeholder with the GPU's memory in GiB
        sys.path.insert(0, str(Path(__file__).parents[1]))
        import devlab
        self.assertEqual(resources, [{"name": "nvidia.com/gpu", "replicas": devlab.GPU_MEMORY_PLACEHOLDER}])

    def test_pods_can_request_several_shares(self):
        time_slicing = time_slicing_config()["sharing"]["timeSlicing"]
        self.assertFalse(time_slicing["renameByDefault"])
        self.assertFalse(time_slicing["failRequestsGreaterThanOne"])

    def test_exclusive_config_disables_sharing(self):
        config = yaml.safe_load(self.config["data"]["exclusive"])
        self.assertEqual(config, {"version": "v1"})

    def test_operator_uses_node_driver_toolkit_and_nvidia_runtime(self):
        # bootstrap --gpu provides the driver (host) and toolkit (node setup)
        self.assertFalse(self.values["driver"]["enabled"])
        self.assertFalse(self.values["toolkit"]["enabled"])
        self.assertEqual(self.values["operator"]["runtimeClass"], "nvidia")

    def test_cuda_forward_compat_is_off(self):
        # Legacy mode, where the node setup disables forward-compat libraries
        sys.path.insert(0, str(Path(__file__).parents[1]))
        import devlab
        self.assertFalse(self.values["cdi"]["enabled"])
        self.assertIn("cuda-compat-mode=disabled", devlab.CONFIGURE_RUNTIME_SCRIPT)
        self.assertIn("features.disable-cuda-compat-lib-hook=true", devlab.CONFIGURE_RUNTIME_SCRIPT)

    def test_validator_skips_cuda_sample_workloads(self):
        for component in ("cuda", "plugin"):
            env = {item["name"]: item["value"] for item in self.values["validator"][component]["env"]}
            self.assertEqual(env["WITH_WORKLOAD"], "false")

    def test_dcgm_service_monitor_is_selected_by_prometheus(self):
        monitor = self.values["dcgmExporter"]["serviceMonitor"]
        self.assertEqual(monitor["additionalLabels"]["release"], "kube-prometheus-stack")


class DaskClusterSpecTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_module("devlab_dask", DASK_DIR / "devlab_dask.py")
        self.spec = self.helper.gpu_cluster_spec("analysis", gpu_memory_gib=5,
                                                 task_durations={"gpu_task": "30s"},
                                                 worker_resources={"GPU": 1})
        self.worker = self.spec["spec"]["worker"]
        self.scheduler = self.spec["spec"]["scheduler"]
        self.worker_container = self.worker["spec"]["containers"][0]
        self.scheduler_container = self.scheduler["spec"]["containers"][0]

    def test_workers_start_at_zero_on_gpu_nodes(self):
        self.assertEqual(self.worker["replicas"], 0)
        pod = self.worker["spec"]
        self.assertEqual(pod["runtimeClassName"], "nvidia")
        self.assertEqual(pod["nodeSelector"], {"devlab.io/gpu": "true"})
        self.assertIn({"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}, pod["tolerations"])

    def test_scheduler_runs_on_cpu_nodes_without_gpu_toleration(self):
        pod = self.scheduler["spec"]
        self.assertEqual(pod["nodeSelector"], {"devlab.io/gpu": "false"})
        self.assertNotIn("tolerations", pod)
        self.assertNotIn("nvidia.com/gpu", str(self.scheduler_container.get("resources")))

    def test_gpu_memory_is_shares_and_rmm_pool(self):
        args = self.worker_container["args"]
        # Quantities must be strings: the DaskCluster CRD rejects integers
        for quantities in self.worker_container["resources"].values():
            for value in quantities.values():
                self.assertIsInstance(value, str)
        self.assertEqual(self.worker_container["resources"]["limits"]["nvidia.com/gpu"], "5")
        pool = parse_gib(flag_value(args, "--rmm-pool-size"))
        self.assertEqual(pool, parse_gib(flag_value(args, "--rmm-maximum-pool-size")))
        self.assertLessEqual(pool + self.helper.CUDA_CONTEXT_GIB, 5)
        self.assertLess(parse_gib(flag_value(args, "--device-memory-limit")), pool)
        self.assertEqual(flag_value(args, "--resources"), "GPU=1")
        for size in range(1, 25):
            memory = self.helper.worker_memory(size)
            self.assertLessEqual(parse_gib(memory["pool"]) + self.helper.CUDA_CONTEXT_GIB, max(size, 1))

    def test_scheduler_serves_adaptive_target_and_knows_task_durations(self):
        import ast
        env = {item["name"]: item["value"] for item in self.scheduler_container["env"]}
        routes = ast.literal_eval(env["DASK_DISTRIBUTED__SCHEDULER__HTTP__ROUTES"])
        self.assertIn("distributed.http.scheduler.api", routes)
        self.assertIn("distributed.http.health", routes)
        self.assertEqual(ast.literal_eval(env["DASK_DISTRIBUTED__SCHEDULER__DEFAULT_TASK_DURATIONS"]),
                         {"gpu_task": "30s"})
        # The Dask operator looks up these port names
        ports = {port["name"] for port in self.scheduler["service"]["ports"]}
        self.assertEqual(ports, {"tcp-comm", "http-dashboard"})

    def test_one_image_for_scheduler_workers_and_sample_client(self):
        job = load_documents(DASK_DIR / "sample" / "job.yaml")[0]["spec"]["template"]["spec"]
        images = {self.worker_container["image"], self.scheduler_container["image"], job["containers"][0]["image"]}
        self.assertEqual(images, {self.helper.IMAGE})
        self.assertEqual(job["nodeSelector"], {"devlab.io/gpu": "false"})
        self.assertEqual(job["serviceAccountName"], "dask-client")

    @unittest.skipUnless(importlib.util.find_spec("dask"), "dask not installed")
    def test_clusters_default_to_the_client_pods_namespace(self):
        import tempfile
        import dask
        with tempfile.NamedTemporaryFile("w", suffix="namespace") as f:
            f.write("dask")
            f.flush()
            self.assertEqual(self.helper.default_namespace(f.name), "dask")
            with dask.config.set({"kubernetes.namespace": "other"}):
                self.assertEqual(self.helper.default_namespace(f.name), "other")
        # Outside a pod: None, so the kubeconfig's namespace is used
        self.assertIsNone(self.helper.default_namespace("/nonexistent/namespace"))

    def test_image_pins_the_required_versions(self):
        requirements = (DASK_DIR / "image" / "requirements.txt").read_text()
        pinned = dict(line.split("==") for line in requirements.splitlines()
                      if "==" in line and not line.startswith("#"))
        documented = (REPO_ROOT / "dask_requirements.md")
        if documented.exists():
            for line in documented.read_text().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0].lower() != "python":
                    name = parts[0] + ("[cu12]" if parts[0] == "numba-cuda" else "")
                    self.assertEqual(pinned.get(name), parts[1], f"{parts[0]} differs from dask_requirements.md")


@unittest.skipUnless(importlib.util.find_spec("distributed"), "dask distributed not installed")
class AdaptiveScaleFromZeroTests(unittest.TestCase):
    """The scheduler logic the DaskAutoscaler relies on, with a real Dask scheduler."""

    def adaptive_target(self, task_durations):
        import asyncio
        import dask
        from distributed import Client, Scheduler

        async def target():
            with dask.config.set({"distributed.scheduler.default-task-durations": task_durations}):
                async with Scheduler(dashboard_address=None, port=0) as scheduler:
                    async with Client(scheduler.address, asynchronous=True) as client:
                        futures = [client.submit(gpu_task, i, resources={"GPU": 1}) for i in range(4)]
                        while len(scheduler.unrunnable) + len(scheduler.queued) < 4:
                            await asyncio.sleep(0.05)
                        result = scheduler.adaptive_target()
                        for future in futures:
                            future.cancel()
                        return result

        return asyncio.run(target())

    def test_scales_from_zero_to_one_worker_per_task_with_durations(self):
        self.assertEqual(self.adaptive_target({"gpu_task": "30s"}), 4)

    def test_without_durations_starts_with_one_worker(self):
        self.assertEqual(self.adaptive_target({}), 1)


def gpu_task(i):
    return i


def sleep_task(seconds):
    """CPU stand-in for gpu_task"""
    from distributed import get_worker
    start = time.time()
    time.sleep(seconds)
    return {"worker": get_worker().name, "gpu": "-", "start": start,
            "end": time.time(), "iterations": 1}


class ConcurrencyCheckTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("gpu_concurrency", DASK_DIR / "sample" / "gpu_concurrency.py")

    def result(self, worker, start, end):
        return {"worker": worker, "start": start, "end": end}

    def test_overlapping_tasks_pass(self):
        results = [self.result(f"w{i}", i, 10 + i) for i in range(4)]
        ok, message = self.module.check_concurrent(results, 4)
        self.assertTrue(ok, message)

    def test_sequential_tasks_fail(self):
        results = [self.result(f"w{i}", i * 10, i * 10 + 5) for i in range(4)]
        self.assertFalse(self.module.check_concurrent(results, 4)[0])

    def test_tasks_on_too_few_workers_fail(self):
        results = [self.result("w0", 0, 10) for _ in range(4)]
        self.assertFalse(self.module.check_concurrent(results, 4)[0])

    @unittest.skipUnless(importlib.util.find_spec("distributed"), "dask distributed not installed")
    def test_run_places_one_concurrent_task_per_worker(self):
        from distributed import Client, LocalCluster
        with LocalCluster(n_workers=4, threads_per_worker=1, processes=False, resources={"GPU": 1},
                          dashboard_address=None) as cluster, Client(cluster) as client:
            results = self.module.run(client, 4, sleep_task, 1.0)
        ok, message = self.module.check_concurrent(results, 4)
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
