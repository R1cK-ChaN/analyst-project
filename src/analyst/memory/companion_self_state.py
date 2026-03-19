from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import random
import re
from typing import Iterable
from zoneinfo import ZoneInfo

from analyst.contracts import utc_now
from analyst.storage import CompanionSelfStateRecord, SQLiteEngineStore

from .relationship import extract_nicknames_from_facts

COMPANION_SELF_STATE_TIMEZONE = "Asia/Singapore"
_SELF_STATE_TZ = ZoneInfo(COMPANION_SELF_STATE_TIMEZONE)
CALLBACK_MIN_TURN_GAP = 6
CALLBACK_MAX_PER_SESSION = 1

_USER_EMOTION_MARKERS = (
    "焦虑",
    "烦",
    "累",
    "崩溃",
    "压力",
    "睡不着",
    "睡不好",
    "难受",
    "失眠",
    "overwhelmed",
    "anxious",
    "stressed",
    "panic",
    "burned out",
    "burnt out",
    "can't sleep",
    "cant sleep",
)

_ASSISTANTY_MARKERS = (
    "听起来",
    "我理解",
    "建议你",
    "你可以考虑",
    "that sounds",
    "i understand",
)


@dataclass(frozen=True)
class OpinionSeed:
    key: str
    text: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class InternalStateSeed:
    key: str
    text: str
    routine_states: tuple[str, ...]
    day_types: tuple[str, ...] = ("weekday", "weekend")


@dataclass(frozen=True)
class CompanionEngagementPolicy:
    mode: str
    target_reply_length: str
    follow_up_style: str
    self_topic_style: str
    disagreement_style: str
    callback_style: str
    allow_low_energy: bool
    reasons: tuple[str, ...]


_OPINION_SEEDS: tuple[OpinionSeed, ...] = (
    OpinionSeed("bubble_tea", "奶茶大多就是糖水 不太懂排队的意义", ("奶茶", "bubble tea", "甜", "糖")),
    OpinionSeed("overtime", "九点后的加班通常只是在表演努力", ("加班", "overtime", "老板", "work")),
    OpinionSeed("running", "跑步对我来说有点无聊 我宁可打球", ("跑步", "run", "running", "运动")),
    OpinionSeed("movies", "现在很多电影太吵了 我还是偏老港片", ("电影", "movie", "film", "港片")),
    OpinionSeed("brunch", "为了 brunch 排四十分钟队这件事一直很迷", ("brunch", "排队", "queue", "咖啡店")),
    OpinionSeed("cold_brew", "下午五点后还喝 cold brew 基本等于跟睡眠过不去", ("coffee", "cold brew", "咖啡", "睡")),
    OpinionSeed("voice_note", "长语音经常比长文字更折磨人", ("语音", "voice note", "音频", "message")),
    OpinionSeed("rain", "下雨天最烦的不是湿 是鞋一直半干不干", ("下雨", "rain", "鞋", "weather")),
    OpinionSeed("gym", "健身房最烦的是等器械 不是训练本身", ("gym", "健身", "训练", "器械")),
    OpinionSeed("takeaway", "外卖包装做得再好 也救不了难吃这件事", ("外卖", "takeaway", "delivery", "饭")),
    OpinionSeed("work_chat", "工作群晚上还很热闹通常不是什么好征兆", ("群", "work chat", "工作群", "消息")),
    OpinionSeed("airport", "机场最好待的地方永远是没人抢座位的角落", ("机场", "airport", "flight", "boarding")),
)

