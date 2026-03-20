from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re

from .render import trim_text

_QUESTION_MARKERS = (
    "?",
    "？",
    "what",
    "when",
    "why",
    "how",
    "which",
    "who",
    "where",
    "should we",
    "are we",
    "do we",
    "can we",
    "吗",
    "嘛",
    "什么",
    "怎么",
    "几点",
    "要不要",
    "是不是",
)
_ACKNOWLEDGEMENT_MARKERS = (
    "ok",
    "okay",
    "sure",
    "yes",
    "yeah",
    "yep",
    "alright",
    "fine",
    "got it",
    "sounds good",
    "行",
    "好",
    "好的",
    "可以",
    "嗯",
    "哦",
    "收到",
)
_HUMOR_MARKERS = (
    "lol",
    "lmao",
    "haha",
    "hehe",
    "rofl",
    "哈哈",
    "哈哈哈",
    "233",
    "xd",
    "😂",
    "🤣",
    "😆",
)
_EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "get",
    "got",
    "have",
    "hello",
    "hey",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "just",
    "let",
    "lets",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "up",
    "us",
    "was",
    "we",
    "will",
    "with",
    "you",
    "your",
}
_CATEGORY_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "planning / scheduling": {
        "meet": ("meet", "meeting", "见面", "碰头", "约见"),
        "tomorrow": ("tomorrow", "tmr", "明天", "明晚"),
        "schedule": ("schedule", "scheduling", "plan", "plans", "安排", "计划", "行程"),
        "trip": ("trip", "travel", "旅行", "出游"),
        "weekend": ("weekend", "周末"),
    },
    "meal / food": {
        "eat": ("eat", "eating", "ate", "吃", "吃了", "吃啥", "吃什么"),
        "lunch": ("lunch", "午饭", "午餐"),
        "dinner": ("dinner", "晚饭", "晚餐"),
        "coffee": ("coffee", "cafe", "咖啡"),
        "rice": ("rice", "char siu", "roast pork", "beef rice", "hotpot", "叉烧", "烧肉", "火锅"),
    },
    "market / finance": {
        "market": ("market", "markets", "行情", "市场"),
        "fed": ("fed", "fomc", "federal reserve", "联储", "美联储"),
        "rates": ("rate", "rates", "yield", "利率", "降息", "加息"),
        "btc": ("btc", "bitcoin", "比特币"),
        "equities": ("stock", "stocks", "equity", "equities", "美股", "港股", "a股", "股票"),
        "macro": ("macro", "cpi", "nfp", "inflation", "通胀", "非农"),
    },
    "mood / emotional": {
        "tired": ("tired", "exhausted", "burned out", "burnt out", "累", "困"),
        "stress": ("stress", "stressed", "anxious", "panic", "焦虑", "压力", "崩溃"),
        "sad": ("sad", "down", "upset", "难过", "伤心", "失恋"),
    },
    "photos / media": {
        "photo": ("photo", "pic", "picture", "image", "照片", "图片"),
        "selfie": ("selfie", "自拍"),
        "video": ("video", "live photo", "视频", "动态"),
    },
    "work / office": {
        "work": ("work", "working", "上班", "工作"),
        "office": ("office", "desk", "工位", "办公室"),
        "boss": ("boss", "老板"),
    },
    "travel / outing": {
        "travel": ("travel", "flight", "airport", "boarding", "旅行", "机场"),
        "walk": ("walk", "walking", "散步"),
        "home": ("home", "回家", "在家"),
    },
    "relationships / people": {
        "friend": ("friend", "朋友"),
        "family": ("family", "wife", "husband", "girlfriend", "boyfriend", "老婆", "老公", "女朋友", "男朋友"),
        "boss": ("boss", "老板"),
    },
    "joke / banter": {
        "banter": _HUMOR_MARKERS,
    },
}
_CATEGORY_IMPORTANCE = {
    "planning / scheduling": 2.0,
    "market / finance": 1.8,
    "mood / emotional": 1.5,
    "work / office": 1.2,
    "travel / outing": 1.0,
    "photos / media": 0.9,
    "relationships / people": 0.9,
    "meal / food": 0.7,
    "joke / banter": 0.2,
}


@dataclass(frozen=True)
class ConversationTopicMessage:
    speaker_key: str
    speaker_label: str
    content: str
    created_at: str
    is_assistant: bool = False
    is_current_turn: bool = False


@dataclass(frozen=True)
class TopicStateEntry:
    label: str
    keywords: tuple[str, ...]
    status: str
    score: float
    latest_summary: str
    last_speaker: str
    participants: tuple[str, ...]
    is_self_topic: bool


