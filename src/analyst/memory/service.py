from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any

from analyst.macro_data import MacroDataClient
from analyst.storage import (
    ClientProfileRecord,
    CompanionRelationshipStateRecord,
    ConversationMessageRecord,
    DeliveryQueueRecord,
    GroupMemberRecord,
    GroupMessageRecord,
    NicknameEntry,
    SQLiteEngineStore,
)

from .profile import ClientProfileUpdate, RelationshipSignalUpdate, extract_client_profile_update, merge_client_profile_updates
from .relationship import compute_relationship_update, extract_nicknames_from_facts
from .render import RenderBudget, render_context_sections, trim_text
from .topic_state import ConversationTopicMessage, build_topic_state_lines

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


def build_user_context(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    query: str,
    current_user_text: str = "",
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
    # Deliveries are client-scoped rather than thread-scoped so user chat can avoid
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
    topic_lines = build_topic_state_lines(
        _conversation_topic_messages(
            recent_messages,
            pending_user_text=current_user_text or query,
        )
    )

    sections = [
        (
            "client_profile",
            _render_client_profile(profile),
        ),
        (
            "topic_state",
            topic_lines,
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
    current_user_text: str = "",
    persona_mode: str = "user",
    budget: RenderBudget | None = None,
) -> str:
    if str(persona_mode).strip().lower() != "companion":
        return build_user_context(
            store=store,
            client_id=client_id,
            channel_id=channel_id,
            thread_id=thread_id,
            query=query,
            current_user_text=current_user_text,
            budget=budget,
        )

    limits = budget or RenderBudget()
    profile = store.get_client_profile(client_id)
    relationship = store.get_companion_relationship_state(client_id=client_id)
    recent_messages = store.list_conversation_messages(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        limit=limits.max_recent_messages,
    )
    topic_lines = build_topic_state_lines(
        _conversation_topic_messages(
            recent_messages,
            pending_user_text=current_user_text or query,
        )
    )
    sections = [
        (
            "client_profile",
            _render_companion_profile(profile, relationship=relationship),
        ),
        (
            "topic_state",
            topic_lines,
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


def record_user_interaction(
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
    store.record_user_interaction(
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
    persona_mode: str = "user",
) -> None:
    if str(persona_mode).strip().lower() != "companion":
        record_user_interaction(
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
    store.record_user_interaction(
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

    # Update companion relationship state
    now = datetime.now(timezone.utc)
    current_rel = store.get_companion_relationship_state(client_id=client_id)
    active_topic = _detect_active_topic_category(user_text)
    interaction_mode = _detect_interaction_mode(user_text)
    signal = RelationshipSignalUpdate(
        current_mood=update.current_mood,
        is_personal_sharing=_detect_personal_sharing(user_text),
        is_late_night=_is_late_night_utc8(now),
        active_topic_category=active_topic,
        interaction_mode=interaction_mode,
        user_text=user_text,
    )
    rel_updates = compute_relationship_update(current_rel, signal=signal, now=now)
    store.update_companion_relationship_state(client_id=client_id, **rel_updates)


def build_group_chat_context(
    *,
    store: SQLiteEngineStore,
    group_id: str,
    thread_id: str,
    speaker_user_id: str,
    persona_mode: str = "user",
    budget: RenderBudget | None = None,
) -> str:
    """Build group chat context: messages + speaker memory + participants + inferred roles + social graph."""
    limits = budget or RenderBudget()

    # Layer 1: Group conversation (working memory)
    group_messages = store.list_group_messages(group_id, thread_id, limit=20)
    topic_lines = build_topic_state_lines(_group_topic_messages(group_messages))
    group_lines = [
        f"- {msg.display_name}: {trim_text(msg.content, max_chars=limits.max_item_chars)}"
        for msg in group_messages
    ]

    # Layer 2: Speaker's user memory (long-term memory, shared across contexts)
    speaker_profile = store.get_client_profile(speaker_user_id)
    is_companion = str(persona_mode).strip().lower() == "companion"
    if is_companion:
        speaker_rel = store.get_companion_relationship_state(client_id=speaker_user_id)
        speaker_lines = _render_companion_profile(speaker_profile, relationship=speaker_rel)
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
        ("topic_state", topic_lines),
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


def _conversation_topic_messages(
    recent_messages: list[ConversationMessageRecord],
    *,
    pending_user_text: str = "",
) -> list[ConversationTopicMessage]:
    messages = [
        ConversationTopicMessage(
            speaker_key=message.role,
            speaker_label=message.role,
            content=message.content,
            created_at=message.created_at,
            is_assistant=message.role == "assistant",
        )
        for message in recent_messages
    ]
    if str(pending_user_text or "").strip():
        messages.append(
            ConversationTopicMessage(
                speaker_key="user",
                speaker_label="user",
                content=pending_user_text,
                created_at=datetime.now(timezone.utc).isoformat(),
                is_assistant=False,
                is_current_turn=True,
            )
        )
    return messages


def _group_topic_messages(group_messages: list[GroupMessageRecord]) -> list[ConversationTopicMessage]:
    return [
        ConversationTopicMessage(
            speaker_key=message.user_id,
            speaker_label=message.display_name or message.user_id,
            content=message.content,
            created_at=message.created_at,
            is_assistant=message.user_id == "assistant",
        )
        for message in group_messages
    ]


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


def _render_companion_profile(
    profile: ClientProfileRecord,
    relationship: CompanionRelationshipStateRecord | None = None,
) -> list[str]:
    lines: list[str] = []

    # -- Relationship stage → behavioral instruction --
    rel_valid = (
        relationship is not None
        and isinstance(relationship, CompanionRelationshipStateRecord)
    )
    if rel_valid and relationship.relationship_stage != "stranger":
        stage_text = _STAGE_INSTRUCTIONS.get(
            relationship.relationship_stage,
            _STAGE_INSTRUCTIONS["stranger"],
        )
        dominant = _dominant_tendency(relationship)
        if dominant and relationship.relationship_stage in ("familiar", "close"):
            stage_text += _TENDENCY_NUANCE.get(dominant, "")
        lines.append(f"- 关系阶段: {relationship.relationship_stage} — {stage_text}")
    elif rel_valid:
        lines.append(f"- 关系阶段: stranger — {_STAGE_INSTRUCTIONS['stranger']}")

    # -- Soft regression note --
    if rel_valid and _is_soft_regression(relationship):
        prev = relationship.previous_stage
        lines.append(
            f"- 关系变化: 你们之前是{prev}，最近疏远了。"
            "语气稍微收一点但不要完全变陌生人，可以自然提起好久不见。"
        )

    # -- Tendency spike hint (ambiguous window) --
    if rel_valid:
        damping_json = getattr(relationship, "tendency_damping_json", "{}") or "{}"
        try:
            import json as _json
            damping_state = _json.loads(damping_json) if isinstance(damping_json, str) else {}
            spike_consecutive = int(damping_state.get("spike_consecutive", 0))
            if 1 <= spike_consecutive < 3:
                lines.append(
                    "- [用户这条消息的风格和之前不太一样，可能在开玩笑或试探。"
                    "不要过度反应，用轻松的方式回应，观察对方是否持续这个方向。]"
                )
        except (ValueError, TypeError):
            pass

    # -- Interaction stats --
    stats_parts: list[str] = []
    turns = relationship.total_turns if rel_valid else profile.total_interactions
    if turns:
        stats_parts.append(f"总对话: {turns}轮")
    if rel_valid and relationship.streak_days > 1:
        stats_parts.append(f"连续聊天: {relationship.streak_days}天")
    if profile.last_active_at:
        try:
            last = datetime.fromisoformat(profile.last_active_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days_away = (datetime.now(timezone.utc) - last).days
            if days_away >= 1:
                stats_parts.append(f"{days_away}天没聊了")
        except (ValueError, TypeError):
            pass
    if stats_parts:
        lines.append(f"- 互动: {' | '.join(stats_parts)}")

    # -- Nicknames --
    nickname_lines = _render_nickname_context(
        relationship.nicknames if rel_valid else [],
        profile.personal_facts,
    )
    lines.extend(nickname_lines)

    # -- Emotion & stress → response strategy --
    mood = profile.current_mood
    emotional_trend = _get_emotional_trend(profile, relationship if rel_valid else None)
    stress = profile.stress_level

    if stress in ("high", "critical") and emotional_trend == "declining":
        lines.append(f"- 情绪状态: {mood or stress}, 趋势declining — 压力很大而且在恶化，优先共情和陪伴")
    elif stress in ("high", "critical"):
        lines.append(f"- 情绪状态: {mood or stress} — 压力较大，优先共情，不要讲道理")
    elif emotional_trend == "declining":
        lines.append(f"- 情绪状态: {mood or '–'}, 趋势declining — 情绪在变差，比平时更温柔一些")
    elif emotional_trend == "improving":
        lines.append(f"- 情绪状态: {mood or '–'}, 趋势improving — 情绪在好转，可以适度轻松")
    elif mood:
        lines.append(f"- current_mood: {mood}")

    # -- Personal facts as memories --
    facts = [f for f in profile.personal_facts if not _is_nickname_fact(f)]
    if facts:
        lines.append(f"- 你记得: {'; '.join(facts[-6:])}")

    # -- Language / style (compact) --
    meta: list[str] = []
    if profile.preferred_language:
        meta.append(f"lang:{profile.preferred_language}")
    if profile.response_style:
        meta.append(f"style:{profile.response_style}")
    if meta:
        lines.append(f"- {', '.join(meta)}")

    return lines


_STAGE_INSTRUCTIONS: dict[str, str] = {
    "stranger": "初识，保持礼貌和温暖，不要太过热情",
    "acquaintance": "认识不久，友好自然，逐渐了解对方",
    "familiar": "你们已经很熟了，可以撒娇、开小玩笑、偶尔任性一点",
    "close": "非常亲密，可以耍赖、吃醋、分享脆弱的一面",
}

_TENDENCY_NUANCE: dict[str, str] = {
    "romantic": "，跟随对方节奏",
    "confidant": "，多倾听少建议",
    "mentor": "，可以适度引导",
    "friend": "",
}

_STAGE_ORDER = {"stranger": 0, "acquaintance": 1, "familiar": 2, "close": 3}


def _is_soft_regression(rel: CompanionRelationshipStateRecord) -> bool:
    """Check if the relationship recently regressed (stage dropped from a higher level)."""
    if not rel.previous_stage:
        return False
    prev_rank = _STAGE_ORDER.get(rel.previous_stage, 0)
    curr_rank = _STAGE_ORDER.get(rel.relationship_stage, 0)
    return prev_rank > curr_rank


def _dominant_tendency(rel: CompanionRelationshipStateRecord) -> str:
    """Return the dominant tendency name, or '' if all equal."""
    tendencies = {
        "friend": rel.tendency_friend,
        "romantic": rel.tendency_romantic,
        "confidant": rel.tendency_confidant,
        "mentor": rel.tendency_mentor,
    }
    max_val = max(tendencies.values())
    if all(v == max_val for v in tendencies.values()):
        return ""
    return max(tendencies, key=tendencies.get)  # type: ignore[arg-type]


def _get_emotional_trend(
    profile: ClientProfileRecord,
    relationship: CompanionRelationshipStateRecord | None,
) -> str:
    """Get emotional trend from relationship state (computed) or profile (LLM-set)."""
    if relationship and relationship.mood_history and len(relationship.mood_history) >= 3:
        from .relationship import _compute_emotional_trend
        return _compute_emotional_trend(
            list(relationship.mood_history), now=datetime.now(timezone.utc)
        )
    return profile.emotional_trend or ""


def _render_nickname_context(
    stored_nicknames: list[dict],
    personal_facts: list[str],
) -> list[str]:
    """Render nickname lines for the companion profile context."""
    # Merge stored nicknames with those extracted from personal_facts
    from .relationship import extract_nicknames_from_facts
    fact_nicknames = extract_nicknames_from_facts(personal_facts)

    # Build lookup from stored nicknames
    nick_map: dict[tuple[str, str], dict] = {}
    for n in stored_nicknames:
        key = (n.get("name", ""), n.get("target", ""))
        nick_map[key] = n
    # Merge fact-extracted nicknames (lower priority)
    for fn in fact_nicknames:
        key = (fn.name, fn.target)
        if key not in nick_map:
            nick_map[key] = {
                "name": fn.name,
                "target": fn.target,
                "created_by": fn.created_by,
                "sentiment": fn.sentiment,
                "frequency": fn.frequency,
                "accepted": fn.accepted,
            }

    if not nick_map:
        return []

    lines: list[str] = []
    ai_names = [n for n in nick_map.values() if n.get("target") == "ai" and n.get("accepted", True)]
    user_names = [n for n in nick_map.values() if n.get("target") == "user" and n.get("accepted", True)]
    parts: list[str] = []
    if ai_names:
        preferred = max(ai_names, key=lambda n: n.get("frequency", 0))
        names_str = ", ".join(f'"{n["name"]}"' for n in ai_names)
        if len(ai_names) > 1:
            parts.append(f'他叫你: {names_str} (最常用: "{preferred["name"]}")')
        else:
            parts.append(f'他叫你"{preferred["name"]}"')
    if user_names:
        names_str = ", ".join(f'"{n["name"]}"' for n in user_names)
        parts.append(f"你叫他: {names_str}")
    if parts:
        lines.append(f"- 称呼: {'; '.join(parts)}")
    return lines


_NICKNAME_FACT_PATTERN = re.compile(
    r"(?:用户|他|她|对方)叫我|我叫(?:他|她|用户)"
)


def _is_nickname_fact(fact: str) -> bool:
    """Check if a personal_fact is a nickname entry (to avoid duplication in memories)."""
    return bool(_NICKNAME_FACT_PATTERN.search(fact))


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


_PERSONAL_SHARING_PATTERN = re.compile(
    r"(?:"
    r"(?:我|我们|老婆|老公|爸|妈|女朋友|男朋友|家里|家人)"
    r"|(?:分手|吵架|离婚|失恋|去世|生病|住院|焦虑|抑郁|失眠|不开心|难过|崩溃|想哭)"
    r"|(?:feel|feeling|lonely|breakup|divorce|depressed|anxious|miss|family|relationship)"
    r")",
    re.IGNORECASE,
)


def _detect_personal_sharing(text: str) -> bool:
    """Detect if user text contains personal/emotional disclosure signals."""
    return bool(_PERSONAL_SHARING_PATTERN.search(text))


def _detect_active_topic_category(text: str) -> str | None:
    """Quick topic category detection for tendency nudging.

    Reuses the same category keywords from topic_state but as a lightweight
    single-pass check (no scoring/decay needed here).
    """
    lowered = text.lower()
    # Check categories in priority order for tendency relevance
    _TOPIC_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
        ("mood / emotional", ("tired", "exhausted", "burned out", "stress", "anxious", "panic", "sad", "upset", "累", "困", "焦虑", "压力", "崩溃", "难过", "伤心", "失恋")),
        ("relationships / people", ("friend", "family", "boyfriend", "girlfriend", "husband", "wife", "朋友", "家人", "男朋友", "女朋友", "老公", "老婆")),
        ("joke / banter", ("lol", "haha", "哈哈", "233", "😂", "🤣")),
        ("planning / scheduling", ("meet", "meeting", "plan", "schedule", "tomorrow", "见面", "安排", "计划", "明天")),
        ("work / office", ("work", "office", "boss", "colleague", "工作", "公司", "老板", "同事")),
        ("meal / food", ("eat", "lunch", "dinner", "coffee", "吃", "午饭", "晚饭", "咖啡")),
        ("photos / media", ("photo", "selfie", "照片", "自拍")),
        ("travel / outing", ("travel", "walk", "旅行", "散步")),
    ]
    for category, keywords in _TOPIC_SIGNALS:
        if any(kw in lowered for kw in keywords):
            return category
    return None


_INTERACTION_MODE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("flirting", re.compile(
        r"(?:你今天穿了什么|想你了|抱抱|亲亲|mua|你在想我吗|miss you|想见你|好想你|"
        r"你的声音|你好可爱|你好温柔|心动|喜欢你|love you)",
        re.IGNORECASE,
    )),
    ("curious_about_ai", re.compile(
        r"(?:你呢|你喜欢什么|你平时|你觉得你|你有没有|about you|what do you like|"
        r"你怎么想|你的感受|你开心吗|你累不累|你今天做了什么)",
        re.IGNORECASE,
    )),
    ("seeking_advice", re.compile(
        r"(?:你觉得我该|帮我分析|你怎么看|你的建议|should i|what do you think|"
        r"帮我想想|给我点建议|该不该|how should i|你说我)",
        re.IGNORECASE,
    )),
    ("venting", re.compile(
        r"(?:算了|不想说了|随便吧|无所谓|烦死了|受不了了|我真的|气死我了|"
        r"i can't|i just can't|whatever|ugh|不管了|懒得)",
        re.IGNORECASE,
    )),
]


def _detect_interaction_mode(text: str) -> str | None:
    """Detect HOW the user is interacting, not just what topic."""
    for mode, pattern in _INTERACTION_MODE_PATTERNS:
        if pattern.search(text):
            return mode
    return None


def _is_late_night_utc8(utc_now_dt: datetime) -> bool:
    """Check if current time is late night in UTC+8 (23:00-05:00)."""
    utc8_hour = (utc_now_dt.hour + 8) % 24
    return utc8_hour >= 23 or utc8_hour <= 5


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
