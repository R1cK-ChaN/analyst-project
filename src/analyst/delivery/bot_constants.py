from __future__ import annotations

import re
from datetime import timedelta, timezone

MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_TURNS = 20
MAX_GROUP_CONTEXT_MESSAGES = 50
MAX_GROUP_CONTEXT_CHARS = 1500
COMPANION_CHECKIN_INTERVAL_SECONDS = 300
COMPANION_CHECKIN_SEND_WINDOW_START_HOUR = 10
COMPANION_CHECKIN_SEND_WINDOW_END_HOUR = 20
COMPANION_LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Singapore")
MANAGED_MEDIA_PREFIXES = (
    "analyst_gen_",
    "analyst_live_",
)
MAX_INBOUND_IMAGE_EDGE = 1536
INSTANT_REPLY_MAX_CHARS = 12
DEEP_STORY_MIN_LINES = 4
DEEP_STORY_MIN_CHARS = 220
EMOTIONAL_CUE_TOKENS = (
    "怎么办",
    "完了",
    "扛不住",
    "不想做了",
    "睡不好",
    "睡不着",
    "焦虑",
    "崩溃",
    "难受",
    "烦死",
    "累了",
    "失眠",
    "overwhelmed",
    "anxious",
    "panic",
    "panicking",
    "burned out",
    "burnt out",
    "rough day",
    "can't sleep",
    "cant sleep",
    "breakup hurts",
    "stressed",
)
GROUP_MEMBER_MENTION_RE = re.compile(r"@\[(?P<name>[^\]\n]{1,64})\]")