@dataclass(frozen=True)
class TopicStateSnapshot:
    active_topic: str
    reply_focus: str
    cooling_topics: tuple[str, ...]
    topic_stack: tuple[TopicStateEntry, ...]


@dataclass(frozen=True)
class _TopicSignal:
    label: str
    keywords: tuple[str, ...]
    summary: str
    importance: float
    is_question: bool
    is_acknowledgement: bool
    is_humor: bool
    is_self_topic: bool


@dataclass
class _TopicBucket:
    label: str
    keywords: set[str] = field(default_factory=set)
    latest_summary: str = ""
    last_activity_at: str = ""
    participants: set[str] = field(default_factory=set)
    total_importance: float = 0.0
    latest_rank: int = 0
    latest_speaker: str = ""
    latest_is_assistant: bool = False
    latest_is_question: bool = False
    contains_current_turn: bool = False
    self_topic_weight: float = 0.0


def build_topic_state_lines(
    messages: list[ConversationTopicMessage],
    *,
    max_topics: int = 3,
) -> list[str]:
    snapshot = derive_topic_state(messages, max_topics=max_topics)
    if not snapshot.active_topic:
        return []
    lines = [f"- active_topic: {snapshot.active_topic}"]
    if snapshot.reply_focus:
        lines.append(f"- reply_focus: {snapshot.reply_focus}")
    if snapshot.cooling_topics:
        lines.append(f"- cooling_topics: {', '.join(snapshot.cooling_topics)}")
    for entry in snapshot.topic_stack:
        keywords = f" | keywords: {', '.join(entry.keywords)}" if entry.keywords else ""
        participants = f" | participants: {', '.join(entry.participants)}" if entry.participants else ""
        self_marker = " | self_topic" if entry.is_self_topic else ""
        lines.append(
            f"- topic_stack: {entry.label} | status: {entry.status} | score: {entry.score:.1f} "
            f"| last_speaker: {entry.last_speaker}{keywords}{participants}{self_marker}"
        )
    return lines


def derive_topic_state(
    messages: list[ConversationTopicMessage],
    *,
    max_topics: int = 3,
) -> TopicStateSnapshot:
    normalized_messages = [message for message in messages if str(message.content or "").strip()]
    if not normalized_messages:
        return TopicStateSnapshot(active_topic="", reply_focus="", cooling_topics=(), topic_stack=())

    buckets: list[_TopicBucket] = []
    for rank, message in enumerate(normalized_messages):
        signal = _classify_message(message)
        if signal.is_acknowledgement and buckets:
            target_index = len(buckets) - 1
        else:
            target_index = _find_matching_bucket(signal, buckets)
        if target_index is None:
            buckets.append(_TopicBucket(label=signal.label))
            target_index = len(buckets) - 1
        bucket = buckets[target_index]
        bucket.keywords.update(signal.keywords)
        bucket.latest_summary = signal.summary
        bucket.last_activity_at = message.created_at
        bucket.participants.add(message.speaker_label)
        bucket.total_importance += signal.importance
        bucket.latest_rank = rank
        bucket.latest_speaker = message.speaker_label
        bucket.latest_is_assistant = message.is_assistant
        bucket.latest_is_question = signal.is_question
        bucket.contains_current_turn = bucket.contains_current_turn or message.is_current_turn
        if signal.is_self_topic:
            bucket.self_topic_weight += signal.importance

    scored = _score_buckets(buckets)
    if not scored:
        return TopicStateSnapshot(active_topic="", reply_focus="", cooling_topics=(), topic_stack=())

    active_bucket = max(scored, key=lambda item: item[1])[0]
    active_score = max(score for _, score in scored) or 1.0
    reply_focus = trim_text(active_bucket.latest_summary, max_chars=90)

    ranked_buckets = sorted(
        ((bucket, score) for bucket, score in scored),
        key=lambda item: (item[1], item[0].latest_rank),
        reverse=True,
    )[:max_topics]

    stack: list[TopicStateEntry] = []
    cooling_topics: list[str] = []
    for bucket, score in ranked_buckets:
        if bucket is active_bucket:
            status = "active"
        elif score >= active_score * 0.45:
            status = "warm"
        else:
            status = "cooling"
            cooling_topics.append(bucket.label)
        stack.append(
            TopicStateEntry(
                label=bucket.label,
                keywords=tuple(sorted(bucket.keywords))[:3],
                status=status,
                score=round(score, 1),
                latest_summary=trim_text(bucket.latest_summary, max_chars=90),
                last_speaker=bucket.latest_speaker or "unknown",
                participants=tuple(sorted(name for name in bucket.participants if name)),
                is_self_topic=bucket.self_topic_weight >= bucket.total_importance * 0.6 if bucket.total_importance else False,
            )
        )
    return TopicStateSnapshot(
        active_topic=active_bucket.label,
        reply_focus=reply_focus,
        cooling_topics=tuple(cooling_topics),
        topic_stack=tuple(stack),
    )


