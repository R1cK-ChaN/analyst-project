from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from analyst.agents import RoleDependencies, get_role_spec
from analyst.engine.live_types import AgentTool, LLMProvider
from analyst.engine.backends import ClaudeCodeProvider
from analyst.storage import SQLiteEngineStore

CLAUDE_CODE_NATIVE_TOOL_NAMES = ("WebSearch", "WebFetch")
COMPANION_SHARED_MCP_TOOL_NAMES = (
    "generate_image",
)


@dataclass(frozen=True)
class CapabilityBuildContext:
    engine: Any | None = None
    store: SQLiteEngineStore | None = None
    provider: LLMProvider | None = None


def _build_companion_capabilities(context: CapabilityBuildContext) -> list[AgentTool]:
    return get_role_spec("companion").build_tools(
        RoleDependencies(store=context.store, provider=context.provider),
    )


@dataclass(frozen=True)
class CapabilitySurfaceSpec:
    surface_id: str
    native_tool_names: tuple[str, ...] = ()
    shared_mcp_tool_names: tuple[str, ...] = ()
    build_tools: Callable[[CapabilityBuildContext], list[AgentTool]] | None = None


CAPABILITY_MATRIX: dict[str, CapabilitySurfaceSpec] = {
    "companion": CapabilitySurfaceSpec(
        surface_id="companion",
        native_tool_names=CLAUDE_CODE_NATIVE_TOOL_NAMES,
        shared_mcp_tool_names=COMPANION_SHARED_MCP_TOOL_NAMES,
        build_tools=_build_companion_capabilities,
    ),
}


def get_capability_surface(surface_id: str) -> CapabilitySurfaceSpec:
    normalized = str(surface_id).strip().lower()
    try:
        return CAPABILITY_MATRIX[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown capability surface: {surface_id}") from exc


def build_capability_tools(
    surface_id: str,
    *,
    engine: Any | None = None,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
) -> list[AgentTool]:
    context = CapabilityBuildContext(engine=engine, store=store, provider=provider)
    spec = get_capability_surface(surface_id)
    if spec.build_tools is not None:
        return spec.build_tools(context)
    return []
