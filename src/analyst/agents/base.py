from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from analyst.engine.live_types import AgentTool, LLMProvider


@dataclass(frozen=True)
class RolePromptContext:
    memory_context: str = ""
    user_text: str = ""
    user_lang: str = ""
    group_context: str = ""
    proactive_kind: str = ""
    companion_local_context: str = ""
    current_time_label: str = ""


@dataclass(frozen=True)
class RoleDependencies:
    store: Any | None = None
    provider: LLMProvider | None = None
    engine: Any | None = None


PromptBuilder = Callable[[RolePromptContext], str]
ToolBuilder = Callable[[RoleDependencies], list[AgentTool]]


@dataclass(frozen=True)
class AgentRoleSpec:
    role_id: str
    build_system_prompt: PromptBuilder
    build_tools: ToolBuilder
