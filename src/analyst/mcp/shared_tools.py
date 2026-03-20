from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from analyst.engine.live_types import AgentTool
from analyst.storage import SQLiteEngineStore
from analyst.tools import (
    build_image_gen_tool,
    build_optional_live_photo_tool,
)


ToolBuilder = Callable[[SQLiteEngineStore | None], AgentTool | None]


@dataclass(frozen=True)
class SharedMcpToolSpec:
    name: str
    build_tool: ToolBuilder
    requires_store: bool = False


def _stateless(builder: Callable[[], AgentTool]) -> ToolBuilder:
    def _build(_store: SQLiteEngineStore | None) -> AgentTool:
        return builder()

    return _build


def _optional_stateless(builder: Callable[[], AgentTool | None]) -> ToolBuilder:
    def _build(_store: SQLiteEngineStore | None) -> AgentTool | None:
        return builder()

    return _build


SHARED_MCP_TOOL_SPECS: dict[str, SharedMcpToolSpec] = {
    "generate_image": SharedMcpToolSpec("generate_image", _stateless(build_image_gen_tool)),
    "generate_live_photo": SharedMcpToolSpec("generate_live_photo", _optional_stateless(build_optional_live_photo_tool)),
}


def validate_shared_mcp_tool_names(tool_names: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for name in tool_names:
        normalized = str(name).strip()
        if not normalized or normalized not in SHARED_MCP_TOOL_SPECS or normalized in ordered:
            continue
        ordered.append(normalized)
    return tuple(ordered)


def build_shared_mcp_tools(
    *,
    tool_names: tuple[str, ...],
    db_path: str | Path | None = None,
) -> list[AgentTool]:
    validated = validate_shared_mcp_tool_names(tool_names)
    if not validated:
        return []

    store: SQLiteEngineStore | None = None
    if db_path:
        store = SQLiteEngineStore(db_path=Path(db_path))

    tools: list[AgentTool] = []
    for name in validated:
        spec = SHARED_MCP_TOOL_SPECS[name]
        tool = spec.build_tool(store)
        if tool is not None:
            tools.append(tool)
    return tools
