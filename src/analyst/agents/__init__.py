from __future__ import annotations

from .base import AgentRoleSpec, RoleDependencies, RolePromptContext
from .companion.companion_agent import build_companion_role_spec
from .research.research_agent import build_research_agent_tool, build_research_role_spec


def get_role_spec(role_id: str) -> AgentRoleSpec:
    normalized = str(role_id).strip().lower()
    if normalized == "companion":
        return build_companion_role_spec()
    if normalized == "research":
        return build_research_role_spec()
    raise KeyError(f"Unknown role spec: {role_id}")


__all__ = [
    "AgentRoleSpec",
    "RoleDependencies",
    "RolePromptContext",
    "build_research_agent_tool",
    "build_research_role_spec",
    "build_companion_role_spec",
    "get_role_spec",
]
