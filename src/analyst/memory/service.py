from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any

from analyst.macro_data import MacroDataClient
from analyst.storage import (
    ClientProfileRecord,
    DeliveryQueueRecord,
    GroupMemberRecord,
    GroupMessageRecord,
    SQLiteEngineStore,
)

from .profile import ClientProfileUpdate, extract_client_profile_update, merge_client_profile_updates
from .render import RenderBudget, render_context_sections, trim_text

_GROUP_HUMOR_MARKERS = (
    "lol",
    "lmao",
    "haha",
    "hehe",
    "rofl",
    "哈哈",
    "哈哈哈",
    "hhh",
    "233",
    "xd",
    "😂",
    "🤣",
    "😆",
)
_GROUP_SUPPORT_MARKERS = (
    "you got this",
    "hang in there",
    "take care",
    "hope you're okay",
    "hope youre okay",
    "proud of you",
    "加油",
    "抱抱",
    "辛苦了",
    "别慌",
    "没事",
    "稳住",
    "你可以",
    "理解你",
    "懂你",
)
_GROUP_TENSION_MARKERS = (
    "stop bullying",
    "shut up",
    "wtf",
    "够了",
    "闭嘴",
    "别闹",
    "烦死",
    "少来",
)


def build_research_context(
    store: SQLiteEngineStore,
    *,
    data_client: MacroDataClient | None = None,
    budget: RenderBudget | None = None,
) -> str:
    limits = budget or RenderBudget(total_chars=4500)
    snapshots = store.list_recent_regime_snapshots(limit=3)
    notes = store.list_recent_generated_notes(limit=3)
    observations = store.list_recent_analytical_observations(limit=4)
    if data_client is None:
        recent_events: list[Any] = store.list_recent_events(limit=18, days=14, released_only=True)
    else:
        recent_events = data_client.invoke("get_recent_releases", {"limit": 18, "days": 14}).get("events", [])

    sections: list[tuple[str, list[str]]] = []

    regime_lines = [
        f"- {snapshot.timestamp}: {trim_text(snapshot.summary, max_chars=limits.max_item_chars)}"
        for snapshot in snapshots
    ]
    sections.append(("最近状态轨迹", regime_lines))

    surprise_lines = _render_surprise_patterns(recent_events, limits=limits)
    sections.append(("最近数据模式", surprise_lines))

    observation_lines = [
        f"- {observation.observation_type}: {trim_text(observation.summary, max_chars=limits.max_item_chars)}"
        for observation in observations
    ]
    sections.append(("分析观察", observation_lines))

    note_lines = [
        f"- {note.title}: {trim_text(note.summary, max_chars=limits.max_item_chars)}"
        for note in notes
    ]
    sections.append(("近期研究输出", note_lines))

    return render_context_sections(sections, budget=limits)


def build_trading_context(
    store: SQLiteEngineStore,
    *,
    budget: RenderBudget | None = None,
) -> str:
    limits = budget or RenderBudget(total_chars=4500)
    research = store.list_recent_research_artifacts(limit=limits.max_research_items)
    trading = store.list_recent_trading_artifacts(limit=limits.max_trading_items)
    decisions = store.list_recent_decisions(limit=4)
    positions = store.list_position_state(limit=6)
    performance = store.list_recent_performance_records(limit=4)

    sections = [
        (
            "最新研究",
            [f"- {item.title}: {trim_text(item.summary, max_chars=limits.max_item_chars)}" for item in research],
        ),
        (
            "当前仓位",
            [
                f"- {item.symbol}: {item.direction} {item.exposure:.2f} | {trim_text(item.thesis, max_chars=limits.max_item_chars)}"
                for item in positions
            ],
        ),
        (
            "最近决策",
            [f"- {item.title}: {trim_text(item.summary, max_chars=limits.max_item_chars)}" for item in decisions],
        ),
        (
            "已发布交易观点",
            [f"- {item.title}: {trim_text(item.summary, max_chars=limits.max_item_chars)}" for item in trading],
        ),
        (
            "表现记录",
            [f"- {item.metric_name} {item.period_label}: {item.metric_value:.2f}" for item in performance],
        ),
    ]
    return render_context_sections(sections, budget=limits)


