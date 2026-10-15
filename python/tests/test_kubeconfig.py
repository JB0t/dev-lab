import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devlab


class KubeconfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root_patch = patch.object(devlab, "PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.runner = devlab.ContainerToolRunner()
        self.config = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [
                {"name": "kind-dev-lab", "cluster": {
                    "server": "https://172.18.0.3:6443",
                    "certificate-authority-data": "test-ca",
                }},
                {"name": "other", "cluster": {"server": "https://other:6443"}},
            ],
            "contexts": [{"name": "kind-dev-lab", "context": {
                "cluster": "kind-dev-lab", "user": "kind-dev-lab",
            }}],
            "current-context": "kind-dev-lab",
            "users": [{"name": "kind-dev-lab", "user": {
                "client-certificate-data": "test-cert",
                "client-key-data": "test-key",
            }}],
        }

    def write_config(self, config):
        self.runner.shared_kubeconfig_path.write_text(yaml.safe_dump(config))

    def read_config(self):
        return yaml.safe_load(self.runner.shared_kubeconfig_path.read_text())

    def test_migrates_only_dev_lab_endpoint(self):
        for old_server in ("https://172.18.0.3:6443", "https://127.0.0.1:6443"):
            with self.subTest(server=old_server):
                config = copy.deepcopy(self.config)
                config["clusters"][0]["cluster"]["server"] = old_server
                self.write_config(config)
                self.runner._ensure_shared_kubeconfig()
                config["clusters"][0]["cluster"]["server"] = (
                    "https://dev-lab-control-plane:6443"
                )
                self.assertEqual(self.read_config(), config)

    def test_unchanged_config_is_not_rewritten(self):
        self.write_config(self.config)
        self.runner._ensure_shared_kubeconfig()
        original_stat = self.runner.shared_kubeconfig_path.stat()
        original_content = self.runner.shared_kubeconfig_path.read_bytes()
        self.runner._ensure_shared_kubeconfig()
        self.assertEqual(self.runner.shared_kubeconfig_path.read_bytes(), original_content)
        self.assertEqual(self.runner.shared_kubeconfig_path.stat().st_mtime_ns,
                         original_stat.st_mtime_ns)

    def test_copies_user_config_without_modifying_source(self):
        user_home = self.root / "home"
        user_config = user_home / ".kube" / "config"
        user_config.parent.mkdir(parents=True)
        user_config.write_text(yaml.safe_dump(self.config))
        original_content = user_config.read_bytes()
        with patch.object(devlab.Path, "home", return_value=user_home):
            self.runner._ensure_shared_kubeconfig()
        self.assertEqual(user_config.read_bytes(), original_content)
        self.assertEqual(self.read_config()["clusters"][0]["cluster"]["server"],
                         "https://dev-lab-control-plane:6443")

    def test_missing_config_creates_empty_config(self):
        with patch.object(devlab.Path, "home", return_value=self.root / "missing"):
            self.runner._ensure_shared_kubeconfig()
        self.assertEqual(self.read_config()["clusters"], [])

    def test_unrelated_config_is_not_rewritten(self):
        self.config["clusters"] = self.config["clusters"][1:]
        self.write_config(self.config)
        original_content = self.runner.shared_kubeconfig_path.read_bytes()
        self.runner._ensure_shared_kubeconfig()
        self.assertEqual(self.runner.shared_kubeconfig_path.read_bytes(), original_content)

    def test_all_container_tools_migrate_before_running(self):
        commands = (
            (self.runner.kubectl, ["get", "nodes"]),
            (self.runner.helm, ["list"]),
            (self.runner.linkerd, ["check"]),
            (self.runner.flux, ["get", "all"]),
        )
        for command, arguments in commands:
            with self.subTest(tool=command.__name__):
                self.write_config(self.config)
                with patch.object(devlab.subprocess, "run") as run:
                    def check_config(*args, **kwargs):
                        self.assertEqual(
                            self.read_config()["clusters"][0]["cluster"]["server"],
                            "https://dev-lab-control-plane:6443",
                        )
                    run.side_effect = check_config
                    command(arguments)
                    run.assert_called_once()


if __name__ == "__main__":
    unittest.main()