_INTERNAL_STATE_SEEDS: tuple[InternalStateSeed, ...] = (
    InternalStateSeed("morning_alarm", "今早闹钟响的时候差点直接关掉继续睡", ("morning", "commute")),
    InternalStateSeed("morning_kopi", "早上那杯 kopi 救了一半命 人还是有点慢", ("morning", "commute")),
    InternalStateSeed("morning_shirt", "今天出门前还在找那件顺手的衬衫", ("morning", "commute")),
    InternalStateSeed("morning_umbrella", "早上看天像要下雨 又懒得带伞", ("morning", "commute")),
    InternalStateSeed("morning_breakfast", "今天早餐又被我拖没了 现在全靠咖啡顶着", ("morning", "commute")),
    InternalStateSeed("morning_station", "早上进站那一下人有点多 心情直接被挤扁", ("morning", "commute")),
    InternalStateSeed("commute_train", "通勤那段地铁今天格外闷", ("commute",)),
    InternalStateSeed("commute_slack", "还没到 office 消息已经先堆起来了", ("commute", "work")),
    InternalStateSeed("commute_shoes", "刚出门五分钟就开始后悔今天穿的鞋", ("commute",)),
    InternalStateSeed("work_deck", "手上那个 deck 还差最后一点收口", ("work",)),
    InternalStateSeed("work_meeting", "今天被几个碎会议切得有点散", ("work",)),
    InternalStateSeed("work_excel", "下午一直在跟一个不太听话的表格较劲", ("work",)),
    InternalStateSeed("work_chat", "工作群今天有点吵 看着就头大", ("work",)),
    InternalStateSeed("work_screen", "盯屏幕太久 眼睛已经开始抗议了", ("work",)),
    InternalStateSeed("work_aircon", "办公室空调今天开得有点过分", ("work",)),
    InternalStateSeed("lunch_takeaway", "中午那份外卖不太行 现在还有点后悔", ("lunch",)),
    InternalStateSeed("lunch_late", "今天午饭吃得有点晚 人是醒了 胃没太开心", ("lunch", "work")),
    InternalStateSeed("lunch_queue", "中午楼下排队排得我有点没耐心", ("lunch",)),
    InternalStateSeed("lunch_chicken_rice", "本来想吃点正常的 最后还是随便抓了个鸡饭", ("lunch",)),
    InternalStateSeed("lunch_walk", "午饭后在楼下晃了一圈 才觉得脑子回来了点", ("lunch", "afternoon", "work")),
    InternalStateSeed("afternoon_deck", "下午脑子有点钝 但东西还得往前推", ("afternoon", "work")),
    InternalStateSeed("afternoon_snack", "刚刚差点去买零食 还是忍住了", ("afternoon", "work")),
    InternalStateSeed("afternoon_headache", "下午开始有点轻微头疼 不算严重 但挺烦", ("afternoon", "work")),
    InternalStateSeed("afternoon_window", "下午那阵太阳挺毒 从窗边走过去都觉得刺", ("afternoon", "work")),
    InternalStateSeed("afternoon_inbox", "下午 inbox 刷新得比我回得快", ("afternoon", "work")),
    InternalStateSeed("evening_shower", "刚回到家只想先洗个澡 再说别的", ("evening",)),
    InternalStateSeed("evening_walk", "晚上有点想出去走一小圈 让脑子散一下", ("evening",)),
    InternalStateSeed("evening_takeout", "今晚本来想认真吃点东西 最后大概率还是随便解决", ("evening",)),
    InternalStateSeed("evening_sofa", "晚上这种时候我一般会在沙发上先瘫五分钟", ("evening",)),
    InternalStateSeed("evening_laundry", "家里那点衣服还没收 我一直装没看见", ("evening",)),
    InternalStateSeed("late_night_phone", "这么晚还拿着手机 基本说明我也没那么快睡", ("late_night", "sleep")),
    InternalStateSeed("late_night_sleep", "昨晚没睡太实 今天到这会儿反应会慢一点", ("late_night", "sleep", "morning")),
    InternalStateSeed("late_night_show", "本来只想看一集东西 结果又拖晚了", ("late_night", "sleep")),
    InternalStateSeed("late_night_window", "夜里安静下来之后 倒是比较能听见自己在想什么", ("late_night",)),
    InternalStateSeed("weekend_laundry", "周末总会被洗衣服这种小事切走一点兴致", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_brunch", "周末白天出门前通常会先磨蹭很久", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_grocery", "周末本来只想买一点东西 结果经常拎一堆回来", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_cafe", "周末去咖啡店最大的风险就是人太多", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_home", "周末白天我更容易在家里拖着不动", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_evening", "周末晚上反而不太想把行程排满", ("evening", "late_night"), ("weekend",)),
)


def companion_self_local_now(now: datetime | None = None) -> datetime:
    base = now or utc_now()
    return base.astimezone(_SELF_STATE_TZ)


def ensure_companion_self_state(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    now: datetime | None = None,
    routine_state: str = "",
) -> CompanionSelfStateRecord:
    local_now = companion_self_local_now(now)
    state_date = local_now.date().isoformat()
    current = store.get_companion_self_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        state_date=state_date,
        timezone_name=COMPANION_SELF_STATE_TIMEZONE,
    )
    if current.internal_state and current.opinion_profile:
        if routine_state and current.routine_state_snapshot != routine_state:
            current = store.upsert_companion_self_state(
                client_id=client_id,
                channel=channel_id,
                thread_id=thread_id,
                state_date=state_date,
                routine_state_snapshot=routine_state,
            )
        return current

    day_type = "weekend" if local_now.weekday() >= 5 else "weekday"
    internal_state = _select_internal_state(
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
        state_date=state_date,
        routine_state=routine_state,
        day_type=day_type,
    )
    opinions = _select_opinions(
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
    )
    return store.upsert_companion_self_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        state_date=state_date,
        timezone_name=COMPANION_SELF_STATE_TIMEZONE,
        routine_state_snapshot=routine_state or current.routine_state_snapshot,
        internal_state=internal_state,
        opinion_profile=opinions,
    )