def build_sales_context(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    query: str,
    budget: RenderBudget | None = None,
) -> str:
    limits = budget or RenderBudget()
    profile = store.get_client_profile(client_id)
    recent_messages = store.list_conversation_messages(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        limit=limits.max_recent_messages,
    )
    # Deliveries are client-scoped rather than thread-scoped so sales can avoid
    # repeating previously sent research across new threads with the same client.
    relevant_deliveries = store.search_delivery_queue(
        client_id=client_id,
        query=query,
        channel=channel_id,
        limit=limits.max_delivery_items,
    )
    if not relevant_deliveries:
        relevant_deliveries = store.list_recent_deliveries(
            client_id=client_id,
            channel=channel_id,
            limit=limits.max_delivery_items,
        )

    sections = [
        (
            "client_profile",
            _render_client_profile(profile),
        ),
        (
            "sent_content",
            _render_delivery_history(relevant_deliveries, limits=limits),
        ),
        (
            "current_thread",
            [
                f"- {message.role}: {trim_text(message.content, max_chars=limits.max_item_chars)}"
                for message in recent_messages
            ],
        ),
    ]
    return render_context_sections(sections, budget=limits)


def build_chat_context(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    query: str,
    persona_mode: str = "sales",
    budget: RenderBudget | None = None,
) -> str:
    if str(persona_mode).strip().lower() != "companion":
        return build_sales_context(
            store=store,
            client_id=client_id,
            channel_id=channel_id,
            thread_id=thread_id,
            query=query,
            budget=budget,
        )

    limits = budget or RenderBudget()
    profile = store.get_client_profile(client_id)
    recent_messages = store.list_conversation_messages(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        limit=limits.max_recent_messages,
    )
    sections = [
        (
            "client_profile",
            _render_companion_profile(profile),
        ),
        (
            "current_thread",
            [
                f"- {message.role}: {trim_text(message.content, max_chars=limits.max_item_chars)}"
                for message in recent_messages
            ],
        ),
    ]
    return render_context_sections(sections, budget=limits)


def record_sales_interaction(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    assistant_profile_update: ClientProfileUpdate | None = None,
    tool_audit: list[dict[str, Any]] | None = None,
) -> None:
    update = merge_client_profile_updates(
        extract_client_profile_update(user_text),
        assistant_profile_update or ClientProfileUpdate(),
    )
    store.record_sales_interaction(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        tool_audit=tool_audit or [],
        profile_updates={
            "preferred_language": update.preferred_language,
            "watchlist_topics": update.watchlist_topics,
            "response_style": update.response_style,
            "risk_appetite": update.risk_appetite,
            "investment_horizon": update.investment_horizon,
            "institution_type": update.institution_type,
            "risk_preference": update.risk_preference,
            "asset_focus": update.asset_focus,
            "market_focus": update.market_focus,
            "expertise_level": update.expertise_level,
            "activity": update.activity,
            "current_mood": update.current_mood,
            "emotional_trend": update.emotional_trend,
            "stress_level": update.stress_level,
            "confidence": update.confidence,
            "notes": update.notes,
            "personal_facts": update.personal_facts,
        },
    )


def record_chat_interaction(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    assistant_profile_update: ClientProfileUpdate | None = None,
    tool_audit: list[dict[str, Any]] | None = None,
    persona_mode: str = "sales",
) -> None:
    if str(persona_mode).strip().lower() != "companion":
        record_sales_interaction(
            store=store,
            client_id=client_id,
            channel_id=channel_id,
            thread_id=thread_id,
            user_text=user_text,
            assistant_text=assistant_text,
            assistant_profile_update=assistant_profile_update,
            tool_audit=tool_audit,
        )
        return

    update = merge_client_profile_updates(
        _companion_only_update(extract_client_profile_update(user_text)),
        _companion_only_update(assistant_profile_update or ClientProfileUpdate()),
    )
    store.record_sales_interaction(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        tool_audit=tool_audit or [],
        profile_updates={
            "preferred_language": update.preferred_language,
            "response_style": update.response_style,
            "current_mood": update.current_mood,
            "emotional_trend": update.emotional_trend,
            "stress_level": update.stress_level,
            "confidence": update.confidence,
            "notes": update.notes,
            "personal_facts": update.personal_facts,
        },
    )


