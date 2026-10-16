import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parents[1]))

import devlab
from devlab import (
    CONFIG_DIR, DevLabError, DevLabManager, GPU_OPERATOR_CHART_VERSION, PROJECT_ROOT,
    allocatable_gpus, cli, gpu_kind_config, pods_state,
)

CLUSTER_DIR = PROJECT_ROOT / "cluster"


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def load(name):
    return yaml.safe_load((CLUSTER_DIR / name).read_text())


def nodes_json(**gpus):
    return json.dumps({"items": [
        {"metadata": {"name": name}, "status": {"allocatable": {"cpu": "8", **({"nvidia.com/gpu": count} if count else {})}}}
        for name, count in gpus.items()
    ]})


def manager():
    with patch.object(devlab.ContainerToolRunner, "__init__", lambda self: None):
        result = DevLabManager()
    result.tools = MagicMock()
    result.tools.shared_kubeconfig_dir = Path("/nonexistent")
    return result


class GpuKindConfigTests(unittest.TestCase):
    def test_default_workers_on_each_profile(self):
        workers = load("gpu-workers.yaml")["workers"]
        for profile in ("kind-config.yaml", "kind-config.ci.yaml"):
            with self.subTest(profile=profile):
                base = load(profile)
                config, gpu_nodes = gpu_kind_config(base, workers)

                self.assertEqual(gpu_nodes, {"dev-lab-worker": ["all"]})
                control_plane, gpu_worker, cpu_worker = config["nodes"]
                # Only the GPU Operator label is added to the control plane
                expected_control_plane = dict(base["nodes"][0], labels={
                    "nvidia.com/gpu.deploy.operands": "false", "devlab.io/gpu": "false"})
                self.assertEqual(control_plane, expected_control_plane)
                self.assertEqual(gpu_worker["labels"], {"nvidia.com/gpu.present": "true", "devlab.io/gpu": "true"})
                self.assertEqual(gpu_worker["extraMounts"], [
                    {"hostPath": "/dev/null", "containerPath": "/var/run/nvidia-container-devices/all"}
                ])
                # Only GPU workloads (and GPU Operator operands) run on GPU nodes
                patch = yaml.safe_load(gpu_worker["kubeadmConfigPatches"][0])
                self.assertEqual(patch, {"kind": "JoinConfiguration", "nodeRegistration": {"taints": [
                    {"key": "nvidia.com/gpu", "value": "present", "effect": "NoSchedule"}]}})
                self.assertEqual(cpu_worker, {"role": "worker", "labels": {
                    "nvidia.com/gpu.deploy.operands": "false", "devlab.io/gpu": "false"}})
                for key in base:
                    if key != "nodes":
                        self.assertEqual(config[key], base[key])
                # The profile config itself is not modified
                self.assertEqual(base, load(profile))

    def test_taint_can_be_turned_off(self):
        config, _ = gpu_kind_config(load("kind-config.yaml"), [{"devices": "all", "taint": False}])
        self.assertNotIn("kubeadmConfigPatches", config["nodes"][1])

    def test_explicit_devices_and_node_names(self):
        workers = [{"devices": 0}, {}, {"devices": [1, 2]}]
        config, gpu_nodes = gpu_kind_config(load("kind-config.yaml"), workers)
        self.assertEqual(gpu_nodes, {"dev-lab-worker": ["0"], "dev-lab-worker3": ["1", "2"]})
        self.assertEqual(len(config["nodes"]), 4)
        mounts = [mount["containerPath"] for mount in config["nodes"][3]["extraMounts"]]
        self.assertEqual(mounts, ["/var/run/nvidia-container-devices/1", "/var/run/nvidia-container-devices/2"])

    def test_invalid_values(self):
        base = load("kind-config.yaml")
        for workers in ([], [{}, {}], [{"devices": "first"}], [{"devices": -1}], [{"devices": True}]):
            with self.subTest(workers=workers):
                with self.assertRaises(DevLabError):
                    gpu_kind_config(base, workers)

    def test_allocatable_gpus(self):
        self.assertEqual(allocatable_gpus(nodes_json(**{"dev-lab-worker": "4", "dev-lab-worker2": None})),
                         {"dev-lab-worker": "4"})
        self.assertEqual(allocatable_gpus(nodes_json(**{"dev-lab-worker": "0"})), {})


