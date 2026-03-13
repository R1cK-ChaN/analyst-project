from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.tools import ToolKit, build_image_gen_tool, build_optional_live_photo_tool

from ..base import AgentRoleSpec, RoleDependencies
from ..research.research_agent import build_research_agent_tool
from .companion_prompts import build_companion_system_prompt


def build_companion_role_spec() -> AgentRoleSpec:
    return AgentRoleSpec(
        role_id="companion",
        build_system_prompt=build_companion_system_prompt,
        build_tools=_build_companion_tools,
    )


def _build_companion_tools(dependencies: RoleDependencies) -> list[AgentTool]:
    kit = ToolKit()
    kit.add(build_image_gen_tool())
    live_photo_tool = build_optional_live_photo_tool()
    if live_photo_tool is not None:
        kit.add(live_photo_tool)
    research_tool = build_research_agent_tool(provider=dependencies.provider, store=dependencies.store)
    if research_tool is not None:
        kit.add(research_tool)
    return kit.to_list()