def _score_buckets(buckets: list[_TopicBucket]) -> list[tuple[_TopicBucket, float]]:
    reference_time = _parse_datetime(buckets[-1].last_activity_at) or datetime.now(timezone.utc)
    scored: list[tuple[_TopicBucket, float]] = []
    total = max(len(buckets), 1)
    for bucket in buckets:
        activity_time = _parse_datetime(bucket.last_activity_at) or reference_time
        age_seconds = max((reference_time - activity_time).total_seconds(), 0.0)
        time_decay = math.exp(-age_seconds / 1800.0)
        rank_gap = max(total - 1 - bucket.latest_rank, 0)
        recency_decay = 0.72 ** rank_gap
        score = bucket.total_importance * time_decay * recency_decay
        if bucket.contains_current_turn:
            score *= 1.35
        if bucket.latest_is_question:
            score *= 1.15
        if bucket.latest_is_assistant:
            score *= 0.7
            if bucket.label in {"meal / food", "photos / media", "joke / banter"}:
                score *= 0.5
        if bucket.self_topic_weight >= bucket.total_importance * 0.6 and bucket.total_importance:
            score *= 0.45
        scored.append((bucket, score))
    return scored


def _find_matching_bucket(
    signal: _TopicSignal,
    buckets: list[_TopicBucket],
) -> int | None:
    if not buckets:
        return None
    for index in range(len(buckets) - 1, max(-1, len(buckets) - 4), -1):
        bucket = buckets[index]
        if signal.label == bucket.label and signal.label != "general chat":
            return index
        if signal.keywords and bucket.keywords and set(signal.keywords).intersection(bucket.keywords):
            return index
    return None


def _classify_message(message: ConversationTopicMessage) -> _TopicSignal:
    content = str(message.content or "").strip()
    lowered = content.casefold()
    is_question = any(marker in lowered for marker in _QUESTION_MARKERS)
    is_humor = any(marker in lowered for marker in _HUMOR_MARKERS)
    is_acknowledgement = _is_acknowledgement(content, lowered=lowered)

    category_hits: dict[str, list[str]] = {}
    for category, keyword_map in _CATEGORY_PATTERNS.items():
        matched = [
            canonical
            for canonical, patterns in keyword_map.items()
            if any(pattern.casefold() in lowered for pattern in patterns)
        ]
        if matched:
            category_hits[category] = matched

    label = "general chat"
    keywords: list[str] = []
    if category_hits:
        label = max(
            category_hits,
            key=lambda category: (
                len(category_hits[category]) * _CATEGORY_IMPORTANCE.get(category, 1.0),
                _CATEGORY_IMPORTANCE.get(category, 1.0),
            ),
        )
        keywords = category_hits[label]
    else:
        keywords = _extract_fallback_keywords(content)
        if keywords:
            label = " / ".join(keywords[:2])

    importance = 1.0 + _CATEGORY_IMPORTANCE.get(label, 0.6)
    if is_question:
        importance += 1.4
    if is_humor:
        importance *= 0.35
    if is_acknowledgement:
        importance *= 0.55
    if message.is_assistant:
        importance *= 0.3

    return _TopicSignal(
        label=label,
        keywords=tuple(dict.fromkeys(keywords)),
        summary=trim_text(_collapse_whitespace(content), max_chars=90),
        importance=importance,
        is_question=is_question,
        is_acknowledgement=is_acknowledgement,
        is_humor=is_humor,
        is_self_topic=message.is_assistant,
    )


def _extract_fallback_keywords(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    english = [
        token
        for token in re.findall(r"[a-z][a-z0-9_'-]{2,}", lowered)
        if token not in _EN_STOPWORDS
    ]
    if english:
        return list(dict.fromkeys(english))[:3]
    chinese_segments = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    cleaned = [segment for segment in chinese_segments if len(segment.strip()) >= 2]
    return list(dict.fromkeys(cleaned))[:2]


def _is_acknowledgement(text: str, *, lowered: str) -> bool:
    collapsed = _collapse_whitespace(lowered)
    if collapsed in _ACKNOWLEDGEMENT_MARKERS:
        return True
    return False


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _parse_datetime(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
