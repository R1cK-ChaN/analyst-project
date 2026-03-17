from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClientProfileUpdate:
    preferred_language: str | None = None
    watchlist_topics: list[str] = field(default_factory=list)
    response_style: str | None = None
    risk_appetite: str | None = None
    investment_horizon: str | None = None
    institution_type: str | None = None
    risk_preference: str | None = None
    asset_focus: list[str] = field(default_factory=list)
    market_focus: list[str] = field(default_factory=list)
    expertise_level: str | None = None
    activity: str | None = None
    current_mood: str | None = None
    emotional_trend: str | None = None
    stress_level: str | None = None
    confidence: str | None = None
    notes: str | None = None
    personal_facts: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClientProfileUpdate":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            preferred_language=_clean_scalar(payload.get("preferred_language")),
            watchlist_topics=_clean_list(payload.get("watchlist_topics")),
            response_style=_clean_scalar(payload.get("response_style")),
            risk_appetite=_clean_scalar(payload.get("risk_appetite")),
            investment_horizon=_clean_scalar(payload.get("investment_horizon")),
            institution_type=_clean_scalar(payload.get("institution_type")),
            risk_preference=_clean_scalar(payload.get("risk_preference")),
            asset_focus=_clean_list(payload.get("asset_focus")),
            market_focus=_clean_list(payload.get("market_focus")),
            expertise_level=_clean_scalar(payload.get("expertise_level")),
            activity=_clean_scalar(payload.get("activity")),
            current_mood=_clean_scalar(payload.get("current_mood")),
            emotional_trend=_clean_scalar(payload.get("emotional_trend")),
            stress_level=_clean_scalar(payload.get("stress_level")),
            confidence=_clean_scalar(payload.get("confidence")),
            notes=_clean_scalar(payload.get("notes")),
            personal_facts=_clean_list(payload.get("personal_facts")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferred_language": self.preferred_language,
            "watchlist_topics": self.watchlist_topics,
            "response_style": self.response_style,
            "risk_appetite": self.risk_appetite,
            "investment_horizon": self.investment_horizon,
            "institution_type": self.institution_type,
            "risk_preference": self.risk_preference,
            "asset_focus": self.asset_focus,
            "market_focus": self.market_focus,
            "expertise_level": self.expertise_level,
            "activity": self.activity,
            "current_mood": self.current_mood,
            "emotional_trend": self.emotional_trend,
            "stress_level": self.stress_level,
            "confidence": self.confidence,
            "notes": self.notes,
            "personal_facts": self.personal_facts,
        }


@dataclass(frozen=True)
class CompanionScheduleUpdate:
    revision_mode: str | None = None
    morning_plan: str | None = None
    lunch_plan: str | None = None
    afternoon_plan: str | None = None
    dinner_plan: str | None = None
    evening_plan: str | None = None
    current_plan: str | None = None
    next_plan: str | None = None
    revision_note: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompanionScheduleUpdate":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            revision_mode=_clean_scalar(payload.get("revision_mode")),
            morning_plan=_clean_scalar(payload.get("morning_plan")),
            lunch_plan=_clean_scalar(payload.get("lunch_plan")),
            afternoon_plan=_clean_scalar(payload.get("afternoon_plan")),
            dinner_plan=_clean_scalar(payload.get("dinner_plan")),
            evening_plan=_clean_scalar(payload.get("evening_plan")),
            current_plan=_clean_scalar(payload.get("current_plan")),
            next_plan=_clean_scalar(payload.get("next_plan")),
            revision_note=_clean_scalar(payload.get("revision_note")),
        )

    def has_changes(self) -> bool:
        return any(
            getattr(self, field) is not None
            for field in (
                "morning_plan",
                "lunch_plan",
                "afternoon_plan",
                "dinner_plan",
                "evening_plan",
                "current_plan",
                "next_plan",
                "revision_note",
            )
        )

    def normalized_revision_mode(self) -> str:
        return "revise" if str(self.revision_mode or "").strip().lower() == "revise" else "set"