def build_group_chat_context(
    *,
    store: SQLiteEngineStore,
    group_id: str,
    thread_id: str,
    speaker_user_id: str,
    persona_mode: str = "sales",
    budget: RenderBudget | None = None,
) -> str:
    """Build group chat context: messages + speaker memory + participants + inferred roles + social graph."""
    limits = budget or RenderBudget()

    # Layer 1: Group conversation (working memory)
    group_messages = store.list_group_messages(group_id, thread_id, limit=20)
    group_lines = [
        f"- {msg.display_name}: {trim_text(msg.content, max_chars=limits.max_item_chars)}"
        for msg in group_messages
    ]

    # Layer 2: Speaker's user memory (long-term memory, shared across contexts)
    speaker_profile = store.get_client_profile(speaker_user_id)
    is_companion = str(persona_mode).strip().lower() == "companion"
    if is_companion:
        speaker_lines = _render_companion_profile(speaker_profile)
    else:
        speaker_lines = _render_client_profile(speaker_profile)

    # Layer 3: Participant model (who's in this group)
    members = store.list_group_members(group_id, limit=15)
    participant_lines = _render_participant_model(members, current_speaker_id=speaker_user_id)

    # Layer 4: Public-only inferred roles/persona hints
    recent_group_messages = store.list_recent_group_messages(group_id, limit=80)
    inferred_members = _resolve_group_member_inference(members, recent_group_messages)
    role_lines = _render_group_roles(
        members,
        inferred_members,
        current_speaker_id=speaker_user_id,
    )

    # Layer 5: Public-only thread social graph, derived on demand
    social_lines = _render_group_social_graph(group_messages, members)

    sections: list[tuple[str, list[str]]] = [
        ("group_conversation", group_lines),
        ("speaker_memory", speaker_lines),
        ("group_roles", role_lines),
        ("group_social_graph", social_lines),
        ("group_participants", participant_lines),
    ]
    return render_context_sections(sections, budget=limits)


def _render_participant_model(
    members: list[GroupMemberRecord],
    *,
    current_speaker_id: str = "",
) -> list[str]:
    lines: list[str] = []
    for member in members:
        parts = [member.display_name or member.user_id]
        if member.user_id == current_speaker_id:
            parts.append("(current speaker)")
        parts.append(f"msgs: {member.message_count}")
        lines.append(f"- {' | '.join(parts)}")
    return lines


def refresh_group_member_public_inference(
    *,
    store: SQLiteEngineStore,
    group_id: str,
    limit: int = 80,
) -> None:
    members = store.list_group_members(group_id, limit=100)
    if not members:
        return
    recent_messages = store.list_recent_group_messages(group_id, limit=limit)
    inferred_members = _derive_group_member_inference(members, recent_messages)
    for member in members:
        role_in_group, personality_notes = inferred_members.get(member.user_id, ("", ""))
        if role_in_group == member.role_in_group and personality_notes == member.personality_notes:
            continue
        store.update_group_member_inference(
            group_id=group_id,
            user_id=member.user_id,
            role_in_group=role_in_group,
            personality_notes=personality_notes,
        )


def _resolve_group_member_inference(
    members: list[GroupMemberRecord],
    group_messages: list[GroupMessageRecord],
) -> dict[str, tuple[str, str]]:
    derived = _derive_group_member_inference(members, group_messages)
    resolved: dict[str, tuple[str, str]] = {}
    for member in members:
        derived_role, derived_notes = derived.get(member.user_id, ("", ""))
        resolved[member.user_id] = (
            member.role_in_group or derived_role,
            member.personality_notes or derived_notes,
        )
    return resolved


