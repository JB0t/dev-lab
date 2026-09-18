import sys
import unittest
from pathlib import Path

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parents[1]))

from devlab import cli, parse_cobra_completions


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


if __name__ == "__main__":
    unittest.main()