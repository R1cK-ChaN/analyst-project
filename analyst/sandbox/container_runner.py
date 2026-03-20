"""Docker container runner for the sandbox.

Wraps ``docker run`` via subprocess, following the dependency-injection
pattern used by ``ClaudeCodeProvider`` and ``LivePhotoPackager``.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

from .limits import SandboxLimits

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContainerResult:
    success: bool
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    timed_out: bool = False


class ContainerRunner:
    """Runs Python code inside an ephemeral Docker container."""

    def __init__(
        self,
        limits: SandboxLimits,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._limits = limits
        self._runner = runner
        self._which = which

    def is_available(self) -> bool:
        return self._which("docker") is not None

    def run(self, payload: dict[str, Any]) -> ContainerResult:
        command = [
            "docker", "run", "--rm", "-i",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp",
            "--tmpfs", "/workspace",
            "-e", "MPLCONFIGDIR=/tmp/mpl",
            "-e", "HOME=/workspace",
            f"--memory={self._limits.memory}",
            f"--cpus={self._limits.cpus}",
            self._limits.image_name,
        ]

        input_json = json.dumps(payload, ensure_ascii=False, default=str)

        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                input=input_json,
                env={},
                timeout=self._limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Sandbox execution timed out after %ds", self._limits.timeout_seconds)
            return ContainerResult(success=False, timed_out=True, error="Execution timed out.")
        except FileNotFoundError:
            logger.warning("Docker binary not found on PATH")
            return ContainerResult(success=False, error="Docker is not installed or not on PATH.")

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""

        if self._limits.max_output_bytes and len(stdout) > self._limits.max_output_bytes:
            stdout = stdout[: self._limits.max_output_bytes]

        if completed.returncode != 0:
            error_msg = stderr.strip() or f"Container exited with code {completed.returncode}"
            logger.warning("Sandbox container failed (rc=%d): %s", completed.returncode, error_msg[:200])
            return ContainerResult(success=False, stdout=stdout, stderr=stderr, error=error_msg)

        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            return ContainerResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                error="Failed to parse container output as JSON.",
            )

        if not isinstance(parsed, dict):
            return ContainerResult(success=False, stdout=stdout, error="Container output is not a JSON object.")

        return ContainerResult(
            success=parsed.get("success", False),
            result=parsed.get("result"),
            stdout=parsed.get("stdout", ""),
            stderr=stderr,
            error=parsed.get("error", ""),
        )