def _derive_group_member_inference(
    members: list[GroupMemberRecord],
    group_messages: list[GroupMessageRecord],
) -> dict[str, tuple[str, str]]:
    stats = _collect_group_member_stats(members, group_messages)
    total_recent_messages = sum(stat["recent_messages"] for stat in stats.values())
    inferred: dict[str, tuple[str, str]] = {}
    for member in members:
        member_stats = stats.get(member.user_id, _empty_group_member_stats())
        role = _infer_group_role(member, member_stats, total_recent_messages=total_recent_messages)
        notes = _build_group_personality_notes(
            member,
            member_stats,
            role=role,
            total_recent_messages=total_recent_messages,
        )
        inferred[member.user_id] = (role, notes)
    return inferred


def _collect_group_member_stats(
    members: list[GroupMemberRecord],
    group_messages: list[GroupMessageRecord],
) -> dict[str, dict[str, Any]]:
    stats = {member.user_id: _empty_group_member_stats() for member in members}
    human_members = [member for member in members if member.user_id != "assistant"]
    previous_human_user_id = ""
    for message in group_messages:
        if message.user_id == "assistant":
            previous_human_user_id = ""
            continue
        if message.user_id not in stats:
            continue
        text = str(message.content or "").strip()
        member_stats = stats[message.user_id]
        member_stats["recent_messages"] += 1
        member_stats["char_total"] += len(text)
        if "?" in text or "？" in text:
            member_stats["questions"] += 1
        member_stats["humor"] += _count_markers(text, _GROUP_HUMOR_MARKERS)
        member_stats["support"] += _count_markers(text, _GROUP_SUPPORT_MARKERS)
        mentions = _extract_public_mentions(text, human_members, speaker_user_id=message.user_id)
        member_stats["mentions"] += len(mentions)
        member_stats["interacted_with"].update(mentions)
        if previous_human_user_id and previous_human_user_id != message.user_id:
            member_stats["interacted_with"].add(previous_human_user_id)
        previous_human_user_id = message.user_id
    return stats


def _empty_group_member_stats() -> dict[str, Any]:
    return {
        "recent_messages": 0,
        "char_total": 0,
        "questions": 0,
        "humor": 0,
        "support": 0,
        "mentions": 0,
        "interacted_with": set(),
    }


def _infer_group_role(
    member: GroupMemberRecord,
    stats: dict[str, Any],
    *,
    total_recent_messages: int,
) -> str:
    recent_messages = int(stats["recent_messages"])
    if recent_messages <= 1 and member.message_count <= 2:
        return "quiet_observer"
    if recent_messages <= 0 or total_recent_messages <= 0:
        return ""

    message_share = recent_messages / total_recent_messages
    question_ratio = stats["questions"] / max(recent_messages, 1)
    if message_share >= 0.4 and recent_messages >= 4:
        return "leader"
    if stats["support"] >= 2 and len(stats["interacted_with"]) >= 2:
        return "mediator"
    if stats["humor"] >= 2 and recent_messages >= 2:
        return "joker"
    if stats["questions"] >= 2 and question_ratio >= 0.5:
        return "question_asker"
    return ""


def _build_group_personality_notes(
    member: GroupMemberRecord,
    stats: dict[str, Any],
    *,
    role: str,
    total_recent_messages: int,
) -> str:
    recent_messages = int(stats["recent_messages"])
    avg_chars = stats["char_total"] / max(recent_messages, 1)
    interacted_count = len(stats["interacted_with"])
    message_share = recent_messages / max(total_recent_messages, 1)

    notes: list[str] = []
    if role == "leader":
        notes.append("drives a lot of the chat")
    if role == "mediator":
        notes.append("often supportive")
    if role == "joker":
        notes.append("often uses jokes/laughter")
    if role == "question_asker":
        notes.append("often asks questions")
    if role == "quiet_observer":
        notes.append("low public signal so far")

    if recent_messages >= 2 and avg_chars <= 28:
        notes.append("brief replies")
    if recent_messages >= 2 and avg_chars >= 120:
        notes.append("longer messages")
    if stats["support"] >= 1:
        notes.append("often supportive")
    if stats["questions"] >= 2:
        notes.append("often asks questions")
    if stats["humor"] >= 1:
        notes.append("often uses jokes/laughter")
    if stats["mentions"] >= 2:
        notes.append("frequently tags others")
    if interacted_count >= 2:
        notes.append("interacts with several members")
    if recent_messages >= 3 and message_share >= 0.35:
        notes.append("high recent activity")
    if recent_messages <= 1 and member.message_count <= 2:
        notes.append("low public signal so far")

    deduped: list[str] = []
    for note in notes:
        if note not in deduped:
            deduped.append(note)
    return "; ".join(deduped[:2])


