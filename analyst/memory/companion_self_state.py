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
_SHARED_HISTORY_STAGES = {"familiar", "close"}

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

# Strong markers: inherently imperative, trigger helpful on their own
_PRACTICAL_STRONG_MARKERS = (
    "推荐", "告诉我", "帮我", "给我",
    "recommend", "tell me", "help me", "give me",
)

# Weak markers: need a second signal (question mark or strong marker)
_PRACTICAL_WEAK_MARKERS = (
    "有没有", "哪里", "哪个", "哪家", "怎么去", "几点",
    "开不开门", "多少钱", "在哪", "去哪", "好吃", "好喝",
    "附近", "名字", "具体", "地址", "营业",
    "where", "how to get", "which",
)

# Short follow-up cues that continue a previous helpful turn
_FOLLOWUP_CUES = ("呢", "具体", "然后呢", "所以", "比如", "还有吗", "else", "more", "?", "？")

_ASSISTANTY_MARKERS = (
    "听起来",
    "我理解",
    "建议你",
    "你可以考虑",
    "that sounds",
    "i understand",
)


def _is_practical_request(user_text: str, *, last_engagement_mode: str = "") -> bool:
    lowered = user_text.lower()
    # Strong markers always trigger
    if any(m in lowered for m in _PRACTICAL_STRONG_MARKERS):
        return True
    # Weak markers need question mark or co-occurring strong marker
    has_weak = any(m in lowered for m in _PRACTICAL_WEAK_MARKERS)
    if has_weak and ("?" in user_text or "？" in user_text):
        return True
    if has_weak and any(m in lowered for m in _PRACTICAL_STRONG_MARKERS):
        return True
    # Continue helpful mode on short follow-ups
    if last_engagement_mode == "helpful" and len(user_text) < 15:
        if any(cue in lowered for cue in _FOLLOWUP_CUES):
            return True
    return False


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
    inference_scope: str
    allow_low_energy: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RelationshipStagePolicy:
    callback_budget: int          # 0, 1, 2, 3
    teasing: str                  # "avoid" | "light" | "encouraged"
    question_budget_per_10: str   # "0-1" | "1-2" | "2-3" | "2-3_action"
    self_disclosure: str          # "surface" | "moderate" | "moderate-personal" | "personal"
    comfort_mode: str             # "none" | "action_only"
    disagreement_ceiling: str     # "low" | "soft" | "medium" | "high"


_STAGE_POLICIES = {
    "stranger": RelationshipStagePolicy(0, "avoid", "1-2", "surface", "none", "low"),
    "acquaintance": RelationshipStagePolicy(1, "avoid", "2-3", "moderate", "none", "soft"),
    "familiar": RelationshipStagePolicy(2, "light", "3-4", "moderate-personal", "action_only", "medium"),
    "close": RelationshipStagePolicy(3, "encouraged", "3-4_action", "personal", "action_only", "high"),
}


def resolve_stage_policy(stage: str) -> RelationshipStagePolicy:
    return _STAGE_POLICIES.get(stage, _STAGE_POLICIES["stranger"])


def apply_tendency_modifier(
    policy: RelationshipStagePolicy, dominant_tendency: str
) -> RelationshipStagePolicy:
    """Adjust stage policy based on dominant tendency. Only affects familiar/close."""
    if dominant_tendency == "romantic":
        return RelationshipStagePolicy(
            callback_budget=policy.callback_budget,
            teasing=policy.teasing,
            question_budget_per_10=policy.question_budget_per_10,
            self_disclosure=policy.self_disclosure,
            comfort_mode="action_proximity" if policy.comfort_mode == "action_only" else policy.comfort_mode,
            disagreement_ceiling=policy.disagreement_ceiling,
        )
    elif dominant_tendency == "confidant":
        budget = "3-4" if policy.question_budget_per_10 in ("2-3", "3-4") else policy.question_budget_per_10
        return RelationshipStagePolicy(
            callback_budget=policy.callback_budget,
            teasing=policy.teasing,
            question_budget_per_10=budget,
            self_disclosure=policy.self_disclosure,
            comfort_mode=policy.comfort_mode,
            disagreement_ceiling=policy.disagreement_ceiling,
        )
    return policy