@dataclass(frozen=True)
class CompanionReminderUpdate:
    reminder_text: str | None = None
    due_at: str | None = None
    timezone_name: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompanionReminderUpdate":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            reminder_text=_clean_scalar(payload.get("reminder_text")),
            due_at=_clean_scalar(payload.get("due_at")),
            timezone_name=_clean_scalar(payload.get("timezone_name")),
        )

    def has_changes(self) -> bool:
        return bool(self.reminder_text and self.due_at)


@dataclass(frozen=True)
class RelationshipSignalUpdate:
    current_mood: str | None = None
    is_personal_sharing: bool = False
    is_late_night: bool = False
    topic_depth_score: float = 0.0
    active_topic_category: str | None = None  # e.g. "mood / emotional", "joke / banter"
    interaction_mode: str | None = None  # seeking_advice / venting / flirting / curious_about_ai
    nickname_for_ai: str | None = None
    nickname_for_user: str | None = None
    user_text: str = ""  # raw text for nickname frequency bumping


_WATCHLIST_PATTERNS = {
    "fed": re.compile(r"(?:\b(?:fed|fomc|powell)\b|美联储|联储)", re.IGNORECASE),
    "cpi": re.compile(r"(?:\b(?:cpi|inflation)\b|通胀)", re.IGNORECASE),
    "jobs": re.compile(r"(?:\b(?:nfp|payroll|employment)\b|非农|就业)", re.IGNORECASE),
    "rates": re.compile(r"(?:\b(?:rates?|yield|treasury)\b|利率|美债|收益率)", re.IGNORECASE),
    "crypto": re.compile(r"(?:\b(?:bitcoin|btc|eth|crypto)\b|加密|比特币|以太坊)", re.IGNORECASE),
    "gold": re.compile(r"(?:\b(?:gold)\b|黄金)", re.IGNORECASE),
    "oil": re.compile(r"(?:\b(?:oil|crude)\b|原油)", re.IGNORECASE),
    "equities": re.compile(r"(?:\b(?:equity|stocks?|nasdaq|spx|hang seng)\b|A股|港股|美股|股票)", re.IGNORECASE),
    "fx": re.compile(r"(?:\b(?:fx|usd|dxy|eurusd|usdcny)\b|汇率|美元|人民币|外汇)", re.IGNORECASE),
}

_STYLE_PATTERNS = {
    "concise": re.compile(r"(简短|简洁|一句话|短一点|concise|brief)", re.IGNORECASE),
    "detailed": re.compile(r"(详细|展开|多写一点|详细点|detailed)", re.IGNORECASE),
}

_RISK_PATTERNS = {
    "conservative": re.compile(r"(稳健|保守|低风险|conservative)", re.IGNORECASE),
    "aggressive": re.compile(r"(进取|激进|高弹性|aggressive)", re.IGNORECASE),
}

_RISK_PREFERENCE_PATTERNS = {
    "defensive": re.compile(r"(稳健|保守|低风险|回撤控制|先别激进)", re.IGNORECASE),
    "offensive": re.compile(r"(进取|激进|高弹性|想搏一把|愿意加风险)", re.IGNORECASE),
    "balanced": re.compile(r"(均衡|平衡|中性一点|别太极端)", re.IGNORECASE),
}

_HORIZON_PATTERNS = {
    "short_term": re.compile(r"(短线|今天|本周|盘中|short[- ]?term)", re.IGNORECASE),
    "long_term": re.compile(r"(长线|中长期|季度|半年|long[- ]?term)", re.IGNORECASE),
}

