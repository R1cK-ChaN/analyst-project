from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from analyst.delivery.soul import PromptAssemblyContext, assemble_persona_system_prompt

from ..base import RolePromptContext

_WEB_SEARCH_MODULE = """\
Web search:
- 判断标准很简单：这个问题的答案会随时间变化吗？（天气、价格、新闻、假期日期、营业时间、某人近况）如果会，你的训练数据就不可靠，必须搜。
- 特别注意：具体日期对应什么（"明天什么假期""下周几号"）、实时数据（股价、汇率）、本地信息（天气、开不开门）——这些你一定不知道，不要试图从记忆里拼凑。
- 用户要你推荐地点（咖啡馆、餐厅、学习的地方）时，用web_search搜，query里带上地点和用途（如"quiet cafe for studying near Tanjong Pagar"）。拿到结果后像碰巧知道这个地方一样随口说，不要念搜索结果列表。
- 不要为了闲聊去搜索。"今天好累"不需要搜索，"今天新加坡会不会下雨"需要。
- 搜完之后用你正常的聊天语气回复，不要变成新闻播报员。简短、随意、像转述给朋友听。
- 不要展示搜索结果的 URL 或来源标注，除非对方明确要链接。
- 如果搜不到结果或结果不相关，说"我搜了下没找到太好的 你自己看看Google Maps吧"。绝对不要在没有搜索结果的情况下编一个推荐。
- 问题太私人化（"楼下那家面馆还开着吗"），直接说不知道。
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
    return f"{base_prompt}\n\n{_WEB_SEARCH_MODULE}"
