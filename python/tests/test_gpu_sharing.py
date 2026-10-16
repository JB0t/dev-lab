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
# A10-24Q vGPU framebuffer; workers' fixed RMM pools must leave headroom for
# CUDA contexts and vGPU-reserved memory
A10_24Q_BYTES = 24 * 10 ** 9
HEADROOM_BYTES = 4 * GIB


def load_documents(path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def device_plugin_config():
    """devicePlugin.config of the GPU Operator values (the time-slicing ConfigMap)."""
    values = yaml.safe_load((GPU_DIR / "gpu-operator-values.yaml").read_text())
    return values["devicePlugin"]["config"]


def time_slicing_replicas():
    plugin_config = device_plugin_config()
    config = yaml.safe_load(plugin_config["data"][plugin_config["default"]])
    resources = config["sharing"]["timeSlicing"]["resources"]
    return {resource["name"]: resource["replicas"] for resource in resources}


def worker_deployment():
    return load_documents(DASK_DIR / "workers.yaml")[0]


def flag_value(args, flag):
    return args[args.index(flag) + 1]


def parse_size(text):
    for suffix, factor in (("GiB", GIB), ("MiB", 1024 ** 2)):
        if text.endswith(suffix):
            return float(text[:-len(suffix)]) * factor
    raise ValueError(text)


class TimeSlicingTests(unittest.TestCase):
    def setUp(self):
        self.values = yaml.safe_load((GPU_DIR / "gpu-operator-values.yaml").read_text())
        self.config = self.values["devicePlugin"]["config"]

    def test_default_config_time_slices_each_gpu_into_four(self):
        self.assertTrue(self.config["create"])
        self.assertEqual(self.config["default"], "time-sliced")
        self.assertEqual(time_slicing_replicas(), {"nvidia.com/gpu": 4})

    def test_time_sliced_config_keeps_resource_name_and_rejects_multi_share(self):
        config = yaml.safe_load(self.config["data"]["time-sliced"])
        time_slicing = config["sharing"]["timeSlicing"]
        self.assertFalse(time_slicing["renameByDefault"])
        self.assertTrue(time_slicing["failRequestsGreaterThanOne"])

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

    def test_dcgm_service_monitor_is_selected_by_prometheus(self):
        monitor = self.values["dcgmExporter"]["serviceMonitor"]
        self.assertEqual(monitor["additionalLabels"]["release"], "kube-prometheus-stack")


class DaskManifestTests(unittest.TestCase):
    def setUp(self):
        self.deployment = worker_deployment()
        self.pod = self.deployment["spec"]["template"]["spec"]
        self.container = self.pod["containers"][0]
        self.args = self.container["args"]

    def test_one_worker_per_time_sliced_share(self):
        self.assertEqual(self.deployment["spec"]["replicas"],
                         time_slicing_replicas()["nvidia.com/gpu"])
        self.assertEqual(self.container["resources"]["limits"]["nvidia.com/gpu"], 1)
        self.assertEqual(self.pod["runtimeClassName"], "nvidia")

    def test_workers_self_limit_gpu_memory_within_a10_24q(self):
        pool = parse_size(flag_value(self.args, "--rmm-pool-size"))
        maximum = parse_size(flag_value(self.args, "--rmm-maximum-pool-size"))
        spill = parse_size(flag_value(self.args, "--device-memory-limit"))
        self.assertEqual(pool, maximum)
        self.assertLess(spill, maximum)
        self.assertEqual(flag_value(self.args, "--set-rmm-allocator-for-libs"), "cupy")
        replicas = self.deployment["spec"]["replicas"]
        self.assertLessEqual(replicas * maximum, A10_24Q_BYTES - HEADROOM_BYTES)

    def test_all_dask_pods_use_same_image_on_gpu_node(self):
        pods = [self.pod,
                load_documents(DASK_DIR / "scheduler.yaml")[0]["spec"]["template"]["spec"],
                load_documents(DASK_DIR / "sample" / "job.yaml")[0]["spec"]["template"]["spec"]]
        self.assertEqual(len({pod["containers"][0]["image"] for pod in pods}), 1)
        for pod in pods:
            self.assertEqual(pod["nodeSelector"], {"nvidia.com/gpu.present": "true"})
            # Keep the image entrypoint, which sets up the conda environment
            self.assertNotIn("command", pod["containers"][0])

    def test_sample_job_expects_every_worker(self):
        job = load_documents(DASK_DIR / "sample" / "job.yaml")[0]
        env = {item["name"]: item["value"] for item in
               job["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(int(env["EXPECTED_WORKERS"]), self.deployment["spec"]["replicas"])


def load_concurrency_module():
    spec = importlib.util.spec_from_file_location(
        "gpu_concurrency", DASK_DIR / "sample" / "gpu_concurrency.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sleep_task(seconds):
    """CPU stand-in for gpu_task"""
    from distributed import get_worker
    start = time.time()
    time.sleep(seconds)
    return {"worker": get_worker().name, "gpu": "-", "start": start,
            "end": time.time(), "iterations": 1}


class ConcurrencyCheckTests(unittest.TestCase):
    def setUp(self):
        self.module = load_concurrency_module()

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
        with LocalCluster(n_workers=4, threads_per_worker=1, processes=False,
                          dashboard_address=None) as cluster, Client(cluster) as client:
            results = self.module.run(client, 4, sleep_task, 1.0)
        ok, message = self.module.check_concurrent(results, 4)
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