def _render_group_roles(
    members: list[GroupMemberRecord],
    inferred_members: dict[str, tuple[str, str]],
    *,
    current_speaker_id: str = "",
) -> list[str]:
    lines: list[str] = []
    ordered_members = sorted(members, key=lambda member: (-member.message_count, (member.display_name or member.user_id).casefold()))
    for member in ordered_members:
        role_in_group, personality_notes = inferred_members.get(member.user_id, ("", ""))
        if not role_in_group and not personality_notes:
            continue
        name = member.display_name or member.user_id
        if member.user_id == current_speaker_id:
            name = f"{name} (current speaker)"
        parts: list[str] = []
        if role_in_group:
            parts.append(f"seems like {role_in_group.replace('_', ' ')}")
        if personality_notes:
            parts.append(personality_notes)
        lines.append(f"- {name}: {'; '.join(parts)}")
    return lines


def _render_group_social_graph(
    group_messages: list[GroupMessageRecord],
    members: list[GroupMemberRecord],
) -> list[str]:
    edges = _derive_group_social_edges(group_messages, members)
    lines: list[str] = []
    for edge in edges[:6]:
        level_phrase = {
            "high": "seem closely connected",
            "medium": "interact regularly",
            "low": "occasionally engage",
        }[edge["level"]]
        line = f"- {edge['members']}: {level_phrase}"
        if edge["tone"]:
            line += f"; tone seems {edge['tone']}"
        lines.append(line)
    return lines


def _derive_group_social_edges(
    group_messages: list[GroupMessageRecord],
    members: list[GroupMemberRecord],
) -> list[dict[str, Any]]:
    display_names = {
        member.user_id: member.display_name or member.user_id
        for member in members
        if member.user_id != "assistant"
    }
    edge_stats: dict[tuple[str, str], dict[str, Any]] = {}
    human_members = [member for member in members if member.user_id != "assistant"]
    previous_human_message: GroupMessageRecord | None = None

    for message in group_messages:
        if message.user_id == "assistant":
            previous_human_message = None
            continue
        if message.user_id not in display_names:
            continue
        text = str(message.content or "").strip()
        current_tone = _message_social_tone(text)

        if previous_human_message is not None and previous_human_message.user_id != message.user_id:
            edge = edge_stats.setdefault(
                _pair_key(previous_human_message.user_id, message.user_id),
                _empty_social_edge_stats(),
            )
            edge["score"] += 1
            edge["directions"].add((previous_human_message.user_id, message.user_id))
            edge["tones"][current_tone] += 1

        for mentioned_user_id in _extract_public_mentions(text, human_members, speaker_user_id=message.user_id):
            edge = edge_stats.setdefault(_pair_key(message.user_id, mentioned_user_id), _empty_social_edge_stats())
            edge["score"] += 2
            edge["directions"].add((message.user_id, mentioned_user_id))
            edge["tones"][current_tone] += 1

        previous_human_message = message

    rendered_edges: list[dict[str, Any]] = []
    for (user_a, user_b), stats in edge_stats.items():
        score = int(stats["score"])
        directions = stats["directions"]
        if any(src == user_a and dst == user_b for src, dst in directions) and any(
            src == user_b and dst == user_a for src, dst in directions
        ):
            score += 2
        if score < 2:
            continue
        rendered_edges.append(
            {
                "members": f"{display_names[user_a]} <-> {display_names[user_b]}",
                "level": "high" if score >= 8 else "medium" if score >= 3 else "low",
                "tone": _dominant_edge_tone(stats["tones"]),
                "score": score,
            }
        )

    rendered_edges.sort(key=lambda edge: (-int(edge["score"]), edge["members"].casefold()))
    return rendered_edges


