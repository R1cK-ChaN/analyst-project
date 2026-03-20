"""Resource limits for the Docker sandbox."""

from __future__ import annotations

from dataclasses import dataclass

from analyst.env import get_env_value


@dataclass(frozen=True)
class SandboxLimits:
    memory: str = "512m"
    cpus: str = "1"
    timeout_seconds: int = 30
    image_name: str = "analyst-python-sandbox"
    max_output_bytes: int = 50_000

    @classmethod
    def from_env(cls) -> SandboxLimits:
        return cls(
            memory=get_env_value("ANALYST_SANDBOX_MEMORY", default="512m").strip(),
            cpus=get_env_value("ANALYST_SANDBOX_CPUS", default="1").strip(),
            timeout_seconds=int(get_env_value("ANALYST_SANDBOX_TIMEOUT", default="30").strip()),
            image_name=get_env_value("ANALYST_SANDBOX_IMAGE", default="analyst-python-sandbox").strip(),
        )
