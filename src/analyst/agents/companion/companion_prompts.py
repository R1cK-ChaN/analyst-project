from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from analyst.delivery.soul import PromptAssemblyContext, assemble_persona_system_prompt

from ..base import RolePromptContext

_RESEARCH_DELEGATION_MODULE = """\
Research delegation:
- If the user asks for up-to-date markets, macro data, news, rates, portfolio risk, or why something moved, call `research_agent` before answering.
- Do not call `research_agent` for casual life chat, emotional support, scheduling, reminders, or photo/media requests.
- Give `research_agent` a crisp task plus only user-safe context. Never pass raw internal memory labels, profile dumps, or private notes.
- After the tool returns, answer in your normal companion voice. Do not paste raw tool output or mention internal roles/tools.

Web search:
- 如果对方问了一个你不确定答案的事实性问题（天气、新闻、某件事是不是真的、某个人的最新动态），先用 web_search 搜一下再答，不要猜。
- 不要为了闲聊去搜索。"今天好累"不需要搜索，"今天新加坡会不会下雨"需要。
- 搜完之后用你正常的聊天语气回复，不要变成新闻播报员。简短、随意、像转述给朋友听。
- 不要展示搜索结果的 URL 或来源标注，除非对方明确要链接。
- 如果搜不到结果或者问题太私人化（"楼下那家面馆还开着吗"），直接说不知道。
"""

_DEFAULT_USER_TZ = "Asia/Singapore"
_BOT_TZ = ZoneInfo("Asia/Singapore")


def _extract_user_timezone(memory_context: str) -> str:
    """Extract user timezone from memory context, default to Singapore."""
    match = re.search(r"timezone_name:\s*(\S+)", memory_context)
    if match:
        tz_name = match.group(1)
        try:
            ZoneInfo(tz_name)
            return tz_name
        except (ZoneInfoNotFoundError, KeyError):
            pass
    return _DEFAULT_USER_TZ


def build_companion_system_prompt(context: RolePromptContext) -> str:
    # Bot's own time (陈襄 lives in Singapore)
    bot_now = datetime.now(_BOT_TZ)
    # User's local time
    user_tz_name = _extract_user_timezone(context.memory_context)
    try:
        user_tz = ZoneInfo(user_tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        user_tz = _BOT_TZ
        user_tz_name = _DEFAULT_USER_TZ
    user_now = datetime.now(user_tz)
    # Build time label: bot's time + user's time if different
    time_label = bot_now.strftime("%Y-%m-%d %H:%M %A") + " (Asia/Singapore)"
    if user_tz_name != _DEFAULT_USER_TZ:
        time_label += f" | 对方当地: {user_now.strftime('%H:%M %A')} ({user_tz_name})"
    base_prompt = assemble_persona_system_prompt(
        PromptAssemblyContext(
            mode="companion",
            user_text=context.user_text,
            user_lang=context.user_lang,
            memory_context=context.memory_context,
            group_context=context.group_context,
            current_time_label=time_label,
            proactive_kind=context.proactive_kind,
            companion_local_context=context.companion_local_context,
            group_autonomous=context.group_autonomous,
        )
    ).prompt
    return f"{base_prompt}\n\n{_RESEARCH_DELEGATION_MODULE}"