def _empty_social_edge_stats() -> dict[str, Any]:
    return {
        "score": 0,
        "directions": set(),
        "tones": defaultdict(int),
    }


def _pair_key(user_a: str, user_b: str) -> tuple[str, str]:
    return tuple(sorted((user_a, user_b)))


def _message_social_tone(text: str) -> str:
    if _count_markers(text, _GROUP_TENSION_MARKERS) > 0:
        return "tense"
    if _count_markers(text, _GROUP_SUPPORT_MARKERS) > 0:
        return "supportive"
    if _count_markers(text, _GROUP_HUMOR_MARKERS) > 0:
        return "playful"
    return ""


def _dominant_edge_tone(tone_counts: dict[str, int]) -> str:
    ranked = [(count, tone) for tone, count in tone_counts.items() if tone]
    if not ranked:
        return ""
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][1]


def _extract_public_mentions(
    text: str,
    members: list[GroupMemberRecord],
    *,
    speaker_user_id: str,
) -> set[str]:
    mentioned_user_ids: set[str] = set()
    for member in members:
        if member.user_id == speaker_user_id:
            continue
        if _message_mentions_display_name(text, member.display_name):
            mentioned_user_ids.add(member.user_id)
    return mentioned_user_ids


def _message_mentions_display_name(text: str, display_name: str) -> bool:
    normalized_name = " ".join(str(display_name or "").strip().split())
    if not normalized_name:
        return False
    lowered_text = str(text or "").casefold()
    lowered_name = normalized_name.casefold()
    if not lowered_name:
        return False
    if any(ord(char) > 127 for char in lowered_name):
        return lowered_name in lowered_text
    if len(lowered_name) < 2:
        return False
    pattern = rf"(?<![a-z0-9_])@?{re.escape(lowered_name)}(?![a-z0-9_])"
    return re.search(pattern, lowered_text) is not None


def _count_markers(text: str, markers: tuple[str, ...]) -> int:
    lowered = str(text or "").casefold()
    return sum(1 for marker in markers if marker.casefold() in lowered)