_INSTITUTION_PATTERNS = {
    "mutual_fund": re.compile(r"(公募|基金公司|公募基金)", re.IGNORECASE),
    "hedge_fund": re.compile(r"(私募|对冲|hedge|量化私募)", re.IGNORECASE),
    "insurance": re.compile(r"(保险|险资)", re.IGNORECASE),
    "bank_wm": re.compile(r"(银行理财|理财子|理财经理|银行资金)", re.IGNORECASE),
    "offshore": re.compile(r"(海外|offshore|overseas)", re.IGNORECASE),
    "retail": re.compile(r"(散户|个人投资|自己炒|自己做)", re.IGNORECASE),
}

_ASSET_PATTERNS = {
    "equity": re.compile(r"(权益|股票|股市|beta|仓位)", re.IGNORECASE),
    "fixed_income": re.compile(r"(固收|债|利率债|信用债|久期)", re.IGNORECASE),
    "derivatives": re.compile(r"(期权|期货|衍生品|互换|swap|gamma|vega)", re.IGNORECASE),
    "commodities": re.compile(r"(商品|原油|黄金|铜|黑色)", re.IGNORECASE),
    "multi_asset": re.compile(r"(多资产|资产配置|跨资产)", re.IGNORECASE),
}

_MARKET_PATTERNS = {
    "a_shares": re.compile(r"(A股|沪深|上证|深证|创业板|科创板)", re.IGNORECASE),
    "hk_equities": re.compile(r"(港股|恒生|恒指|H股)", re.IGNORECASE),
    "us_equities": re.compile(r"(美股|纳指|标普|道指|nasdaq|spx)", re.IGNORECASE),
    "bonds": re.compile(r"(债市|国债|信用债|美债|收益率曲线)", re.IGNORECASE),
    "commodities": re.compile(r"(商品|原油|黄金|铜|大宗)", re.IGNORECASE),
    "fx": re.compile(r"(外汇|汇率|美元|人民币|日元|欧元|fx)", re.IGNORECASE),
}

_EXPERTISE_PATTERNS = {
    "senior": re.compile(r"(组合|净值|回撤|久期|carry|vega|basis|赔率|仓位管理)", re.IGNORECASE),
    "junior": re.compile(r"(刚开始|小白|入门|不太懂|科普一下)", re.IGNORECASE),
}

_ACTIVITY_PATTERNS = {
    "high": re.compile(r"(每天|天天|盘中|实时|高频|一直盯)", re.IGNORECASE),
    "low": re.compile(r"(偶尔|不常|低频|佛系|很少看盘)", re.IGNORECASE),
    "medium": re.compile(r"(每周|隔三差五|有空会看)", re.IGNORECASE),
}

_MOOD_PATTERNS = {
    "anxious": re.compile(r"(太难做|崩了|慌|焦虑|扛不住|难受|亏麻了)", re.IGNORECASE),
    "cautious": re.compile(r"(谨慎|先看看|再观察|别急|不太敢)", re.IGNORECASE),
    "optimistic": re.compile(r"(乐观|看多|有信心|挺稳|问题不大)", re.IGNORECASE),
}

_PROFILE_UPDATE_PATTERN = re.compile(
    r"<profile_update>\s*(\{.*?\})\s*</profile_update>",
    re.DOTALL | re.IGNORECASE,
)
_SCHEDULE_UPDATE_PATTERN = re.compile(
    r"<schedule_update>\s*(\{.*?\})\s*</schedule_update>",
    re.DOTALL | re.IGNORECASE,
)
_REMINDER_UPDATE_PATTERN = re.compile(
    r"<reminder_update>\s*(\{.*?\})\s*</reminder_update>",
    re.DOTALL | re.IGNORECASE,
)


