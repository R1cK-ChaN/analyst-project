"""Execute Python code in a sandboxed Docker container."""

from __future__ import annotations

from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.sandbox import SandboxManager


class PythonAnalysisHandler:
    """Stateful callable that delegates code execution to a SandboxManager."""

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        code = str(arguments.get("code", "")).strip()
        if not code:
            return {"status": "error", "error": "code is required", "result": None}
        data = arguments.get("data")
        return self._manager.run_python(code, data)


def build_python_analysis_tool(
    manager: SandboxManager | None = None,
) -> AgentTool:
    """Factory: create a run_python_analysis AgentTool."""
    resolved = manager or SandboxManager()
    handler = PythonAnalysisHandler(resolved)
    return AgentTool(
        name="run_python_analysis",
        description=(
            "Execute Python code in a sandboxed environment for data analysis, "
            "statistical calculations, or chart generation. The code has access to "
            "numpy, pandas, scipy, matplotlib, and statsmodels. Pass optional data "
            "as a JSON object accessible via the `data` variable. Store your final "
            "answer in a variable called `result`."
        ),
        parameters={
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Python code to execute. Use numpy, pandas, scipy, matplotlib, "
                        "or statsmodels for analysis. Store the final answer in a variable "
                        "called `result`. Print output is also captured."
                    ),
                },
                "data": {
                    "type": "object",
                    "description": (
                        "Optional JSON data to pass into the execution environment, "
                        "accessible as the `data` variable in your code."
                    ),
                },
            },
        },
        handler=handler,
    )