def _render_client_profile(profile: ClientProfileRecord) -> list[str]:
    lines: list[str] = []
    if profile.preferred_language:
        lines.append(f"- preferred_language: {profile.preferred_language}")
    if profile.watchlist_topics:
        lines.append(f"- watchlist_topics: {', '.join(profile.watchlist_topics)}")
    if profile.response_style:
        lines.append(f"- response_style: {profile.response_style}")
    if profile.risk_appetite:
        lines.append(f"- risk_appetite: {profile.risk_appetite}")
    if profile.investment_horizon:
        lines.append(f"- investment_horizon: {profile.investment_horizon}")
    if profile.institution_type:
        lines.append(f"- institution_type: {profile.institution_type}")
    if profile.risk_preference:
        lines.append(f"- risk_preference: {profile.risk_preference}")
    if profile.asset_focus:
        lines.append(f"- asset_focus: {', '.join(profile.asset_focus)}")
    if profile.market_focus:
        lines.append(f"- market_focus: {', '.join(profile.market_focus)}")
    if profile.expertise_level:
        lines.append(f"- expertise_level: {profile.expertise_level}")
    if profile.activity:
        lines.append(f"- activity: {profile.activity}")
    if profile.current_mood:
        lines.append(f"- current_mood: {profile.current_mood}")
    if profile.emotional_trend:
        lines.append(f"- emotional_trend: {profile.emotional_trend}")
    if profile.stress_level:
        lines.append(f"- stress_level: {profile.stress_level}")
    effective_confidence = profile.confidence or ("low" if profile.total_interactions < 3 else "")
    if effective_confidence:
        lines.append(f"- confidence: {effective_confidence}")
    if profile.notes:
        lines.append(f"- notes: {trim_text(profile.notes, max_chars=160)}")
    if profile.personal_facts:
        lines.append(f"- personal_facts: {'; '.join(profile.personal_facts)}")
    if profile.total_interactions:
        lines.append(f"- total_interactions: {profile.total_interactions}")
    if profile.last_active_at:
        try:
            last = datetime.fromisoformat(profile.last_active_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days_away = (datetime.now(timezone.utc) - last).days
            if days_away >= 1:
                lines.append(f"- days_since_last_active: {days_away}")
        except (ValueError, TypeError):
            pass
    return lines


def _render_companion_profile(profile: ClientProfileRecord) -> list[str]:
    lines: list[str] = []
    if profile.preferred_language:
        lines.append(f"- preferred_language: {profile.preferred_language}")
    if profile.response_style:
        lines.append(f"- response_style: {profile.response_style}")
    if profile.current_mood:
        lines.append(f"- current_mood: {profile.current_mood}")
    if profile.emotional_trend:
        lines.append(f"- emotional_trend: {profile.emotional_trend}")
    if profile.stress_level:
        lines.append(f"- stress_level: {profile.stress_level}")
    effective_confidence = profile.confidence or ("low" if profile.total_interactions < 3 else "")
    if effective_confidence:
        lines.append(f"- confidence: {effective_confidence}")
    if profile.notes:
        lines.append(f"- notes: {trim_text(profile.notes, max_chars=160)}")
    if profile.personal_facts:
        lines.append(f"- personal_facts: {'; '.join(profile.personal_facts)}")
    if profile.total_interactions:
        lines.append(f"- total_interactions: {profile.total_interactions}")
    if profile.last_active_at:
        try:
            last = datetime.fromisoformat(profile.last_active_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days_away = (datetime.now(timezone.utc) - last).days
            if days_away >= 1:
                lines.append(f"- days_since_last_active: {days_away}")
        except (ValueError, TypeError):
            pass
    return lines


def _companion_only_update(update: ClientProfileUpdate) -> ClientProfileUpdate:
    return ClientProfileUpdate(
        preferred_language=update.preferred_language,
        response_style=update.response_style,
        current_mood=update.current_mood,
        emotional_trend=update.emotional_trend,
        stress_level=update.stress_level,
        confidence=update.confidence,
        notes=update.notes,
        personal_facts=update.personal_facts,
    )


def _format_age(created_at: str) -> str:
    """Convert an ISO timestamp to a human-readable relative age (e.g. '2h ago')."""
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "just now"
        if total_seconds < 3600:
            minutes = max(total_seconds // 60, 1)
            return f"{minutes}m ago"
        if total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours}h ago"
        days = delta.days
        if days == 1:
            return "yesterday"
        return f"{days}d ago"
    except (ValueError, TypeError):
        return ""


def _render_delivery_history(deliveries: list[DeliveryQueueRecord], *, limits: RenderBudget) -> list[str]:
    lines: list[str] = []
    for delivery in deliveries[: limits.max_delivery_items]:
        age = _format_age(delivery.created_at)
        age_prefix = f"[{age}] " if age else ""
        headline = f"{age_prefix}{delivery.source_type} [{delivery.status}]"
        body = trim_text(delivery.content_rendered, max_chars=limits.max_item_chars)
        lines.append(f"- {headline}: {body}")
    return lines


def _render_surprise_patterns(events: list[Any], *, limits: RenderBudget) -> list[str]:
    by_category: dict[str, list[float]] = defaultdict(list)
    for event in events:
        surprise = event["surprise"] if isinstance(event, dict) else event.surprise
        category = event["category"] if isinstance(event, dict) else event.category
        if surprise is None or not category:
            continue
        by_category[category].append(float(surprise))

    lines: list[str] = []
    for category, surprises in sorted(by_category.items()):
        avg = sum(surprises) / len(surprises)
        beats = sum(1 for value in surprises if value > 0)
        misses = sum(1 for value in surprises if value < 0)
        lines.append(
            trim_text(
                f"- {category}: {len(surprises)} releases | beats {beats} | misses {misses} | avg surprise {avg:.3f}",
                max_chars=limits.max_item_chars,
            )
        )
    return lines[:4]
