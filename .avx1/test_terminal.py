"""Behavior tests for the fork's child-environment and MCP fixes."""
import os
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


class TerminalTests(unittest.TestCase):
    def test_child_cannot_read_inherited_terminal_credentials(self):
        from open_terminal.env import sanitized_environ
        environment = {**os.environ, "OPEN_TERMINAL_API_KEY": "synthetic-secret",
                       "open_terminal_private": "synthetic-secret", "KEEP_APPLICATION_SETTING": "kept"}
        with patch.dict(os.environ, environment, clear=True):
            child_env = sanitized_environ({"EXTRA_SETTING": "extra"})
        result = subprocess.run([sys.executable, "-c", "import os; assert not any(k.upper().startswith('OPEN_TERMINAL_') for k in os.environ); assert os.environ['KEEP_APPLICATION_SETTING']=='kept'; assert os.environ['EXTRA_SETTING']=='extra'"],
                                env=child_env, capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_stdio_passes_no_network_arguments(self):
        from click.testing import CliRunner
        from open_terminal.cli import main
        received = []
        fake = types.ModuleType("open_terminal.mcp_server")
        fake.mcp = types.SimpleNamespace(run=lambda **kwargs: received.append(kwargs))
        with patch.dict(sys.modules, {"open_terminal.mcp_server": fake}), patch("open_terminal.config.init", return_value={}):
            result = CliRunner().invoke(main, ["mcp", "--transport", "stdio"])
        self.assertEqual(result.exit_code, 0, repr(result.exception))
        self.assertEqual(received, [{"transport": "stdio"}])


if __name__ == "__main__":
    unittest.main()