_DISAGREEMENT_LEVELS = ("avoid", "low", "soft", "medium", "high")


def _clamp_disagreement(engagement_val: str, ceiling: str) -> str:
    eng_idx = _DISAGREEMENT_LEVELS.index(engagement_val) if engagement_val in _DISAGREEMENT_LEVELS else 1
    ceil_idx = _DISAGREEMENT_LEVELS.index(ceiling) if ceiling in _DISAGREEMENT_LEVELS else 1
    return _DISAGREEMENT_LEVELS[min(eng_idx, ceil_idx)]


def _apply_stage_ceiling(
    policy: CompanionEngagementPolicy,
    stage_policy: RelationshipStagePolicy,
) -> CompanionEngagementPolicy:
    clamped_disagreement = _clamp_disagreement(policy.disagreement_style, stage_policy.disagreement_ceiling)
    clamped_callback = "none" if stage_policy.callback_budget == 0 else policy.callback_style
    return CompanionEngagementPolicy(
        mode=policy.mode,
        target_reply_length=policy.target_reply_length,
        follow_up_style=policy.follow_up_style,
        self_topic_style=policy.self_topic_style,
        disagreement_style=clamped_disagreement,
        callback_style=clamped_callback,
        inference_scope=policy.inference_scope,
        allow_low_energy=policy.allow_low_energy,
        reasons=policy.reasons,
    )


_LOW_ENGAGEMENT_TOKENS = frozenset({
    "好的", "ok", "嗯", "哦", "行", "嗯嗯", "俄呐", "噢", "知道了",
    "好", "好吧", "收到", "了解", "sure", "yeah", "yep", "alright",
    "got it", "right", "cool", "nice", "k",
})


