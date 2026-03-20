from __future__ import annotations

from analyst.engine.live_types import AgentTool


class ToolKit:
    """Composable builder for assembling agent tool lists.

    Each agent creates its own ToolKit, adds the tools it needs, and
    exports via ``to_list()`` for PythonAgentLoop.
    """

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def add(self, tool: AgentTool) -> ToolKit:
        """Add a single tool; later adds with the same name overwrite."""
        self._tools[tool.name] = tool
        return self

    def merge(self, other: ToolKit) -> ToolKit:
        """Merge another ToolKit into this one (other wins on conflicts)."""
        self._tools.update(other._tools)
        return self

    def to_list(self) -> list[AgentTool]:
        """Export the collected tools as a list for PythonAgentLoop."""
        return list(self._tools.values())
