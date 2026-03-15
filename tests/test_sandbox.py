"""Tests for the sandbox module — policy, container runner, manager, and tool."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from analyst.sandbox.container_runner import ContainerResult, ContainerRunner
from analyst.sandbox.limits import SandboxLimits
from analyst.sandbox.manager import SandboxManager
from analyst.sandbox.policy import PolicyViolation, validate_code
from analyst.tools._python_analysis import PythonAnalysisHandler, build_python_analysis_tool


# ---------------------------------------------------------------------------
# policy.py
# ---------------------------------------------------------------------------

class TestPolicy(unittest.TestCase):
    def test_allows_numpy_import(self):
        validate_code("import numpy as np\nresult = np.mean([1, 2, 3])")

    def test_allows_pandas_import(self):
        validate_code("import pandas as pd\ndf = pd.DataFrame({'a': [1]})\nresult = df.to_dict()")

    def test_allows_scipy_import(self):
        validate_code("from scipy import stats\nresult = stats.norm.cdf(0)")

    def test_allows_matplotlib_import(self):
        validate_code("import matplotlib.pyplot as plt\nresult = 'ok'")

    def test_allows_basic_arithmetic(self):
        validate_code("result = sum([1, 2, 3]) / 3")

    def test_blocks_os_import(self):
        with self.assertRaises(PolicyViolation):
            validate_code("import os")

    def test_blocks_os_path_import(self):
        with self.assertRaises(PolicyViolation):
            validate_code("import os.path")

    def test_blocks_subprocess_import(self):
        with self.assertRaises(PolicyViolation):
            validate_code("import subprocess")

    def test_blocks_subprocess_from_import(self):
        with self.assertRaises(PolicyViolation):
            validate_code("from subprocess import run")

    def test_blocks_socket_import(self):
        with self.assertRaises(PolicyViolation):
            validate_code("import socket")

    def test_blocks_eval_call(self):
        with self.assertRaises(PolicyViolation):
            validate_code("result = eval('1+1')")

    def test_blocks_exec_call(self):
        with self.assertRaises(PolicyViolation):
            validate_code("exec('print(1)')")

    def test_blocks_open_call(self):
        with self.assertRaises(PolicyViolation):
            validate_code("f = open('/etc/passwd')")

    def test_blocks_dunder_subclasses(self):
        with self.assertRaises(PolicyViolation):
            validate_code("x = ().__class__.__subclasses__()")

    def test_blocks_dunder_globals(self):
        with self.assertRaises(PolicyViolation):
            validate_code("x = foo.__globals__")

    def test_blocks_dunder_builtins(self):
        with self.assertRaises(PolicyViolation):
            validate_code("x = foo.__builtins__")

    def test_blocks_importlib(self):
        with self.assertRaises(PolicyViolation):
            validate_code("import importlib")

    def test_blocks_pickle(self):
        with self.assertRaises(PolicyViolation):
            validate_code("import pickle")

    def test_syntax_error_raises_policy_violation(self):
        with self.assertRaises(PolicyViolation):
            validate_code("def f(\n")

    def test_blocks_breakpoint(self):
        with self.assertRaises(PolicyViolation):
            validate_code("breakpoint()")

    def test_blocks_input(self):
        with self.assertRaises(PolicyViolation):
            validate_code("x = input('>')")


# ---------------------------------------------------------------------------
# container_runner.py
# ---------------------------------------------------------------------------

class TestContainerRunner(unittest.TestCase):
    def _make_runner(self, **overrides):
        limits = SandboxLimits()
        return ContainerRunner(limits, **overrides)

    def test_is_available_true(self):
        runner = self._make_runner(which=lambda cmd: "/usr/bin/docker")
        self.assertTrue(runner.is_available())

    def test_is_available_false(self):
        runner = self._make_runner(which=lambda cmd: None)
        self.assertFalse(runner.is_available())

    def test_successful_run_parses_json(self):
        stdout_json = json.dumps({"success": True, "result": 42, "stdout": "", "error": ""})
        mock_runner = MagicMock(return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=stdout_json, stderr="",
        ))
        cr = self._make_runner(runner=mock_runner)
        result = cr.run({"code": "result = 42"})
        self.assertTrue(result.success)
        self.assertEqual(result.result, 42)

    def test_timeout_returns_timed_out(self):
        mock_runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=30))
        cr = self._make_runner(runner=mock_runner)
        result = cr.run({"code": "import time; time.sleep(999)"})
        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)

    def test_docker_not_found_returns_error(self):
        mock_runner = MagicMock(side_effect=FileNotFoundError("docker"))
        cr = self._make_runner(runner=mock_runner)
        result = cr.run({"code": "result = 1"})
        self.assertFalse(result.success)
        self.assertIn("not installed", result.error)

    def test_no_host_env_vars_passed(self):
        mock_runner = MagicMock(return_value=subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"success": True, "result": None, "stdout": "", "error": ""}),
            stderr="",
        ))
        cr = self._make_runner(runner=mock_runner)
        cr.run({"code": "result = 1"})
        call_kwargs = mock_runner.call_args
        self.assertEqual(call_kwargs.kwargs.get("env") or call_kwargs[1].get("env"), {})

    def test_docker_flags_include_security_constraints(self):
        mock_runner = MagicMock(return_value=subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"success": True, "result": None, "stdout": "", "error": ""}),
            stderr="",
        ))
        cr = self._make_runner(runner=mock_runner)
        cr.run({"code": "result = 1"})
        cmd = mock_runner.call_args[0][0]
        self.assertIn("--network", cmd)
        self.assertIn("none", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("--tmpfs", cmd)
        self.assertIn("--memory=512m", cmd)
        self.assertIn("--cpus=1", cmd)
        self.assertIn("--rm", cmd)

    def test_nonzero_exit_code_returns_error(self):
        mock_runner = MagicMock(return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="OOM killed",
        ))
        cr = self._make_runner(runner=mock_runner)
        result = cr.run({"code": "result = 1"})
        self.assertFalse(result.success)
        self.assertIn("OOM", result.error)


# ---------------------------------------------------------------------------
# manager.py
# ---------------------------------------------------------------------------

class TestSandboxManager(unittest.TestCase):
    def _make_manager(self, *, docker_available=True, container_result=None):
        mock_runner = MagicMock()
        if container_result:
            stdout_json = json.dumps({
                "success": container_result.get("success", True),
                "result": container_result.get("result"),
                "stdout": container_result.get("stdout", ""),
                "error": container_result.get("error", ""),
            })
            mock_runner.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=stdout_json, stderr="",
            )
        mgr = SandboxManager(runner=mock_runner)
        if not docker_available:
            mgr._container._which = lambda cmd: None
        return mgr, mock_runner

    def test_policy_violation_blocks_execution(self):
        mgr, mock_runner = self._make_manager()
        result = mgr.run_python("import os; os.system('rm -rf /')")
        self.assertEqual(result["status"], "error")
        self.assertIn("policy violation", result["error"].lower())
        mock_runner.assert_not_called()

    def test_docker_unavailable_returns_error(self):
        mgr, _ = self._make_manager(docker_available=False)
        result = mgr.run_python("result = 42")
        self.assertEqual(result["status"], "error")
        self.assertIn("Docker", result["error"])

    def test_successful_execution(self):
        mgr, _ = self._make_manager(container_result={"success": True, "result": 3.0})
        result = mgr.run_python("import numpy as np; result = np.mean([1,2,3,4,5])")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], 3.0)

    def test_data_passed_through(self):
        mgr, mock_runner = self._make_manager(container_result={"success": True, "result": 6})
        mgr.run_python("result = sum(data['values'])", data={"values": [1, 2, 3]})
        input_json = mock_runner.call_args.kwargs.get("input") or mock_runner.call_args[1].get("input")
        payload = json.loads(input_json)
        self.assertEqual(payload["data"], {"values": [1, 2, 3]})


# ---------------------------------------------------------------------------
# _python_analysis.py (tool)
# ---------------------------------------------------------------------------

class TestPythonAnalysisTool(unittest.TestCase):
    def test_empty_code_returns_error(self):
        mock_manager = MagicMock()
        handler = PythonAnalysisHandler(mock_manager)
        result = handler({"code": ""})
        self.assertEqual(result["status"], "error")
        self.assertIn("code is required", result["error"])
        mock_manager.run_python.assert_not_called()

    def test_handler_delegates_to_manager(self):
        mock_manager = MagicMock()
        mock_manager.run_python.return_value = {"status": "ok", "result": 42}
        handler = PythonAnalysisHandler(mock_manager)
        result = handler({"code": "result = 42", "data": {"x": 1}})
        mock_manager.run_python.assert_called_once_with("result = 42", {"x": 1})
        self.assertEqual(result["status"], "ok")

    def test_build_tool_returns_correct_schema(self):
        with patch("analyst.tools._python_analysis.SandboxManager"):
            tool = build_python_analysis_tool()
        self.assertEqual(tool.name, "run_python_analysis")
        self.assertIn("code", tool.parameters["required"])
        self.assertIn("code", tool.parameters["properties"])
        self.assertIn("data", tool.parameters["properties"])
        self.assertIn("sandbox", tool.description.lower())


if __name__ == "__main__":
    unittest.main()
