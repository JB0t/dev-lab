import sys
import unittest
from pathlib import Path

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parents[1]))

from devlab import ADDONS, CONFIG_DIR, cli, parse_cobra_completions, prepare_port_forward, registry_image


class CompletionTests(unittest.TestCase):
    def test_parse_cobra_completions(self):
        items = parse_cobra_completions(
            "pods\tList pods\nservices\tList services\n_activeHelp_ignore me\n:4\n"
        )

        self.assertEqual([item.value for item in items], ["pods", "services"])
        self.assertEqual([item.help for item in items], ["List pods", "List services"])

    def test_completion_command_generates_bash_source(self):
        result = CliRunner().invoke(cli, ["completion", "bash"], prog_name="devlab")

        self.assertEqual(result.exit_code, 0)
        self.assertIn("_devlab_completion", result.output)
        self.assertIn("_DEVLAB_COMPLETE=bash_complete", result.output)


    def test_completion_command_adds_kubectl_alias(self):
        result = CliRunner().invoke(
            cli, ["completion", "bash", "--kubectl-alias", "k"], prog_name="devlab"
        )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("complete -o nosort -F _devlab_alias_k k", result.output)
        self.assertIn('COMP_WORDS=(devlab kubectl "${COMP_WORDS[@]:1}")', result.output)


class PassthroughParsingTests(unittest.TestCase):
    def parse(self, *argv):
        name, *rest = argv
        command = cli.get_command(None, name)
        return command.make_context(name, rest).params

    def test_exec_separator_reaches_kubectl(self):
        self.assertEqual(
            self.parse("kubectl", "-n", "x", "exec", "-it", "pod", "--", "sh")["args"],
            ("-n", "x", "exec", "-it", "pod", "--", "sh"),
        )

    def test_leading_separator_is_still_consumed(self):
        self.assertEqual(
            self.parse("kubectl", "--", "exec", "pod", "--", "ls")["args"],
            ("exec", "pod", "--", "ls"),
        )

    def test_help_is_passed_to_wrapped_tool(self):
        self.assertEqual(self.parse("helm", "--help")["args"], ("--help",))

    def test_build_passes_unknown_options_to_docker(self):
        params = self.parse("build", "-t", "app:1", "--push", "-f", "Dockerfile", ".")
        self.assertEqual(params["image"], "app:1")
        self.assertTrue(params["push_after"])
        self.assertEqual(params["args"], ("-f", "Dockerfile", "."))


class RegistryImageTests(unittest.TestCase):
    def test_prefixes_bare_image(self):
        self.assertEqual(registry_image("app:1"), "localhost:5000/app:1")

    def test_keeps_qualified_image(self):
        self.assertEqual(registry_image("localhost:5000/app:1"), "localhost:5000/app:1")


class PortForwardTests(unittest.TestCase):
    def test_non_port_forward_is_unchanged(self):
        self.assertEqual(prepare_port_forward(["get", "pods"]), (["get", "pods"], [], []))

    def test_publishes_local_port_on_loopback(self):
        args, publish, forwards = prepare_port_forward(
            ["-n", "monitoring", "port-forward", "svc/grafana", "3000:80", "9090"]
        )
        self.assertEqual(
            args,
            ["-n", "monitoring", "port-forward", "--address", "0.0.0.0", "svc/grafana", "3000:80", "9090:9090"],
        )
        self.assertEqual(publish, ["-p", "127.0.0.1:3000:3000", "-p", "127.0.0.1:9090:9090"])
        self.assertEqual(forwards, [("3000", "80"), ("9090", "9090")])

    def test_user_address_becomes_host_bind_address(self):
        args, publish, _ = prepare_port_forward(
            ["port-forward", "-n", "app", "--address", "0.0.0.0", "pod/p", "8080"]
        )
        self.assertEqual(args, ["port-forward", "--address", "0.0.0.0", "-n", "app", "pod/p", "8080:8080"])
        self.assertEqual(publish, ["-p", "0.0.0.0:8080:8080"])

    def test_random_local_port_is_chosen_on_host(self):
        args, publish, forwards = prepare_port_forward(["port-forward", "svc/db", ":5432"])
        local, remote = forwards[0]
        self.assertEqual(remote, "5432")
        self.assertTrue(local.isdigit())
        self.assertEqual(args[-1], f"{local}:5432")
        self.assertEqual(publish, ["-p", f"127.0.0.1:{local}:{local}"])


class AddonTests(unittest.TestCase):
    def test_unknown_addon_is_rejected(self):
        result = CliRunner().invoke(cli, ["addon", "enable", "nope"], prog_name="devlab")
        self.assertEqual(result.exit_code, 2)
        self.assertIn("keda", result.output)

    def test_addon_handlers_exist(self):
        from devlab import DevLabManager
        for spec in ADDONS.values():
            self.assertTrue(callable(getattr(DevLabManager, spec["enable"])))
            self.assertTrue(callable(getattr(DevLabManager, spec["disable"])))

    def test_kwok_templates_are_valid_yaml_after_substitution(self):
        import yaml
        text = (CONFIG_DIR / "addons" / "node-autoscaler" / "kwok-provider.yaml").read_text()
        configmap = yaml.safe_load(text.replace("${ARCH}", "arm64"))
        nodes = yaml.safe_load(configmap["data"]["templates"])["items"]
        for node in nodes:
            labels = node["metadata"]["labels"]
            self.assertIn("kwok-nodegroup", labels)
            self.assertEqual(labels["kubernetes.io/arch"], "arm64")
            self.assertEqual(labels["devlab.io/node-pool"], "kwok")


if __name__ == "__main__":
    unittest.main()