class GpuPrerequisiteTests(unittest.TestCase):
    def test_docker_without_gpu_injection_shows_setup(self):
        m = manager()
        with patch.object(devlab.subprocess, "run", return_value=completed(1, stderr="could not select device driver")) as run, \
                patch.object(devlab.console, "print") as console_print:
            self.assertFalse(m._check_gpu_prerequisites())
        self.assertIn("/dev/null:/var/run/nvidia-container-devices/all", run.call_args[0][0])
        printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
        self.assertIn("accept-nvidia-visible-devices-as-volume-mounts=true", printed)

    def test_low_inotify_limits_fail_with_fix(self):
        for values, ok in ((("128", "65536"), False), (("8192", "524288"), True)):
            with self.subTest(values=values), \
                    patch.dict(devlab.os.environ, {"DOCKER_HOST": ""}), \
                    patch.object(devlab.Path, "read_text", side_effect=list(values)), \
                    patch.object(devlab.console, "print") as console_print:
                self.assertEqual(manager()._check_inotify_limits(), ok)
            printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
            self.assertEqual("99-devlab-kind.conf" in printed, not ok)

    def test_compute_mode_must_be_default(self):
        for output, ok in (("0, Default\n", True), ("0, Exclusive_Process\n", False)):
            with self.subTest(output=output), \
                    patch.object(devlab.subprocess, "run", return_value=completed(stdout=output)), \
                    patch.object(devlab.console, "print") as console_print:
                self.assertEqual(manager()._check_compute_mode(), ok)
            printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
            self.assertEqual("nvidia-smi -c DEFAULT" in printed, not ok)

    def test_vgpu_license_warning(self):
        cases = (
            ("bare metal", "Product Name : NVIDIA A10\n", False),
            ("licensed vGPU", "    License Status : Licensed (Expiry: 2026-11-1 0:0:0 GMT)\n", False),
            ("unlicensed vGPU", "    License Status : Unlicensed (Restricted)\n", True),
        )
        for name, output, warns in cases:
            with self.subTest(name), \
                    patch.object(devlab.subprocess, "run", return_value=completed(stdout=output)), \
                    patch.object(devlab.console, "print") as console_print:
                manager()._check_vgpu_license()
            printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
            self.assertEqual("throttled" in printed, warns)


class GpuNodeSetupTests(unittest.TestCase):
    def test_existing_cluster_without_gpus_fails_with_hint(self):
        m = manager()
        m.gpu_nodes = {"dev-lab-worker": ["all"]}
        with patch.object(m, "_kind_nodes", return_value=["dev-lab-control-plane", "dev-lab-worker"]), \
                patch.object(devlab.subprocess, "run", return_value=completed(127, stderr="nvidia-smi: not found")), \
                patch.object(devlab.console, "print") as console_print:
            self.assertFalse(m._setup_gpu_nodes())
        printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
        self.assertIn("./devlab cleanup && ./devlab bootstrap --gpu", printed)

    def test_setup_runs_scripts_and_removes_unassigned_devices(self):
        m = manager()
        m.gpu_nodes = {"dev-lab-worker": ["0"]}
        scripts = []

        def run(command, **kwargs):
            if command[:2] == ["docker", "run"]:
                return completed(stdout="GPU 0: A\nGPU 1: B\n")
            if command[-1] == "/proc/driver/nvidia/params":
                return completed(stdout="ModifyDeviceFiles: 0\n")
            if command[-2:] == ["nvidia-smi", "-L"]:
                return completed(stdout="GPU 0: A\n")
            scripts.append(command[-1])
            return completed()

        with patch.object(m, "_kind_nodes", return_value=["dev-lab-control-plane", "dev-lab-worker"]), \
                patch.object(devlab.subprocess, "run", side_effect=run):
            self.assertTrue(m._setup_gpu_nodes())
        joined = "\n".join(scripts)
        self.assertIn("apt-get install -y nvidia-container-toolkit", joined)
        self.assertIn("nvidia-ctk runtime configure --runtime=containerd", joined)
        self.assertIn("rm -rf /dev/nvidia1", joined)
        self.assertNotIn("rm -rf /dev/nvidia0", joined)
        # Params already masked by the toolkit's CDI hook
        self.assertNotIn("umount -R /proc/driver/nvidia", joined)

    def test_failed_toolkit_install_stops(self):
        m = manager()
        m.gpu_nodes = {"dev-lab-worker": ["all"]}

        def run(command, **kwargs):
            if command[-2:] == ["nvidia-smi", "-L"]:
                return completed(stdout="GPU 0: A\n")
            return completed(100, stderr="E: Unable to locate package")

        with patch.object(m, "_kind_nodes", return_value=["dev-lab-worker"]), \
                patch.object(devlab.subprocess, "run", side_effect=run), \
                patch.object(devlab.console, "print"):
            self.assertFalse(m._setup_gpu_nodes())


