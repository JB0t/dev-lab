import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devlab


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def nodes_json(*gpu_counts):
    items = []
    for index, count in enumerate(gpu_counts):
        allocatable = {"cpu": "8"}
        if count is not None:
            allocatable["nvidia.com/gpu"] = count
        items.append({
            "metadata": {"name": f"dev-lab-worker{index or ''}"},
            "status": {"allocatable": allocatable},
        })
    return json.dumps({"items": items})


class GpuTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root_patch = patch.object(devlab, "PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.manager = devlab.DevLabManager()

    def write_nvkind_config(self):
        cluster_dir = self.root / "cluster"
        cluster_dir.mkdir()
        (cluster_dir / "nvkind-config-template.yaml").write_text("kind: Cluster\n")
        (cluster_dir / "nvkind-values.yaml").write_text("workers: []\n")

    def test_nvkind_uses_shared_kubeconfig(self):
        with patch.object(devlab.subprocess, "run", return_value=completed()) as run:
            self.manager.tools.nvkind(["cluster", "list"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["nvkind", "cluster", "list"])
        self.assertEqual(kwargs["env"]["KUBECONFIG"],
                         str(self.root / ".kube" / "config"))

    def test_create_gpu_cluster_uses_repo_template_and_values(self):
        self.write_nvkind_config()
        with patch.object(self.manager.tools, "nvkind", return_value=completed()) as nvkind:
            self.assertTrue(self.manager._create_gpu_cluster())
        args = nvkind.call_args[0][0]
        self.assertEqual(args[:4], ["cluster", "create", "--name", "dev-lab"])
        self.assertIn(str(self.root / "cluster" / "nvkind-config-template.yaml"), args)
        self.assertIn(str(self.root / "cluster" / "nvkind-values.yaml"), args)

    def test_create_gpu_cluster_tolerates_error_when_cluster_exists(self):
        self.write_nvkind_config()
        with patch.object(self.manager.tools, "nvkind", return_value=completed(1)), \
                patch.object(self.manager.tools, "kind",
                             return_value=completed(stdout="dev-lab\n")):
            self.assertTrue(self.manager._create_gpu_cluster())

    def test_create_gpu_cluster_fails_when_cluster_missing(self):
        self.write_nvkind_config()
        with patch.object(self.manager.tools, "nvkind", return_value=completed(1)), \
                patch.object(self.manager.tools, "kind",
                             return_value=completed(stdout="dev-lab-old\n")):
            self.assertFalse(self.manager._create_gpu_cluster())

    def test_create_gpu_cluster_fails_without_config(self):
        with patch.object(self.manager.tools, "nvkind") as nvkind:
            self.assertFalse(self.manager._create_gpu_cluster())
        nvkind.assert_not_called()

    def test_gpu_prerequisites_report_missing_tools(self):
        with patch.object(devlab.platform, "system", return_value="Linux"), \
                patch.object(devlab.shutil, "which",
                             side_effect=lambda tool: None if tool == "nvkind" else f"/usr/bin/{tool}"), \
                patch.object(devlab.subprocess, "run") as run:
            self.assertFalse(self.manager._check_gpu_prerequisites())
        run.assert_not_called()

    def test_gpu_prerequisites_check_volume_mount_injection(self):
        results = [completed(stdout="GPU 0: NVIDIA RTX\n"), completed(stdout=""),
                   completed(1, stderr="no GPUs")]
        with patch.object(devlab.platform, "system", return_value="Linux"), \
                patch.object(devlab.shutil, "which", return_value="/usr/bin/tool"), \
                patch.object(devlab.subprocess, "run", side_effect=results) as run:
            self.assertFalse(self.manager._check_gpu_prerequisites())
        docker_args = run.call_args_list[2][0][0]
        self.assertIn("/dev/null:/var/run/nvidia-container-devices/all", docker_args)

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
                self.manager._check_vgpu_license()
            printed = " ".join(str(call.args[0]) for call in console_print.call_args_list)
            self.assertEqual("throttled" in printed, warns)

    def test_gpu_plugin_cli_runs_device_plugin_setup(self):
        with patch.object(devlab.DevLabManager, "_setup_gpu_device_plugin", return_value=True) as setup:
            result = CliRunner().invoke(devlab.cli, ["gpu-plugin"])
        self.assertEqual(result.exit_code, 0)
        setup.assert_called_once_with()

    def test_gpu_prerequisites_reject_non_linux(self):
        with patch.object(devlab.platform, "system", return_value="Darwin"), \
                patch.object(devlab.shutil, "which") as which:
            self.assertFalse(self.manager._check_gpu_prerequisites())
        which.assert_not_called()

    def test_device_plugin_waits_for_gpu_capacity(self):
        node_results = [completed(stdout=nodes_json(None, "0")),
                        completed(stdout=nodes_json("1", None))]
        kubectl_results = [completed()] + node_results
        with patch.object(self.manager.tools, "kubectl", side_effect=kubectl_results), \
                patch.object(self.manager.tools, "helm", return_value=completed()) as helm, \
                patch.object(devlab.time, "sleep"):
            self.assertTrue(self.manager._setup_gpu_device_plugin())
        helm_args = helm.call_args[0][0]
        self.assertIn(devlab.NVIDIA_DEVICE_PLUGIN_VERSION, helm_args)
        self.assertIn("/workspace/config/gpu/nvidia-device-plugin-values.yaml", helm_args)

    def test_device_plugin_fails_without_gpu_capacity(self):
        def kubectl(args, **kwargs):
            return completed(stdout=nodes_json("0", None))
        with patch.object(self.manager.tools, "kubectl", side_effect=kubectl), \
                patch.object(self.manager.tools, "helm", return_value=completed()), \
                patch.object(devlab.time, "sleep"):
            self.assertFalse(self.manager._setup_gpu_device_plugin())

    def test_bootstrap_cli_gpu_flag(self):
        for cli_args, gpu in (([], False), (["--gpu"], True)):
            with self.subTest(args=cli_args), \
                    patch.object(devlab.DevLabManager, "bootstrap", return_value=True) as bootstrap:
                result = CliRunner().invoke(devlab.cli, ["bootstrap"] + cli_args)
                self.assertEqual(result.exit_code, 0)
                bootstrap.assert_called_once_with(gpu=gpu)


class NvkindTemplateTests(unittest.TestCase):
    """Rendered nvkind config must keep the kind-config.yaml shape"""

    def test_template_matches_kind_config_outside_gpu_workers(self):
        cluster_dir = Path(__file__).resolve().parents[2] / "cluster"
        template = (cluster_dir / "nvkind-config-template.yaml").read_text()
        kind_config = yaml_without_workers(
            (cluster_dir / "kind-config.yaml").read_text())
        # Drop the Go template worker block; the rest must be plain YAML
        start = template.index("{{- range $.workers }}")
        end = template.rindex("{{- end }}") + len("{{- end }}")
        rendered = yaml_without_workers(template[:start] + template[end:])
        self.assertEqual(rendered, kind_config)


def yaml_without_workers(text):
    config = yaml.safe_load(text)
    config["nodes"] = [node for node in config["nodes"] if node["role"] != "worker"]
    return config


if __name__ == "__main__":
    unittest.main()