def extract_client_profile_update(text: str) -> ClientProfileUpdate:
    stripped = text.strip()
    if not stripped:
        return ClientProfileUpdate()

    preferred_language = "zh" if re.search(r"[\u4e00-\u9fff]", stripped) else "en"
    watchlist_topics = [name for name, pattern in _WATCHLIST_PATTERNS.items() if pattern.search(stripped)]
    asset_focus = [name for name, pattern in _ASSET_PATTERNS.items() if pattern.search(stripped)]
    market_focus = [name for name, pattern in _MARKET_PATTERNS.items() if pattern.search(stripped)]

    response_style = _first_match(_STYLE_PATTERNS, stripped)
    risk_appetite = _first_match(_RISK_PATTERNS, stripped)
    investment_horizon = _first_match(_HORIZON_PATTERNS, stripped)
    institution_type = _first_match(_INSTITUTION_PATTERNS, stripped)
    risk_preference = _first_match(_RISK_PREFERENCE_PATTERNS, stripped)
    activity = _first_match(_ACTIVITY_PATTERNS, stripped)
    current_mood = _first_match(_MOOD_PATTERNS, stripped)

    expertise_level = _first_match(_EXPERTISE_PATTERNS, stripped)
    if expertise_level is None and (watchlist_topics or asset_focus or market_focus):
        expertise_level = "intermediate"

    confidence = "low"
    if institution_type or expertise_level == "senior" or len(asset_focus) + len(market_focus) >= 2:
        confidence = "medium"
    if expertise_level == "senior" and (institution_type or activity == "high"):
        confidence = "high"

    if risk_preference is None:
        if risk_appetite == "aggressive":
            risk_preference = "offensive"
        elif risk_appetite == "conservative":
            risk_preference = "defensive"

    return ClientProfileUpdate(
        preferred_language=preferred_language,
        watchlist_topics=watchlist_topics,
        response_style=response_style,
        risk_appetite=risk_appetite,
        investment_horizon=investment_horizon,
        institution_type=institution_type,
        risk_preference=risk_preference,
        asset_focus=asset_focus,
        market_focus=market_focus,
        expertise_level=expertise_level,
        activity=activity,
        current_mood=current_mood,
        confidence=confidence,
    )


def extract_embedded_profile_update(text: str) -> ClientProfileUpdate:
    matches = _PROFILE_UPDATE_PATTERN.findall(text)
    if not matches:
        return ClientProfileUpdate()
    raw_payload = matches[-1]
    try:
        decoded = json.loads(raw_payload)
    except json.JSONDecodeError:
        return ClientProfileUpdate()
    return ClientProfileUpdate.from_dict(decoded)


def extract_embedded_schedule_update(text: str) -> CompanionScheduleUpdate:
    matches = _SCHEDULE_UPDATE_PATTERN.findall(text)
    if not matches:
        return CompanionScheduleUpdate()
    raw_payload = matches[-1]
    try:
        decoded = json.loads(raw_payload)
    except json.JSONDecodeError:
        return CompanionScheduleUpdate()
    return CompanionScheduleUpdate.from_dict(decoded)


def extract_embedded_reminder_update(text: str) -> CompanionReminderUpdate:
    matches = _REMINDER_UPDATE_PATTERN.findall(text)
    if not matches:
        return CompanionReminderUpdate()
    raw_payload = matches[-1]
    try:
        decoded = json.loads(raw_payload)
    except json.JSONDecodeError:
        return CompanionReminderUpdate()
    return CompanionReminderUpdate.from_dict(decoded)


def strip_embedded_reminder_update(text: str) -> str:
    return _REMINDER_UPDATE_PATTERN.sub("", text).strip()


def strip_embedded_schedule_update(text: str) -> str:
    return _SCHEDULE_UPDATE_PATTERN.sub("", strip_embedded_reminder_update(text)).strip()


def strip_embedded_profile_update(text: str) -> str:
    return _PROFILE_UPDATE_PATTERN.sub("", strip_embedded_schedule_update(text)).strip()


def split_reply_and_profile_update(text: str) -> tuple[str, ClientProfileUpdate]:
    return strip_embedded_profile_update(text), extract_embedded_profile_update(text)


