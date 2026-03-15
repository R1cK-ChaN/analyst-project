"""Sandbox manager — the public API for sandboxed code execution.

Composes AST-based policy validation with Docker container execution.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Callable

from .container_runner import ContainerRunner
from .limits import SandboxLimits
from .policy import PolicyViolation, validate_code

logger = logging.getLogger(__name__)


class SandboxManager:
    """Validate and execute Python code inside an ephemeral Docker container."""

    def __init__(
        self,
        limits: SandboxLimits | None = None,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._limits = limits or SandboxLimits.from_env()
        self._container = ContainerRunner(self._limits, runner=runner)

    def is_available(self) -> bool:
        return self._container.is_available()

    def run_python(
        self,
        code: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate and execute Python code in a sandbox.

        Returns a dict with:
          status        "ok" | "error"
          result        value of the ``result`` variable after execution
          stdout_output any print() output captured
          error         error message (empty string on success)
          timed_out     bool
        """
        try:
            validate_code(code)
        except PolicyViolation as exc:
            return _error(f"Code policy violation: {exc}")

        if not self._container.is_available():
            return _error("Docker is not available on this host.")

        payload: dict[str, Any] = {"code": code}
        if data is not None:
            payload["data"] = data

        container_result = self._container.run(payload)

        if container_result.timed_out:
            return _error("Execution timed out.", timed_out=True)

        if not container_result.success:
            return _error(container_result.error, stdout_output=container_result.stdout)

        return {
            "status": "ok",
            "result": container_result.result,
            "stdout_output": container_result.stdout,
            "error": "",
            "timed_out": False,
        }


def _error(
    msg: str,
    *,
    timed_out: bool = False,
    stdout_output: str = "",
) -> dict[str, Any]:
    return {
        "status": "error",
        "result": None,
        "stdout_output": stdout_output,
        "error": msg,
        "timed_out": timed_out,
    }
