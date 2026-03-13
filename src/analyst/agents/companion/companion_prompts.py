from __future__ import annotations

from datetime import datetime, timedelta, timezone

from analyst.delivery.soul import PromptAssemblyContext, assemble_persona_system_prompt

from ..base import RolePromptContext

_RESEARCH_DELEGATION_MODULE = """\
Research delegation:
- If the user asks for up-to-date markets, macro data, news, rates, portfolio risk, or why something moved, call `research_agent` before answering.
- Do not call `research_agent` for casual life chat, emotional support, scheduling, reminders, or photo/media requests.
- Give `research_agent` a crisp task plus only user-safe context. Never pass raw internal memory labels, profile dumps, or private notes.
- After the tool returns, answer in your normal companion voice. Do not paste raw tool output or mention internal roles/tools.
"""


def build_companion_system_prompt(context: RolePromptContext) -> str:
    now = datetime.now(timezone(timedelta(hours=8), name="Asia/Singapore"))
    base_prompt = assemble_persona_system_prompt(
        PromptAssemblyContext(
            mode="companion",
            user_text=context.user_text,
            user_lang=context.user_lang,
            memory_context=context.memory_context,
            group_context=context.group_context,
            current_time_label=now.strftime("%Y-%m-%d %H:%M %A") + " (Asia/Singapore)",
            proactive_kind=context.proactive_kind,
            companion_local_context=context.companion_local_context,
        )
    ).prompt
    return f"{base_prompt}\n\n{_RESEARCH_DELEGATION_MODULE}"