def merge_client_profile_updates(*updates: ClientProfileUpdate) -> ClientProfileUpdate:
    merged = ClientProfileUpdate()
    for update in updates:
        if update is None:
            continue
        merged = ClientProfileUpdate(
            preferred_language=update.preferred_language or merged.preferred_language,
            watchlist_topics=_merge_lists(merged.watchlist_topics, update.watchlist_topics),
            response_style=update.response_style or merged.response_style,
            risk_appetite=update.risk_appetite or merged.risk_appetite,
            investment_horizon=update.investment_horizon or merged.investment_horizon,
            institution_type=update.institution_type or merged.institution_type,
            risk_preference=update.risk_preference or merged.risk_preference,
            asset_focus=_merge_lists(merged.asset_focus, update.asset_focus),
            market_focus=_merge_lists(merged.market_focus, update.market_focus),
            expertise_level=update.expertise_level or merged.expertise_level,
            activity=update.activity or merged.activity,
            current_mood=update.current_mood or merged.current_mood,
            emotional_trend=update.emotional_trend or merged.emotional_trend,
            stress_level=update.stress_level or merged.stress_level,
            confidence=update.confidence or merged.confidence,
            notes=update.notes or merged.notes,
            personal_facts=_merge_lists_capped(merged.personal_facts, update.personal_facts, cap=20),
        )
    return merged


_ZH_TO_EN: dict[str, str] = {
    # confidence
    "低": "low", "中": "medium", "高": "high",
    # mood
    "焦虑": "anxious", "谨慎": "cautious", "乐观": "optimistic",
    "疲惫": "exhausted", "自嘲": "self-deprecating", "兴奋": "excited",
    # expertise
    "资深": "senior", "初级": "junior", "中等": "intermediate",
    # activity
    "高频": "high", "中频": "medium", "低频": "low",
    # risk_preference
    "防守": "defensive", "进攻": "offensive", "均衡": "balanced",
    # institution
    "公募": "mutual_fund", "私募": "hedge_fund", "保险": "insurance",
    "银行理财": "bank_wm", "海外": "offshore", "散户": "retail",
    # asset
    "权益": "equity", "固收": "fixed_income", "衍生品": "derivatives",
    "商品": "commodities", "多资产": "multi_asset",
    # market
    "A股": "a_shares", "港股": "hk_equities", "美股": "us_equities",
    "债市": "bonds", "外汇": "fx",
    # style
    "简短": "concise", "详细": "detailed",
    # risk_appetite
    "保守": "conservative", "激进": "aggressive", "稳健": "conservative",
}


def _normalize(value: str | None) -> str | None:
    """Translate known Chinese profile values to English."""
    if value is None:
        return None
    return _ZH_TO_EN.get(value, value)


def _normalize_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(_ZH_TO_EN.get(v, v) for v in values))


def _clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return _normalize(cleaned) if cleaned else None
    return _normalize(str(value).strip()) or None


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = re.split(r"[，,、/]", value)
    elif isinstance(value, list):
        candidates = [str(item) for item in value]
    else:
        return []
    cleaned = [item.strip() for item in candidates if str(item).strip()]
    return _normalize_list(list(dict.fromkeys(cleaned)))


def _first_match(patterns: dict[str, re.Pattern[str]], text: str) -> str | None:
    for value, pattern in patterns.items():
        if pattern.search(text):
            return value
    return None


def _merge_lists(left: list[str], right: list[str]) -> list[str]:
    if not left and not right:
        return []
    return list(dict.fromkeys([*left, *right]))


def _merge_lists_capped(left: list[str], right: list[str], *, cap: int = 20) -> list[str]:
    """Merge two lists, deduplicating by last occurrence so re-mentioned items refresh recency."""
    if not left and not right:
        return []
    # Reverse, dedup (keeps first=latest), reverse back to preserve chronological order.
    combined = [*left, *right]
    seen: set[str] = set()
    deduped: list[str] = []
    for item in reversed(combined):
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    deduped.reverse()
    return deduped[-cap:]
