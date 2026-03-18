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
DEFAULT_USER_TIMEZONE = "Asia/Shanghai"
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
MAX_DOCUMENT_TEXT_CHARS = 8000
MAX_DOCUMENT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
SUPPORTED_DOCUMENT_MIMES: set[str] = {
    "application/pdf",
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
    "text/x-python",
    "text/x-script.python",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-excel",  # .xls
}
GROUP_MEMBER_MENTION_RE = re.compile(r"@\[(?P<name>[^\]\n]{1,64})\]")