def _is_low_engagement(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 5:
        return True
    return stripped.lower() in _LOW_ENGAGEMENT_TOKENS


def _detect_user_disengagement(history: list[dict[str, str]]) -> bool:
    recent = history[-6:]
    # Build (preceding_assistant, user_text) pairs
    pairs: list[tuple[str, str]] = []
    for i, msg in enumerate(recent):
        if str(msg.get("role", "")).strip() != "user":
            continue
        prev_assistant = ""
        for j in range(i - 1, -1, -1):
            if str(recent[j].get("role", "")).strip() == "assistant":
                prev_assistant = recent[j].get("content", "")
                break
        pairs.append((prev_assistant, msg.get("content", "")))
    last_three = pairs[-3:] if len(pairs) >= 3 else pairs
    if len(last_three) < 2:
        return False
    low_count = 0
    for prev_asst, user_text in last_three:
        if not _is_low_engagement(user_text):
            continue
        # Brief answer to a direct question is normal, not disengagement
        stripped = prev_asst.rstrip()
        if stripped.endswith("？") or stripped.endswith("?"):
            continue
        low_count += 1
    return low_count >= 2


def _detect_self_focus_drift(history: list[dict[str, str]]) -> bool:
    assistant_msgs = [
        msg.get("content", "")
        for msg in history[-6:]
        if str(msg.get("role", "")).strip() == "assistant"
    ]
    if not assistant_msgs:
        return False

    def _is_self_focused(text: str) -> bool:
        return "我" in text and "你" not in text and "你们" not in text

    # Case 1: last 2 assistant messages both self-focused
    if len(assistant_msgs) >= 2 and all(_is_self_focused(m) for m in assistant_msgs[-2:]):
        return True
    # Case 2: last 1 assistant message self-focused AND last user reply is low_engagement
    user_msgs = [
        msg.get("content", "")
        for msg in history[-4:]
        if str(msg.get("role", "")).strip() == "user"
    ]
    if assistant_msgs and _is_self_focused(assistant_msgs[-1]) and user_msgs and _is_low_engagement(user_msgs[-1]):
        return True
    return False


def _extract_dominant_tendency(memory_context: str) -> str:
    match = re.search(r"tendency_dominant:\s*(\w+)", memory_context)
    return match.group(1) if match else ""


_OPINION_SEEDS: tuple[OpinionSeed, ...] = (
    OpinionSeed("bubble_tea", "奶茶大多就是糖水 不太懂排队的意义", ("奶茶", "bubble tea", "甜", "糖")),
    OpinionSeed("overtime", "九点后的加班通常只是在表演努力", ("加班", "overtime", "老板", "work")),
    OpinionSeed("small_talk", "硬撑着聊无效社交比加班还累", ("社交", "small talk", "应酬", "awkward")),
    OpinionSeed("plans", "临时改计划这件事 我通常没什么耐心", ("plan", "plans", "改计划", "临时")),
    OpinionSeed("weekend_plans", "周末行程排太满最后大多只会更累", ("weekend", "周末", "行程", "安排")),
    OpinionSeed("spending", "为了省十块钱绕半个小时路很不值", ("省钱", "折扣", "便宜", "delivery fee")),
    OpinionSeed("work_jargon", "工作里最烦的不是忙 是一堆空话套话", ("汇报", "jargon", "套话", "汇报")),
    OpinionSeed("messaging", "一串分开发来的短消息比一条长消息更折磨人", ("消息", "text", "message", "微信")),
    OpinionSeed("group_dinner", "团建吃饭最累的部分通常不是饭 是前后的客套", ("团建", "dinner", "聚餐", "吃饭")),
    OpinionSeed("shopping", "为了拍照好看去一家店 我一般做不到", ("拍照", "shopping", "店", "打卡")),
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
    # ── morning / commute ──
    InternalStateSeed("morning_alarm", "今早居然在闹钟前就醒了 精神还不错", ("morning", "commute")),
    InternalStateSeed("morning_kopi", "早上那杯 kopi 今天特别顺 一口下去人就活了", ("morning", "commute")),
    InternalStateSeed("morning_shirt", "今天翻出一件很久没穿的衬衫 意外地好看", ("morning", "commute")),
    InternalStateSeed("morning_umbrella", "早上出门看天超好 心情直接起来了", ("morning", "commute")),
    InternalStateSeed("morning_breakfast", "今天居然有时间吃了个早餐 太难得了", ("morning", "commute")),
    InternalStateSeed("morning_station", "早上进站的时候正好有座 今天运气真好", ("morning", "commute")),
    InternalStateSeed("commute_train", "通勤的地铁今天空调坏了 真的想骂人", ("commute",)),
    InternalStateSeed("commute_slack", "还没到 office 就看到一条好消息 今天有盼头", ("commute", "work")),
    InternalStateSeed("commute_shoes", "今天穿的这双鞋太舒服了 走路都带风", ("commute",)),
    # ── work ──
    InternalStateSeed("work_deck", "手上那个 deck 终于收口了 爽", ("work",)),
    InternalStateSeed("work_meeting", "今天开会居然碰出一个不错的想法 有点兴奋", ("work",)),
    InternalStateSeed("work_excel", "下午那个表格我弄了两小时 差点砸键盘", ("work",)),
    InternalStateSeed("work_chat", "工作群今天有个人说了句超好笑的话 我差点笑出声", ("work",)),
    InternalStateSeed("work_screen", "刚发现一个新的快捷键 效率直接翻倍 太爽了", ("work",)),
    InternalStateSeed("work_aircon", "办公室空调今天终于正常了 感动", ("work",)),
    # ── lunch ──
    InternalStateSeed("lunch_takeaway", "中午吃的那个咖喱饭真的绝了 想再去一次", ("lunch",)),
    InternalStateSeed("lunch_late", "中午吃晚了但是那碗叻沙太值了 完全不后悔", ("lunch", "work")),
    InternalStateSeed("lunch_queue", "中午排了半天队 但吃到那一口觉得值了", ("lunch",)),
    InternalStateSeed("lunch_chicken_rice", "今天那份鸡饭酱料给得特别足 老板太实在了", ("lunch",)),
    InternalStateSeed("lunch_walk", "午饭后在楼下晃了一圈 太阳刚好 人一下就松了", ("lunch", "afternoon", "work")),
    # ── afternoon ──
    InternalStateSeed("afternoon_deck", "下午突然来了状态 一口气推完了一大块", ("afternoon", "work")),
    InternalStateSeed("afternoon_snack", "刚买了个零食 太好吃了 后悔没多买一包", ("afternoon", "work")),
    InternalStateSeed("afternoon_headache", "下午头疼得我喝了三杯水 还是没用 烦死了", ("afternoon", "work")),
    InternalStateSeed("afternoon_window", "下午窗外突然下了阵雨 看着特别爽", ("afternoon", "work")),
    InternalStateSeed("afternoon_inbox", "下午居然提前把事情都清完了 难得的成就感", ("afternoon", "work")),
    # ── evening ──
    InternalStateSeed("evening_shower", "刚洗完澡 整个人焕然一新 太舒服了", ("evening",)),
    InternalStateSeed("evening_walk", "刚出去走了一圈 晚上的风真的太舒服了", ("evening",)),
    InternalStateSeed("evening_takeout", "今晚叫的外卖居然超好吃 赚到了", ("evening",)),
    InternalStateSeed("evening_sofa", "瘫在沙发上 旁边放着刚泡的茶 这一刻完美", ("evening",)),
    InternalStateSeed("evening_laundry", "家里那堆衣服还没收 我选择性失明了 哈哈", ("evening",)),
    # ── late night ──
    InternalStateSeed("late_night_phone", "这么晚还在刷手机 但刚看到一个超有意思的东西", ("late_night", "sleep")),
    InternalStateSeed("late_night_sleep", "昨晚没睡好 但今天反而精神不错 也是奇怪", ("late_night", "sleep", "morning")),
    InternalStateSeed("late_night_show", "昨晚看了部纪录片 太好看了 差点不想睡", ("late_night", "sleep")),
    InternalStateSeed("late_night_window", "夜里安静的时候 脑子反而特别活跃 想法一个接一个", ("late_night",)),
    # ── weekend ──
    InternalStateSeed("weekend_laundry", "周末洗衣服的时候听了个播客 时间一下就过去了", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_brunch", "周末出门吃了个 brunch 环境太好了 拍了好多照片", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_grocery", "周末去超市本来只想买一点 结果发现好多新东西 拎了一大袋", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_cafe", "周末找了家没人的咖啡店 位置绝了 想天天来", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_home", "周末在家发现了一个新的歌单 太对味了", ("weekend_day",), ("weekend",)),
    InternalStateSeed("weekend_evening", "周末晚上没什么安排 反而觉得特别自在", ("evening", "late_night"), ("weekend",)),
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
) -> tuple[str, CompanionSelfStateRecord, CompanionEngagementPolicy, tuple[str, ...], RelationshipStagePolicy]:
    local_now = companion_self_local_now(now)
    relationship_stage = _extract_relationship_stage(memory_context)
    shared_history_gate = "open" if relationship_stage in _SHARED_HISTORY_STAGES else "locked"
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
        relationship_stage=relationship_stage,
    )
    policy = _derive_engagement_policy(
        user_text=user_text,
        history=history or [],
        memory_context=memory_context,
        routine_state=routine_state,
        self_state=self_state,
        callbacks=callbacks,
        local_now=local_now,
        relationship_stage=relationship_stage,
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
    # Resolve stage policy with tendency modifier
    stage_policy = resolve_stage_policy(relationship_stage)
    dominant_tendency = _extract_dominant_tendency(memory_context)
    if dominant_tendency:
        stage_policy = apply_tendency_modifier(stage_policy, dominant_tendency)

    lines = [
        "[COMPANION TURN POLICY]",
        "policy_priority: user_emotion > engagement > relationship_stage",
        f"relationship_stage_hint: {relationship_stage}",
        f"shared_history_gate: {shared_history_gate}",
        f"engagement_mode: {policy.mode}",
        f"engagement_reply_length: {policy.target_reply_length}",
        f"engagement_follow_up: {policy.follow_up_style}",
        f"engagement_self_topic: {policy.self_topic_style}",
        f"engagement_disagreement: {policy.disagreement_style}",
        f"engagement_low_energy: {'allowed' if policy.allow_low_energy else 'avoid'}",
        f"engagement_callback_style: {policy.callback_style}",
        f"engagement_inference_scope: {policy.inference_scope}",
        f"engagement_reasons: {'; '.join(policy.reasons) if policy.reasons else 'none'}",
        f"stage_callback_budget: {stage_policy.callback_budget}",
        f"stage_teasing: {stage_policy.teasing}",
        f"stage_question_budget: {stage_policy.question_budget_per_10}",
        f"stage_self_disclosure: {stage_policy.self_disclosure}",
        f"stage_comfort_mode: {stage_policy.comfort_mode}",
        f"stage_disagreement_ceiling: {stage_policy.disagreement_ceiling}",
        f"callback_same_fact_limit: once",
        f"callback_session_limit: {stage_policy.callback_budget}",
        f"callback_min_turn_gap: {CALLBACK_MIN_TURN_GAP}",
    ]
    for item in callbacks:
        lines.append(f"callback_candidate: {item}")
    if self_state.last_callback_fact:
        lines.append(f"last_callback_fact: {self_state.last_callback_fact}")
    # Generation hint for topic_invite
    if policy.follow_up_style == "topic_invite":
        # If last assistant message already ended with a question, don't ask another
        last_asst_was_question = False
        for msg in reversed(history or []):
            if str(msg.get("role", "")).strip() == "assistant":
                content = msg.get("content", "").rstrip()
                last_asst_was_question = content.endswith("？") or content.endswith("?")
                break
        if last_asst_was_question:
            lines.append("[GENERATION HINT] 这一轮你应该停止聊自己的事，把话题引向对方——说一个跟对方有关的观察或想法，但这轮不要用问句。")
        else:
            lines.append("[GENERATION HINT] 这一轮你应该停止聊自己的事，把话题引向对方。问一个轻量的peer式问题。")
    if policy.mode == "helpful":
        lines.append("[GENERATION HINT] 用户在问一个具体问题。用 web_search 搜真实答案，不要给泛泛的建议。")
    return "\n".join(lines), self_state, policy, callbacks, stage_policy


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
        "engagement_inference_scope: own_or_stated_only",
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
    relationship_stage: str,
) -> tuple[str, ...]:
    if relationship_stage not in _SHARED_HISTORY_STAGES:
        return ()
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
    relationship_stage: str,
) -> CompanionEngagementPolicy:
    reasons: list[str] = []
    inference_scope = "own_or_stated_only" if relationship_stage in {"stranger", "acquaintance"} else "light"
    stage_policy = resolve_stage_policy(relationship_stage)

    if _needs_emotional_priority(user_text=user_text, memory_context=memory_context):
        reasons.append("user_emotion_priority")
        return _apply_stage_ceiling(
            CompanionEngagementPolicy(
                mode="attentive",
                target_reply_length="short",
                follow_up_style="avoid",
                self_topic_style="none",
                disagreement_style="avoid",
                callback_style="soft" if callbacks else "none",
                inference_scope=inference_scope,
                allow_low_energy=False,
                reasons=tuple(reasons),
            ),
            stage_policy,
        )

    # Practical request: user explicitly asking for help — override dry mode
    if _is_practical_request(user_text, last_engagement_mode=self_state.last_engagement_mode):
        reasons.append("practical_request")
        return _apply_stage_ceiling(
            CompanionEngagementPolicy(
                mode="helpful",
                target_reply_length="medium",
                follow_up_style="avoid",
                self_topic_style="none",
                disagreement_style="soft",
                callback_style="none",
                inference_scope=inference_scope,
                allow_low_energy=False,
                reasons=tuple(reasons),
            ),
            stage_policy,
        )

    # User disengagement detection (high priority, after emotion)
    user_disengaging = _detect_user_disengagement(history)
    self_focus_drift = _detect_self_focus_drift(history)
    if user_disengaging:
        reasons.append("user_disengaging")
    if self_focus_drift and relationship_stage in ("familiar", "close"):
        reasons.append("reciprocity_redirect")

    if _is_repetitive_turn(user_text, history):
        reasons.append("repetition")
    if routine_state in {"late_night", "sleep"} or local_now.hour >= 23:
        reasons.append("late_night")
    interest_score = _interest_score(user_text=user_text, memory_context=memory_context, self_state=self_state)
    if interest_score >= 2:
        reasons.append("shared_interest")
    if len(history) >= 10:
        reasons.append("long_thread")

    # User disengagement or reciprocity redirect → topic_invite
    if "user_disengaging" in reasons or "reciprocity_redirect" in reasons:
        return _apply_stage_ceiling(
            CompanionEngagementPolicy(
                mode="normal",
                target_reply_length="short",
                follow_up_style="topic_invite",
                self_topic_style="none",
                disagreement_style="soft",
                callback_style="soft" if callbacks else "none",
                inference_scope=inference_scope,
                allow_low_energy=False,
                reasons=tuple(reasons),
            ),
            stage_policy,
        )

    if "repetition" in reasons and "shared_interest" not in reasons:
        return _apply_stage_ceiling(
            CompanionEngagementPolicy(
                mode="low_energy",
                target_reply_length="terse",
                follow_up_style="avoid",
                self_topic_style="none",
                disagreement_style="soft",
                callback_style="none",
                inference_scope=inference_scope,
                allow_low_energy=True,
                reasons=tuple(reasons),
            ),
            stage_policy,
        )
    if "late_night" in reasons and "shared_interest" not in reasons:
        return _apply_stage_ceiling(
            CompanionEngagementPolicy(
                mode="low_energy",
                target_reply_length="terse",
                follow_up_style="avoid",
                self_topic_style="none",
                disagreement_style="soft",
                callback_style="none",
                inference_scope=inference_scope,
                allow_low_energy=True,
                reasons=tuple(reasons),
            ),
            stage_policy,
        )
    if "shared_interest" in reasons:
        return _apply_stage_ceiling(
            CompanionEngagementPolicy(
                mode="engaged",
                target_reply_length="medium",
                follow_up_style="optional",
                self_topic_style="soft",
                disagreement_style="medium",
                callback_style="soft" if callbacks else "none",
                inference_scope=inference_scope,
                allow_low_energy=False,
                reasons=tuple(reasons),
            ),
            stage_policy,
        )
    return _apply_stage_ceiling(
        CompanionEngagementPolicy(
            mode="normal",
            target_reply_length="short",
            follow_up_style="optional",
            self_topic_style="soft",
            disagreement_style="soft",
            callback_style="soft" if callbacks else "none",
            inference_scope=inference_scope,
            allow_low_energy=False,
            reasons=tuple(reasons or ["default"]),
        ),
        stage_policy,
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


def _extract_relationship_stage(memory_context: str) -> str:
    english = re.search(r"relationship_stage:\s*(\w+)", memory_context)
    if english:
        return english.group(1)
    chinese = re.search(r"关系阶段:\s*(\w+)", memory_context)
    if chinese:
        return chinese.group(1)
    return "stranger"


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
