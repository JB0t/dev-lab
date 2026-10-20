import contextlib
import importlib.util
import io
import json
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

    def test_mps_config_shares_the_gpu_in_equal_slices(self):
        mps = yaml.safe_load(self.config["data"]["mps"])["sharing"]["mps"]
        self.assertFalse(mps["renameByDefault"])
        # A share is a fixed slice (1/replicas of memory and SMs): a pod takes exactly one
        self.assertTrue(mps["failRequestsGreaterThanOne"])
        self.assertEqual(mps["resources"], [{"name": "nvidia.com/gpu", "replicas": 4}])
        self.assertEqual(self.config["default"], "time-sliced")

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

    def test_gpu_shares_default_to_one_per_gib_or_a_fixed_slice(self):
        limits = self.worker_container["resources"]["limits"]
        self.assertEqual(limits["nvidia.com/gpu"], "5")
        # MPS: one share of the GPU, with the slice's memory for the RMM pool
        spec = self.helper.gpu_cluster_spec("mps", gpu_memory_gib=5, gpu_shares=1)
        container = spec["spec"]["worker"]["spec"]["containers"][0]
        self.assertEqual(container["resources"]["limits"]["nvidia.com/gpu"], "1")
        self.assertEqual(flag_value(container["args"], "--rmm-pool-size"), self.helper.worker_memory(5)["pool"])
        with self.assertRaises(ValueError):
            self.helper.gpu_cluster_spec("mps", gpu_memory_gib=5, gpu_shares=0)

    def test_workers_declare_gpu_resource_by_default(self):
        args = self.helper.gpu_cluster_spec("run", gpu_memory_gib=2)["spec"]["worker"]["spec"]["containers"][0]["args"]
        self.assertEqual(flag_value(args, "--resources"), "GPU=1")
        args = self.helper.gpu_cluster_spec("run", gpu_memory_gib=2, worker_resources={})["spec"]["worker"]["spec"]["containers"][0]["args"]
        self.assertNotIn("--resources", args)

    def test_standing_cluster_command_line_resources(self):
        def worker_args(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(self.helper.main(["gpu", *argv]), 0)
            cluster = json.loads(out.getvalue())["items"][0]
            return cluster["spec"]["worker"]["spec"]["containers"][0]["args"]
        self.assertEqual(flag_value(worker_args(), "--resources"), "GPU=1")
        self.assertEqual(flag_value(worker_args("--resources", "GPU=1,MEM=2.5"), "--resources"), "GPU=1 MEM=2.5")
        self.assertNotIn("--resources", worker_args("--resources", "none"))

    def test_standing_cluster_command_line_gpu_shares(self):
        def gpu_limit(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(self.helper.main(["gpu", *argv]), 0)
            cluster = json.loads(out.getvalue())["items"][0]
            return cluster["spec"]["worker"]["spec"]["containers"][0]["resources"]["limits"]["nvidia.com/gpu"]
        self.assertEqual(gpu_limit("--gpu-memory-gib", "3"), "3")
        self.assertEqual(gpu_limit("--gpu-memory-gib", "5", "--gpu-shares", "1"), "1")

    def test_worker_env_volumes_and_scheduler_settings_are_optional(self):
        self.assertNotIn("volumes", self.worker["spec"])
        self.assertNotIn("envFrom", self.worker["spec"]["containers"][0])
        self.assertNotIn("idleTimeout", self.spec["spec"])
        volumes = [{"name": "code", "configMap": {"name": "code"}}]
        mounts = [{"name": "code", "mountPath": "/code"}]
        env = [{"name": "PYTHONPATH", "value": "/code"}]
        env_from = [{"configMapRef": {"name": "worker-env"}}]
        spec = self.helper.gpu_cluster_spec("run", gpu_memory_gib=2, worker_env=env, worker_env_from=env_from,
                                            worker_volumes=volumes,
                                            worker_volume_mounts=mounts, unknown_task_duration="5m",
                                            idle_timeout=600)
        worker = spec["spec"]["worker"]["spec"]
        self.assertEqual(worker["volumes"], volumes)
        self.assertEqual(worker["containers"][0]["volumeMounts"], mounts)
        self.assertEqual(worker["containers"][0]["env"], env)
        self.assertEqual(worker["containers"][0]["envFrom"], env_from)
        self.assertEqual(spec["spec"]["idleTimeout"], 600)
        scheduler_env = {item["name"]: item["value"]
                         for item in spec["spec"]["scheduler"]["spec"]["containers"][0]["env"]}
        self.assertEqual(scheduler_env["DASK_DISTRIBUTED__SCHEDULER__UNKNOWN_TASK_DURATION"], "5m")

    def test_standing_cluster_has_a_fixed_scheduler_address_and_scales_from_zero(self):
        import contextlib
        import io
        import json
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.helper.main(["gpu", "--workers", "3", "--gpu-memory-gib", "2"]), 0)
        manifests = json.loads(out.getvalue())
        self.assertEqual(manifests["kind"], "List")
        cluster, autoscaler, ingress = manifests["items"]
        self.assertEqual(cluster["kind"], "DaskCluster")
        self.assertEqual(cluster["spec"]["worker"]["replicas"], 0)
        self.assertEqual(autoscaler["spec"], {"cluster": "gpu", "minimum": 0, "maximum": 3})
        service = cluster["spec"]["scheduler"]["service"]
        self.assertEqual(service["type"], "NodePort")
        self.assertEqual(service["ports"][0]["nodePort"], self.helper.STANDING_SCHEDULER_NODE_PORT)
        self.assertEqual(service["ports"][1]["nodePort"], self.helper.STANDING_DASHBOARD_NODE_PORT)
        env = {item["name"]: item["value"] for item in cluster["spec"]["scheduler"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["DASK_DISTRIBUTED__SCHEDULER__UNKNOWN_TASK_DURATION"], "1m")
        worker_args = cluster["spec"]["worker"]["spec"]["containers"][0]["args"]
        self.assertFalse([arg for arg in worker_args if arg.startswith("--rmm")])
        backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
        self.assertEqual(backend, {"name": "gpu-scheduler", "port": {"number": self.helper.DASHBOARD_PORT}})
        self.assertEqual(ingress["spec"]["rules"][0]["host"], "gpu.dask.localhost")

    def test_kind_publishes_the_standing_scheduler_on_host_port_8786(self):
        sys.path.insert(0, str(Path(__file__).parents[1]))
        import devlab
        config = yaml.safe_load((REPO_ROOT / "cluster" / "kind-config.yaml").read_text())
        gpu_config, _ = devlab.gpu_kind_config(config, [{"devices": 0}, {}])
        for kind_config in (config, gpu_config):
            mappings = kind_config["nodes"][0]["extraPortMappings"]
            for node_port, host_port in ((self.helper.STANDING_SCHEDULER_NODE_PORT, 8786),
                                         (self.helper.STANDING_DASHBOARD_NODE_PORT, 8787)):
                mapping = [m for m in mappings if m["containerPort"] == node_port]
                self.assertEqual(mapping, [{"containerPort": node_port, "hostPort": host_port,
                                            "listenAddress": "0.0.0.0", "protocol": "TCP"}])

    def test_rmm_pool_can_be_turned_off(self):
        spec = self.helper.gpu_cluster_spec("xgb", gpu_memory_gib=5, rmm_pool=False)
        container = spec["spec"]["worker"]["spec"]["containers"][0]
        self.assertFalse([arg for arg in container["args"] if arg.startswith("--rmm")])
        self.assertEqual(container["resources"]["limits"]["nvidia.com/gpu"], "5")

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


def assigned_literal(path, name):
    """Value of a module-level `name = <literal>` in a Python file, without importing it."""
    import ast
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


class DagsterAddonTests(unittest.TestCase):
    """Dagster (devlab addon enable dagster): code location, run pods and Dask workers line up."""

    def setUp(self):
        self.values = yaml.safe_load((REPO_ROOT / "config" / "addons" / "dagster" / "values.yaml").read_text())
        self.deployment = self.values["dagster-user-deployments"]["deployments"][0]
        self.definitions = DASK_DIR / "dagster" / "definitions.py"

    def test_ui_is_published_through_traefik(self):
        ingress = self.values["ingress"]
        self.assertTrue(ingress["enabled"])
        self.assertEqual(ingress["ingressClassName"], "traefik")
        self.assertEqual(ingress["dagsterWebserver"]["host"], "dagster.localhost")

    def test_code_location_loads_mounted_definitions(self):
        sys.path.insert(0, str(Path(__file__).parents[1]))
        import devlab
        self.assertEqual(self.deployment["image"]["repository"] + ":" + self.deployment["image"]["tag"],
                         assigned_literal(DASK_DIR / "devlab_dask.py", "IMAGE"))
        self.assertEqual(self.deployment["codeServerArgs"], ["--python-file", "/dagster/definitions.py"])
        self.assertTrue(self.deployment["includeConfigInLaunchedRuns"]["enabled"])
        self.assertEqual(self.values["dagster-user-deployments"]["serviceAccount"],
                         {"create": False, "name": "dask-client"})
        self.assertIn("dagster", devlab.ADDONS)
        requirements = (DASK_DIR / "image" / "requirements.txt").read_text()
        self.assertIn(f"dagster=={devlab.DAGSTER_CHART_VERSION}\n", requirements)

    def test_run_pods_and_dask_workers_get_the_same_code(self):
        kustomization = yaml.safe_load((DASK_DIR / "kustomization.yaml").read_text())
        generated = {item["name"]: [Path(f).name for f in item["files"]]
                     for item in kustomization["configMapGenerator"]}
        for item in kustomization["configMapGenerator"]:
            for file in item["files"]:
                self.assertTrue((DASK_DIR / file).exists(), file)
        self.assertIn("definitions.py", generated["devlab-dagster"])
        self.assertIn("postgres_io_manager.py", generated["devlab-dagster"])
        self.assertIn("gpu_concurrency.py", generated["devlab-dagster"])
        self.assertEqual(self.deployment["volumes"], assigned_literal(self.definitions, "WORKER_VOLUMES"))
        self.assertEqual(self.deployment["volumeMounts"],
                         assigned_literal(self.definitions, "WORKER_VOLUME_MOUNTS"))
        for volume in self.deployment["volumes"]:
            self.assertIn(volume["configMap"]["name"], generated)
        pythonpath = {item["name"]: item.get("value") for item in self.deployment["env"]}["PYTHONPATH"]
        worker_env = {item["name"]: item for item in assigned_literal(self.definitions, "WORKER_ENV")}
        self.assertEqual(worker_env["PYTHONPATH"]["value"], pythonpath)
        self.assertEqual(worker_env["DAGSTER_PG_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"],
                         "dagster-postgresql-secret")

    def test_postgres_replaces_the_unpublished_bitnami_chart(self):
        postgres = self.values["postgresql"]
        self.assertFalse(postgres["enabled"])
        self.assertEqual(postgres["postgresqlScheme"], "postgresql+psycopg2")
        manifests = {item["kind"]: item for item in self.values["extraManifests"]}
        self.assertEqual(manifests["Service"]["metadata"]["name"], postgres["postgresqlHost"])
        container = manifests["StatefulSet"]["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["image"], "docker.io/library/postgres:" + postgres["image"]["tag"])


@unittest.skipUnless(importlib.util.find_spec("distributed"), "dask distributed not installed")
class AdaptiveScaleFromZeroTests(unittest.TestCase):
    """The scheduler logic the DaskAutoscaler relies on, with a real Dask scheduler."""

    def adaptive_target(self, task_durations, unknown_task_duration="500ms", resources={"GPU": 1}):
        import asyncio
        import dask
        from distributed import Client, Scheduler

        async def target():
            with dask.config.set({"distributed.scheduler.default-task-durations": task_durations,
                                  "distributed.scheduler.unknown-task-duration": unknown_task_duration}):
                async with Scheduler(dashboard_address=None, port=0) as scheduler:
                    async with Client(scheduler.address, asynchronous=True) as client:
                        futures = [client.submit(gpu_task, i, resources=resources) for i in range(4)]
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

    def test_standing_cluster_task_duration_scales_unknown_tasks_from_zero(self):
        # Clients of a standing cluster send tasks the scheduler knows nothing about
        self.assertEqual(self.adaptive_target({}, unknown_task_duration="1m", resources=None), 4)


def gpu_task(i):
    return i


def sleep_task(seconds):
    """CPU stand-in for gpu_task"""
    from distributed import get_worker
    start = time.time()
    time.sleep(seconds)
    return {"worker": get_worker().name, "gpu": "-", "start": start,
            "end": time.time(), "rounds": 1}


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
            results = self.module.run(client, 4, sleep_task, 1.0, resources={"GPU": 1})
        ok, message = self.module.check_concurrent(results, 4)
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
