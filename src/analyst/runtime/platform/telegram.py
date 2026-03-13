from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from analyst.runtime.conversation_service import persist_companion_turn_for_input
from analyst.runtime.environment_adapter import ConversationInput, build_telegram_conversation_input
from analyst.tools._request_context import RequestImageInput

RenderImageInstruction = Callable[[str], str]
FirstReplyDelay = Callable[..., float]
NeedsEmotionalFollowUp = Callable[[str, Any], bool]
RefreshCheckinSchedule = Callable[..., None]


@dataclass(frozen=True)
class TelegramTurnPreparation:
    llm_text: str
    first_reply_delay_seconds: float
    conversation: ConversationInput


def prepare_telegram_turn(
    *,
    user_id: str,
    channel_id: str,
    thread_id: str,
    text: str,
    reply_context: str,
    history: list[dict[str, str]],
    history_user_text: str,
    group_context: str,
    group_id: str,
    attached_image: RequestImageInput | None,
    companion_local_context: str,
    render_image_instruction: Callable[..., str],
    first_reply_delay: FirstReplyDelay,
) -> TelegramTurnPreparation:
    base_llm_text = text or "The user sent an image without caption."
    if reply_context:
        llm_text = f'回复消息：\n"{reply_context}"\n\n用户说：\n{base_llm_text}'
    else:
        llm_text = base_llm_text
    first_reply_delay_seconds = first_reply_delay(
        text,
        has_image=attached_image is not None,
    )
    user_content = (
        [
            {"type": "text", "text": render_image_instruction(llm_text, image=attached_image)},
            {"type": "image_url", "image_url": {"url": attached_image.data_uri}},
        ]
        if attached_image is not None
        else llm_text
    )
    conversation = build_telegram_conversation_input(
        user_id=user_id,
        channel_id=channel_id,
        thread_id=thread_id,
        message=llm_text,
        history=history,
        current_user_text=history_user_text,
        group_context=group_context,
        group_id=group_id,
        user_content=user_content,
        companion_local_context=companion_local_context,
        attached_image=attached_image,
    )
    return TelegramTurnPreparation(
        llm_text=llm_text,
        first_reply_delay_seconds=first_reply_delay_seconds,
        conversation=conversation,
    )


def refresh_companion_checkin_schedule(
    *,
    store: Any,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    profile: Any,
    now: datetime,
    needs_emotional_follow_up: NeedsEmotionalFollowUp,
) -> None:
    state = store.get_companion_checkin_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
    )
    if not state.enabled:
        return
    if needs_emotional_follow_up(user_text, profile):
        due_at = now + timedelta(hours=18)
        store.schedule_companion_checkin(
            client_id=client_id,
            channel=channel_id,
            thread_id=thread_id,
            kind="follow_up",
            due_at=due_at.isoformat(),
        )


def should_send_inactivity_ping(
    *,
    now: datetime,
    checkin_state: Any,
    last_user_message_at: str,
    parse_iso_datetime: Callable[[str], datetime | None],
    is_same_local_day: Callable[[str, datetime], bool],
) -> bool:
    if not last_user_message_at:
        return False
    if checkin_state.pending_kind == "follow_up":
        return False
    if checkin_state.cooldown_until:
        cooldown_until = parse_iso_datetime(checkin_state.cooldown_until)
        if cooldown_until is not None and cooldown_until > now:
            return False
    if checkin_state.last_sent_at and is_same_local_day(checkin_state.last_sent_at, now):
        return False
    last_user_dt = parse_iso_datetime(last_user_message_at)
    if last_user_dt is None:
        return False
    return now - last_user_dt >= timedelta(days=5)


def should_send_routine_ping(
    *,
    now: datetime,
    lifestyle_state: Any,
    checkin_state: Any,
    last_user_message_at: str,
    kind: str,
    parse_iso_datetime: Callable[[str], datetime | None],
    is_same_local_day: Callable[[str, datetime], bool],
    lifestyle_ping_sent_at: Callable[[Any, str], str],
) -> bool:
    if not kind:
        return False
    if checkin_state.pending_kind:
        return False
    if checkin_state.cooldown_until:
        cooldown_until = parse_iso_datetime(checkin_state.cooldown_until)
        if cooldown_until is not None and cooldown_until > now:
            return False
    if last_user_message_at and is_same_local_day(last_user_message_at, now):
        return False
    if checkin_state.last_sent_at and is_same_local_day(checkin_state.last_sent_at, now):
        return False
    routine_sent_at = lifestyle_ping_sent_at(lifestyle_state, kind)
    if routine_sent_at and is_same_local_day(routine_sent_at, now):
        return False
    return True


def persist_telegram_companion_turn(
    *,
    store: Any,
    conversation: ConversationInput,
    reply: Any,
    assistant_text: str,
    history_user_text: str,
    now: datetime,
    routine_state: str,
    in_group: bool,
    refresh_schedule: RefreshCheckinSchedule,
    apply_companion_schedule_update: Callable[..., Any],
    apply_companion_reminder_update: Callable[..., Any],
    record_chat_interaction: Callable[..., Any],
    needs_emotional_follow_up: NeedsEmotionalFollowUp,
) -> Any:
    persist_companion_turn_for_input(
        conversation=conversation,
        store=store,
        assistant_text=assistant_text,
        reply=reply,
        now=now,
        routine_state=routine_state,
        apply_reminders=not in_group,
        schedule_updater=apply_companion_schedule_update,
        reminder_updater=apply_companion_reminder_update,
        interaction_recorder=record_chat_interaction,
    )
    updated_profile = store.get_client_profile(conversation.user_id)
    if not in_group:
        refresh_schedule(
            store=store,
            client_id=conversation.user_id,
            channel_id=conversation.channel_id,
            thread_id=conversation.thread_id,
            user_text=history_user_text,
            profile=updated_profile,
            now=now,
            needs_emotional_follow_up=needs_emotional_follow_up,
        )
    return updated_profile