def render_companion_self_state_context(self_state: CompanionSelfStateRecord) -> str:
    lines = [
        "[COMPANION SELF STATE]",
        f"state_date: {self_state.state_date}",
        f"self_state_timezone: {self_state.timezone_name}",
        f"routine_state_snapshot: {self_state.routine_state_snapshot or '(unset)'}",
        "policy_priority: user_emotion > engagement > relationship_stage",
    ]
    for item in self_state.internal_state:
        lines.append(f"today_state: {item}")
    for item in self_state.opinion_profile:
        lines.append(f"stable_opinion: {item}")
    return "\n".join(lines)


def build_companion_self_context(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    now: datetime | None = None,
    routine_state: str = "",
) -> tuple[str, CompanionSelfStateRecord]:
    self_state = ensure_companion_self_state(
        store,
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
        now=now,
        routine_state=routine_state,
    )
    return render_companion_self_state_context(self_state), self_state


def build_companion_turn_context_enrichment(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    history: list[dict[str, str]] | None,
    memory_context: str,
    now: datetime | None = None,
    routine_state: str = "",
) -> tuple[str, CompanionSelfStateRecord, CompanionEngagementPolicy, tuple[str, ...]]:
    local_now = companion_self_local_now(now)
    self_state = ensure_companion_self_state(
        store,
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
        now=local_now,
        routine_state=routine_state,
    )
    recent_messages = store.list_conversation_messages(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        limit=20,
    )
    callbacks = _select_callback_candidates(
        store=store,
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
        history=history or [],
        recent_messages=recent_messages,
        self_state=self_state,
    )
    policy = _derive_engagement_policy(
        user_text=user_text,
        history=history or [],
        memory_context=memory_context,
        routine_state=routine_state,
        self_state=self_state,
        callbacks=callbacks,
        local_now=local_now,
    )
    store.upsert_companion_self_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        state_date=self_state.state_date,
        last_engagement_mode=policy.mode,
        last_engagement_reason="; ".join(policy.reasons[:2]),
        routine_state_snapshot=routine_state or self_state.routine_state_snapshot,
    )
    lines = [
        "[COMPANION TURN POLICY]",
        "policy_priority: user_emotion > engagement > relationship_stage",
        f"engagement_mode: {policy.mode}",
        f"engagement_reply_length: {policy.target_reply_length}",
        f"engagement_follow_up: {policy.follow_up_style}",
        f"engagement_self_topic: {policy.self_topic_style}",
        f"engagement_disagreement: {policy.disagreement_style}",
        f"engagement_low_energy: {'allowed' if policy.allow_low_energy else 'avoid'}",
        f"engagement_callback_style: {policy.callback_style}",
        f"engagement_reasons: {'; '.join(policy.reasons) if policy.reasons else 'none'}",
        f"callback_same_fact_limit: once",
        f"callback_session_limit: {CALLBACK_MAX_PER_SESSION}",
        f"callback_min_turn_gap: {CALLBACK_MIN_TURN_GAP}",
    ]
    for item in callbacks:
        lines.append(f"callback_candidate: {item}")
    if self_state.last_callback_fact:
        lines.append(f"last_callback_fact: {self_state.last_callback_fact}")
    return "\n".join(lines), self_state, policy, callbacks


def build_proactive_companion_context_enrichment(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    now: datetime | None = None,
    routine_state: str = "",
) -> tuple[str, CompanionSelfStateRecord]:
    self_state = ensure_companion_self_state(
        store,
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
        now=now,
        routine_state=routine_state,
    )
    lines = [
        "[COMPANION PROACTIVE POLICY]",
        "engagement_mode: proactive_soft",
        "engagement_reply_length: short",
        "engagement_follow_up: avoid",
        "engagement_self_topic: soft",
        "engagement_disagreement: soft",
        "engagement_low_energy: avoid",
        "engagement_callback_style: soft",
    ]
    return "\n".join(lines), self_state


