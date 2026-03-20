from __future__ import annotations

import logging

from analyst.engine.backends import ClaudeCodeProvider
from analyst.engine.live_types import AgentTool
from analyst.tools import ToolKit, build_image_gen_tool, build_optional_live_photo_tool, build_smart_search_tool

from ..base import AgentRoleSpec, RoleDependencies
from .companion_prompts import build_companion_system_prompt

logger = logging.getLogger(__name__)


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
    if not isinstance(dependencies.provider, ClaudeCodeProvider):
        try:
            kit.add(build_smart_search_tool())
        except Exception:
            logger.debug("web_search tool not available (missing API key)")
    return kit.to_list()
