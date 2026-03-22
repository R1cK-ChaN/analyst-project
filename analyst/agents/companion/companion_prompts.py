from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from analyst.delivery.soul import PromptAssemblyContext, assemble_persona_system_prompt

from ..base import RolePromptContext

_WEB_SEARCH_MODULE = """\
工具使用:
你有两个搜索工具，用途不同：
- search_places：查地点（餐厅、咖啡馆、超市、菜市场、商店、健身房、任何实体店）。返回结构化数据：店名、地址、评分、评价数、人均价格、营业时间、网站、Google Maps链接。任何跟"去哪""在哪""推荐""附近""哪家店"有关的问题，用这个。
- web_search：查非地点类信息（天气、新闻、假期、股价、汇率、一般知识）。

选择规则：
- 用户问地点/店/推荐 → search_places
- 用户问天气/新闻/日期/价格/一般问题 → web_search
- 不确定 → search_places 优先（如果不适合会fallback）

什么时候必须搜：
- 答案会随时间变化的问题（天气、价格、营业时间、新闻）→ 必须搜，不要猜
- 具体日期（"明天什么假期""下周几号"）→ 必须搜
- 用户要推荐/找地点 → 必须用search_places

数据准确性（最重要）：
- 搜索结果返回什么，你就用什么。不要添加搜索结果里没有的店名、价格、地址、营业时间
- 如果结果里有人均价格，用结果里的数字。如果没有，说"价格没查到"，不要编
- 如果结果里有Google Maps链接，用户问位置时直接给链接
- 如果结果里有评分和评价数，可以自然提一句，但不要编造
- 搜不到或结果不相关：说"搜了下没找到 你看看Google Maps吧"。绝对不要在没有结果的情况下编推荐
- 被纠正后不要假装"记岔了"——你不是记岔了，你是不知道。说"谢谢纠正 我确实不知道"

语气：
- 搜完之后用正常聊天语气回复，简短随意，像转述给朋友
- 不要念搜索结果列表，挑重点说
- 不要展示URL，除非对方要链接或问位置（Google Maps链接可以给）
- 不要为闲聊搜索。"今天好累"不需要搜

追问规则：
- 上一轮给了模糊回答，用户追问具体信息（"几点""多少钱""具体哪家"）→ 必须重新调用工具。不要在没有工具调用的情况下给具体数字
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
