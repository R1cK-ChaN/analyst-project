from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from analyst.storage import (
    ClientProfileRecord,
    DeliveryQueueRecord,
    SQLiteEngineStore,
    StoredEventRecord,
)

from .profile import ClientProfileUpdate, extract_client_profile_update, merge_client_profile_updates
from .render import RenderBudget, render_context_sections, trim_text


def build_research_context(
    store: SQLiteEngineStore,
    *,
    budget: RenderBudget | None = None,
) -> str:
    limits = budget or RenderBudget(total_chars=4500)
    snapshots = store.list_recent_regime_snapshots(limit=3)
    notes = store.list_recent_generated_notes(limit=3)
    observations = store.list_recent_analytical_observations(limit=4)
    recent_events = store.list_recent_events(limit=18, days=14, released_only=True)

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


def record_sales_interaction(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    assistant_profile_update: ClientProfileUpdate | None = None,
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


def _render_delivery_history(deliveries: list[DeliveryQueueRecord], *, limits: RenderBudget) -> list[str]:
    lines: list[str] = []
    for delivery in deliveries[: limits.max_delivery_items]:
        headline = f"{delivery.source_type} [{delivery.status}]"
        body = trim_text(delivery.content_rendered, max_chars=limits.max_item_chars)
        lines.append(f"- {headline}: {body}")
    return lines


def _render_surprise_patterns(events: list[StoredEventRecord], *, limits: RenderBudget) -> list[str]:
    by_category: dict[str, list[float]] = defaultdict(list)
    for event in events:
        surprise = event.surprise
        category = event.category
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