class GpuOperatorTests(unittest.TestCase):
    def setUp(self):
        self.m = manager()
        self.m._apply_manifest = MagicMock(return_value=True)
        self.m._ensure_namespace = MagicMock(return_value=True)
        self.m._helm_release = MagicMock(return_value=True)
        self.m._gpu_memory_gib = MagicMock(return_value=22)
        self.sleep = patch.object(devlab.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def kubectl(self, *outputs):
        outputs = list(outputs)

        def run(args, **kwargs):
            if args[:3] == ["get", "nodes", "-o"]:
                return completed(stdout=outputs.pop(0) if len(outputs) > 1 else outputs[0])
            return completed()
        self.m.tools.kubectl.side_effect = run

    def test_installs_pinned_chart_and_waits_for_capacity(self):
        self.kubectl(nodes_json(**{"dev-lab-worker": None}), nodes_json(**{"dev-lab-worker": "4"}))
        with patch.object(self.m, "_has_service_monitor_crd", return_value=True):
            self.assertTrue(self.m._setup_gpu_operator())
        args, kwargs = self.m._helm_release.call_args
        self.assertEqual(args[:4], ("gpu-operator", "nvidia/gpu-operator", GPU_OPERATOR_CHART_VERSION, "gpu-operator"))
        self.assertEqual(args[4], CONFIG_DIR / "gpu" / "gpu-operator-values.yaml")
        self.assertNotIn("dcgmExporter.serviceMonitor.enabled=false", kwargs["extra_args"])
        # Helm 4's --wait would block on the ClusterPolicy; capacity is checked instead
        self.assertNotIn("--wait", kwargs["extra_args"])
        self.m._apply_manifest.assert_called_once_with(CONFIG_DIR / "gpu" / "nvidia-runtimeclass.yaml")
        # One time-slicing share per GiB of GPU memory
        values = yaml.safe_load(kwargs["values_text"])
        time_sliced = yaml.safe_load(values["devicePlugin"]["config"]["data"]["time-sliced"])
        self.assertEqual(time_sliced["sharing"]["timeSlicing"]["resources"][0]["replicas"], 22)

    def test_service_monitor_off_without_monitoring_stack(self):
        self.kubectl(nodes_json(**{"dev-lab-worker": "4"}))
        with patch.object(self.m, "_has_service_monitor_crd", return_value=False):
            self.assertTrue(self.m._setup_gpu_operator())
        self.assertIn("dcgmExporter.serviceMonitor.enabled=false", self.m._helm_release.call_args.kwargs["extra_args"])

    def test_fails_without_capacity(self):
        self.kubectl(nodes_json(**{"dev-lab-worker": "0"}))
        with patch.object(self.m, "_has_service_monitor_crd", return_value=True), \
                patch.object(devlab.console, "print"):
            self.assertFalse(self.m._setup_gpu_operator())


def pod(name, ready=True, waiting=None, phase="Running"):
    status = {"phase": phase, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
              "containerStatuses": [{"name": "c", "state": {"waiting": {"reason": waiting}} if waiting else {"running": {}}}]}
    return {"metadata": {"name": name}, "status": status}


class PodStateTests(unittest.TestCase):
    def test_counts_and_broken_pods(self):
        state, broken = pods_state(json.dumps({"items": [
            pod("grafana-1"), pod("job-1", ready=False, phase="Succeeded"), pod("prometheus-0", ready=False)]}))
        self.assertEqual((state["pods"], state["ready"], broken), (3, 2, None))
        self.assertIn("prometheus-0", state["names"])

        _, broken = pods_state(json.dumps({"items": [pod("grafana-1", ready=False, waiting="CrashLoopBackOff")]}))
        self.assertIn("grafana-1: container c is CrashLoopBackOff", broken)
        _, broken = pods_state(json.dumps({"items": [pod("grafana-1", ready=False, waiting="ContainerCreating")]}))
        self.assertIsNone(broken)

    def test_wait_for_pods_fails_fast_and_needs_required_pods(self):
        m = manager()
        responses = iter([
            json.dumps({"items": [pod("kube-prometheus-stack-grafana-x")]}),            # prometheus not created yet
            json.dumps({"items": [pod("kube-prometheus-stack-grafana-x"), pod("prometheus-0")]}),
        ])
        m.tools.kubectl.side_effect = lambda *a, **k: completed(stdout=next(responses))
        with patch.object(devlab.time, "sleep"), patch.object(devlab.console, "print"):
            self.assertTrue(m._wait_for_pods("monitoring", required=["kube-prometheus-stack-grafana", "prometheus-"]))
        self.assertEqual(m.tools.kubectl.call_count, 2)

        m.tools.kubectl.side_effect = lambda *a, **k: completed(
            stdout=json.dumps({"items": [pod("grafana-1", ready=False, waiting="ImagePullBackOff")]}))
        m.tools.kubectl.call_count = 0
        with patch.object(devlab.time, "sleep"), patch.object(devlab.console, "print"):
            self.assertFalse(m._wait_for_pods("monitoring"))
        self.assertEqual(m.tools.kubectl.call_count, 1)


class GpuBootstrapTests(unittest.TestCase):
    def test_monitoring_failure_is_reported_at_the_end(self):
        m = manager()
        for name in ("check_docker", "_check_gpu_prerequisites", "_create_cluster",
                     "_configure_kind_node_certificates", "_setup_gpu_nodes", "_setup_registry",
                     "_setup_metrics_server", "_setup_ingress", "_setup_gpu_operator"):
            setattr(m, name, MagicMock(return_value=True))
        m._deploy_monitoring = MagicMock(return_value=False)
        m._has_service_monitor_crd = MagicMock(return_value=False)
        with patch.object(devlab, "show_access_points"), patch.object(devlab.console, "print") as console_print:
            self.assertFalse(m.bootstrap(monitoring=True, krew=False, gpu=True))
        m._setup_gpu_operator.assert_called_once_with()
        printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
        self.assertIn("these components failed", printed)
        self.assertIn("monitoring stack", printed)

    def test_gpu_steps_run_in_order(self):
        m = manager()
        calls = []
        for name in ("check_docker", "_check_gpu_prerequisites", "_create_cluster",
                     "_configure_kind_node_certificates", "_setup_gpu_nodes", "_setup_registry",
                     "_setup_metrics_server", "_setup_ingress", "_deploy_monitoring", "_setup_gpu_operator"):
            setattr(m, name, MagicMock(return_value=True, side_effect=lambda *a, _n=name, **k: calls.append(_n) or True))
        with patch.object(devlab, "show_access_points"), patch.object(devlab.console, "print"):
            self.assertTrue(m.bootstrap(monitoring=True, krew=False, gpu=True))
        self.assertEqual(calls, [
            "check_docker", "_check_gpu_prerequisites", "_create_cluster",
            "_configure_kind_node_certificates", "_setup_gpu_nodes", "_setup_registry",
            "_setup_metrics_server", "_setup_ingress", "_deploy_monitoring", "_setup_gpu_operator",
        ])
        m._create_cluster.assert_called_once_with(gpu=True)

    def test_cli_flags(self):
        with patch.object(DevLabManager, "bootstrap", return_value=True) as bootstrap:
            result = CliRunner().invoke(cli, ["bootstrap", "--gpu", "--no-krew"])
        self.assertEqual(result.exit_code, 0, result.output)
        bootstrap.assert_called_once_with(monitoring=None, krew=False, gpu=True)

        with patch.object(DevLabManager, "_setup_gpu_operator", return_value=True) as setup:
            result = CliRunner().invoke(cli, ["gpu-operator"])
        self.assertEqual(result.exit_code, 0, result.output)
        setup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