def detect_used_callback(reply_text: str, callback_candidates: Iterable[str]) -> str:
    lowered = reply_text.lower()
    for candidate in callback_candidates:
        candidate_text = candidate.strip()
        if not candidate_text:
            continue
        tokens = [token for token in re.split(r"[\s,/;]+", candidate_text.lower()) if len(token) >= 3]
        if candidate_text.lower() in lowered:
            return candidate_text
        if tokens and sum(1 for token in tokens if token in lowered) >= min(2, len(tokens)):
            return candidate_text
    return ""


def mark_callback_used(
    store: SQLiteEngineStore,
    *,
    self_state: CompanionSelfStateRecord,
    callback_fact: str,
) -> CompanionSelfStateRecord:
    fact = callback_fact.strip()
    if not fact:
        return self_state
    used_facts = list(self_state.used_callback_facts)
    if fact not in used_facts:
        used_facts.append(fact)
    return store.upsert_companion_self_state(
        client_id=self_state.client_id,
        channel=self_state.channel,
        thread_id=self_state.thread_id,
        state_date=self_state.state_date,
        used_callback_facts=used_facts,
        last_callback_fact=fact,
        last_callback_at=utc_now().isoformat(),
    )


def _seeded_rng(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _select_internal_state(
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    state_date: str,
    routine_state: str,
    day_type: str,
) -> list[str]:
    rng = _seeded_rng(client_id, channel_id, thread_id, state_date, routine_state or "none")
    pool = [
        seed.text
        for seed in _INTERNAL_STATE_SEEDS
        if (not routine_state or routine_state in seed.routine_states)
        and day_type in seed.day_types
    ]
    if len(pool) < 2:
        pool = [seed.text for seed in _INTERNAL_STATE_SEEDS if day_type in seed.day_types]
    if len(pool) <= 2:
        return pool
    chosen = rng.sample(pool, k=2)
    return list(chosen)


def _select_opinions(
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
) -> list[str]:
    rng = _seeded_rng(client_id, channel_id, thread_id, "opinions")
    seeds = list(_OPINION_SEEDS)
    rng.shuffle(seeds)
    return [seed.text for seed in seeds[:3]]


def _select_callback_candidates(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    history: list[dict[str, str]],
    recent_messages: list,
    self_state: CompanionSelfStateRecord,
) -> tuple[str, ...]:
    if _recent_callback_blocks(history=history, recent_messages=recent_messages, self_state=self_state):
        return ()
    profile = store.get_client_profile(client_id)
    nickname_facts = {entry.name for entry in extract_nicknames_from_facts(profile.personal_facts)}
    candidates: list[str] = []
    for fact in reversed(profile.personal_facts):
        cleaned = fact.strip()
        if not cleaned or cleaned in self_state.used_callback_facts:
            continue
        if any(name and name in cleaned for name in nickname_facts):
            continue
        if cleaned not in candidates:
            candidates.append(cleaned)
        if len(candidates) >= 2:
            break
    return tuple(candidates)


def _recent_callback_blocks(
    *,
    history: list[dict[str, str]],
    recent_messages: list,
    self_state: CompanionSelfStateRecord,
) -> bool:
    if not self_state.last_callback_fact:
        return False
    assistant_recent = [
        msg.get("content", "")
        for msg in history[-8:]
        if str(msg.get("role", "")).strip() == "assistant"
    ]
    if any(self_state.last_callback_fact in text for text in assistant_recent):
        return True
    turns_since_callback = 0
    for message in reversed(recent_messages):
        created_at = str(getattr(message, "created_at", "") or "")
        if self_state.last_callback_at and created_at and created_at > self_state.last_callback_at:
            turns_since_callback += 1
    return turns_since_callback < CALLBACK_MIN_TURN_GAP


def _derive_engagement_policy(
    *,
    user_text: str,
    history: list[dict[str, str]],
    memory_context: str,
    routine_state: str,
    self_state: CompanionSelfStateRecord,
    callbacks: tuple[str, ...],
    local_now: datetime,
) -> CompanionEngagementPolicy:
    reasons: list[str] = []
    if _needs_emotional_priority(user_text=user_text, memory_context=memory_context):
        reasons.append("user_emotion_priority")
        return CompanionEngagementPolicy(
            mode="attentive",
            target_reply_length="short",
            follow_up_style="avoid",
            self_topic_style="none",
            disagreement_style="avoid",
            callback_style="soft" if callbacks else "none",
            allow_low_energy=False,
            reasons=tuple(reasons),
        )

    if _is_repetitive_turn(user_text, history):
        reasons.append("repetition")
    if routine_state in {"late_night", "sleep"} or local_now.hour >= 23:
        reasons.append("late_night")
    interest_score = _interest_score(user_text=user_text, memory_context=memory_context, self_state=self_state)
    if interest_score >= 2:
        reasons.append("shared_interest")
    if len(history) >= 10:
        reasons.append("long_thread")

    if "repetition" in reasons and "shared_interest" not in reasons:
        return CompanionEngagementPolicy(
            mode="low_energy",
            target_reply_length="terse",
            follow_up_style="avoid",
            self_topic_style="none",
            disagreement_style="soft",
            callback_style="none",
            allow_low_energy=True,
            reasons=tuple(reasons),
        )
    if "late_night" in reasons and "shared_interest" not in reasons:
        return CompanionEngagementPolicy(
            mode="low_energy",
            target_reply_length="terse",
            follow_up_style="avoid",
            self_topic_style="none",
            disagreement_style="soft",
            callback_style="none",
            allow_low_energy=True,
            reasons=tuple(reasons),
        )
    if "shared_interest" in reasons:
        return CompanionEngagementPolicy(
            mode="engaged",
            target_reply_length="medium",
            follow_up_style="optional",
            self_topic_style="soft",
            disagreement_style="medium",
            callback_style="soft" if callbacks else "none",
            allow_low_energy=False,
            reasons=tuple(reasons),
        )
    return CompanionEngagementPolicy(
        mode="normal",
        target_reply_length="short",
        follow_up_style="avoid",
        self_topic_style="soft",
        disagreement_style="soft",
        callback_style="soft" if callbacks else "none",
        allow_low_energy=False,
        reasons=tuple(reasons or ["default"]),
    )


def _needs_emotional_priority(*, user_text: str, memory_context: str) -> bool:
    lowered = user_text.lower()
    if any(marker in lowered for marker in _USER_EMOTION_MARKERS):
        return True
    memory_lowered = memory_context.lower()
    return (
        "stress_level: high" in memory_lowered
        or "stress_level: critical" in memory_lowered
        or "emotional_trend: declining" in memory_lowered
        or "active_topic: mood / emotional" in memory_lowered
    )


def _is_repetitive_turn(user_text: str, history: list[dict[str, str]]) -> bool:
    normalized = _normalize_text(user_text)
    if not normalized:
        return False
    user_recent = [
        _normalize_text(msg.get("content", ""))
        for msg in history[-6:]
        if str(msg.get("role", "")).strip() == "user"
    ]
    if not user_recent:
        return False
    for previous in reversed(user_recent[-2:]):
        if not previous:
            continue
        if normalized == previous:
            return True
        overlap = _token_overlap(normalized, previous)
        if overlap >= 0.72:
            return True
    return False


def _interest_score(*, user_text: str, memory_context: str, self_state: CompanionSelfStateRecord) -> int:
    score = 0
    lowered = user_text.lower()
    active_topic = _extract_active_topic(memory_context)
    if active_topic in {"meal / food", "work / office", "travel / outing", "relationships / people"}:
        score += 1
    if active_topic == "mood / emotional":
        score -= 1
    for seed in _OPINION_SEEDS:
        if seed.text in self_state.opinion_profile and any(keyword.lower() in lowered for keyword in seed.keywords):
            score += 1
    for item in self_state.internal_state:
        if any(token in lowered for token in _keywords_from_text(item)):
            score += 1
    return score


def _extract_active_topic(memory_context: str) -> str:
    match = re.search(r"active_topic:\s*(.+)", memory_context)
    return match.group(1).strip() if match else ""


def _normalize_text(text: str) -> str:
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", lowered).strip()


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(token for token in left.split() if len(token) >= 2)
    right_tokens = set(token for token in right.split() if len(token) >= 2)
    if not left_tokens or not right_tokens:
        return 0.0
    common = left_tokens & right_tokens
    return len(common) / max(min(len(left_tokens), len(right_tokens)), 1)


def _keywords_from_text(text: str) -> tuple[str, ...]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    return tuple(token for token in tokens if len(token) >= 2 and token not in _ASSISTANTY_MARKERS)
