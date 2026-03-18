from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from analyst.delivery.companion_reminders import apply_companion_reminder_update
from analyst.delivery.companion_schedule import apply_companion_schedule_update
from analyst.engine import AgentExecutor
from analyst.engine.live_types import AgentTool, MessageContent
from analyst.memory import build_chat_context, build_group_chat_context, record_chat_interaction
from analyst.storage import SQLiteEngineStore
from analyst.tools._request_context import RequestImageInput, bind_request_image

from .chat import ChatReply, generate_chat_reply, generate_proactive_companion_reply
from .environment_adapter import ConversationInput, ProactiveConversationInput


def _append_image_hint(context: str, hint: str) -> str:
    if context:
        return f"{context}\n{hint}"
    return hint


MemoryContextBuilder = Callable[..., str]
GroupMemoryContextBuilder = Callable[..., str]
ReplyGenerator = Callable[..., ChatReply]
ProactiveReplyGenerator = Callable[..., ChatReply]
ScheduleUpdater = Callable[..., Any]
ReminderUpdater = Callable[..., Any]
InteractionRecorder = Callable[..., Any]


def build_companion_memory_context(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    query: str,
    current_user_text: str,
    group_id: str = "",
    persona_mode: str = "companion",
    memory_context_builder: MemoryContextBuilder = build_chat_context,
    group_memory_context_builder: GroupMemoryContextBuilder = build_group_chat_context,
) -> str:
    if group_id:
        return group_memory_context_builder(
            store=store,
            group_id=group_id,
            thread_id=thread_id,
            speaker_user_id=client_id,
            persona_mode=persona_mode,
        )
    return memory_context_builder(
        store=store,
        client_id=client_id,
        channel_id=channel_id,
        thread_id=thread_id,
        query=query,
        current_user_text=current_user_text,
        persona_mode=persona_mode,
    )


def run_companion_turn(
    *,
    user_text: str,
    history: list[dict[str, str]] | None,
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool],
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    query: str,
    current_user_text: str,
    group_context: str = "",
    group_id: str = "",
    user_content: MessageContent | None = None,
    companion_local_context: str = "",
    attached_image: RequestImageInput | None = None,
    persona_mode: str = "companion",
    memory_context_builder: MemoryContextBuilder = build_chat_context,
    group_memory_context_builder: GroupMemoryContextBuilder = build_group_chat_context,
    reply_generator: ReplyGenerator = generate_chat_reply,
) -> ChatReply:
    return run_companion_turn_for_input(
        conversation=ConversationInput(
            user_id=client_id,
            channel="",
            channel_id=channel_id,
            thread_id=thread_id,
            message=user_text,
            current_user_text=current_user_text,
            history=list(history or []),
            group_context=group_context,
            group_id=group_id,
            user_content=user_content,
            companion_local_context=companion_local_context,
            attached_image=attached_image,
            persona_mode=persona_mode,
        ),
        store=store,
        agent_loop=agent_loop,
        tools=tools,
        memory_context_builder=memory_context_builder,
        group_memory_context_builder=group_memory_context_builder,
        reply_generator=reply_generator,
    )


def run_companion_turn_for_input(
    *,
    conversation: ConversationInput,
    store: SQLiteEngineStore,
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool],
    memory_context_builder: MemoryContextBuilder = build_chat_context,
    group_memory_context_builder: GroupMemoryContextBuilder = build_group_chat_context,
    reply_generator: ReplyGenerator = generate_chat_reply,
) -> ChatReply:
    memory_context = build_companion_memory_context(
        store=store,
        client_id=conversation.user_id,
        channel_id=conversation.channel_id,
        thread_id=conversation.thread_id,
        query=conversation.message,
        current_user_text=conversation.current_user_text or conversation.message,
        group_id=conversation.group_id,
        persona_mode=conversation.persona_mode,
        memory_context_builder=memory_context_builder,
        group_memory_context_builder=group_memory_context_builder,
    )
    from analyst.delivery.injection_scanner import scan_for_injection
    injection_detected = scan_for_injection(conversation.message)
    profile = store.get_client_profile(conversation.user_id)

    # --- Image decision layer ---
    from analyst.delivery.image_decision import should_generate_image
    import re as _re

    filtered_tools = list(tools)
    companion_local_context = conversation.companion_local_context
    try:
        _stage_match = _re.search(r"relationship_stage:\s*(\w+)", memory_context)
        _stage = _stage_match.group(1) if _stage_match else "acquaintance"
        _topic_match = _re.search(r"active_topic:\s*(.+)", memory_context)
        _active_topic = _topic_match.group(1).strip() if _topic_match else ""
        _stress = profile.stress_level or ""
        _images_today = store.count_images_sent_today(
            client_id=conversation.user_id,
            timezone_name=profile.timezone_name,
        )
        _turns_gap = store.get_turns_since_last_image(
            client_id=conversation.user_id,
            channel=conversation.channel_id,
            thread_id=conversation.thread_id,
        )
        from datetime import datetime, timezone as _tz
        _now_hour = datetime.now(_tz.utc).hour  # approximate; ideally user tz
        _image_decision = should_generate_image(
            reply_text="",
            relationship_stage=_stage,
            active_topic=_active_topic,
            stress_level=_stress,
            images_sent_today=_images_today,
            turns_since_last_image=_turns_gap,
            current_hour=_now_hour,
            is_proactive=False,
            user_text=conversation.message,
        )
        if not _image_decision.allowed:
            filtered_tools = [t for t in tools if t.name not in ("generate_image", "generate_live_photo")]
            companion_local_context = _append_image_hint(
                companion_local_context,
                "[这轮不要发照片。]",
            )
        elif _image_decision.recommended and _image_decision.mode:
            _hint = f"[这轮可以拍一张{_image_decision.mode}照片"
            if _image_decision.scene_hint:
                _hint += f"，场景：{_image_decision.scene_hint}"
            _hint += "。自然就好。]"
            companion_local_context = _append_image_hint(companion_local_context, _hint)
    except Exception:
        pass  # If decision layer fails, fall through with original tools

    with bind_request_image(conversation.attached_image):
        return reply_generator(
            conversation.message,
            history=conversation.history,
            agent_loop=agent_loop,
            tools=filtered_tools,
            memory_context=memory_context,
            preferred_language=profile.preferred_language,
            group_context=conversation.group_context,
            user_content=conversation.user_content,
            companion_local_context=companion_local_context,
            persona_mode=conversation.persona_mode,
            injection_detected=injection_detected,
            group_autonomous=conversation.group_autonomous,
        )


def persist_companion_turn(
    *,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    reply: ChatReply,
    routine_state: str = "",
    now: datetime | None = None,
    apply_reminders: bool = True,
    persona_mode: str = "companion",
    schedule_updater: ScheduleUpdater = apply_companion_schedule_update,
    reminder_updater: ReminderUpdater = apply_companion_reminder_update,
    interaction_recorder: InteractionRecorder = record_chat_interaction,
) -> None:
    persist_companion_turn_for_input(
        conversation=ConversationInput(
            user_id=client_id,
            channel="",
            channel_id=channel_id,
            thread_id=thread_id,
            message=user_text,
            current_user_text=user_text,
            persona_mode=persona_mode,
        ),
        store=store,
        assistant_text=assistant_text,
        reply=reply,
        routine_state=routine_state,
        now=now,
        apply_reminders=apply_reminders,
        persona_mode=persona_mode,
        schedule_updater=schedule_updater,
        reminder_updater=reminder_updater,
        interaction_recorder=interaction_recorder,
    )


def persist_companion_turn_for_input(
    *,
    conversation: ConversationInput,
    store: SQLiteEngineStore,
    assistant_text: str,
    reply: ChatReply,
    routine_state: str = "",
    now: datetime | None = None,
    apply_reminders: bool = True,
    persona_mode: str = "companion",
    schedule_updater: ScheduleUpdater = apply_companion_schedule_update,
    reminder_updater: ReminderUpdater = apply_companion_reminder_update,
    interaction_recorder: InteractionRecorder = record_chat_interaction,
) -> None:
    schedule_kwargs: dict[str, Any] = {
        "client_id": conversation.user_id,
        "user_text": conversation.current_user_text or conversation.message,
    }
    if now is not None:
        schedule_kwargs["now"] = now
    if routine_state:
        schedule_kwargs["routine_state"] = routine_state
    schedule_updater(store, reply.schedule_update, **schedule_kwargs)

    if apply_reminders:
        profile = store.get_client_profile(conversation.user_id)
        reminder_kwargs: dict[str, Any] = {
            "store": store,
            "update": reply.reminder_update,
            "client_id": conversation.user_id,
            "channel_id": conversation.channel_id,
            "thread_id": conversation.thread_id,
            "preferred_language": profile.preferred_language,
        }
        if now is not None:
            reminder_kwargs["now"] = now
        reminder_updater(**reminder_kwargs)

    interaction_recorder(
        store=store,
        client_id=conversation.user_id,
        channel_id=conversation.channel_id,
        thread_id=conversation.thread_id,
        user_text=conversation.current_user_text or conversation.message,
        assistant_text=assistant_text,
        assistant_profile_update=reply.profile_update,
        tool_audit=reply.tool_audit,
        persona_mode=persona_mode,
    )


def run_proactive_companion_turn(
    *,
    kind: str,
    store: SQLiteEngineStore,
    client_id: str,
    channel_id: str,
    thread_id: str,
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool] | None = None,
    companion_local_context: str = "",
    persona_mode: str = "companion",
    memory_context_builder: MemoryContextBuilder = build_chat_context,
    proactive_reply_generator: ProactiveReplyGenerator = generate_proactive_companion_reply,
) -> ChatReply:
    return run_proactive_companion_turn_for_input(
        conversation=ProactiveConversationInput(
            user_id=client_id,
            channel="",
            channel_id=channel_id,
            thread_id=thread_id,
            kind=kind,
            companion_local_context=companion_local_context,
            persona_mode=persona_mode,
        ),
        store=store,
        agent_loop=agent_loop,
        tools=tools,
        memory_context_builder=memory_context_builder,
        proactive_reply_generator=proactive_reply_generator,
    )


def run_proactive_companion_turn_for_input(
    *,
    conversation: ProactiveConversationInput,
    store: SQLiteEngineStore,
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool] | None = None,
    memory_context_builder: MemoryContextBuilder = build_chat_context,
    proactive_reply_generator: ProactiveReplyGenerator = generate_proactive_companion_reply,
) -> ChatReply:
    memory_context = memory_context_builder(
        store=store,
        client_id=conversation.user_id,
        channel_id=conversation.channel_id,
        thread_id=conversation.thread_id,
        query="",
        current_user_text="",
        persona_mode=conversation.persona_mode,
    )
    profile = store.get_client_profile(conversation.user_id)
    return proactive_reply_generator(
        kind=conversation.kind,
        agent_loop=agent_loop,
        tools=tools,
        memory_context=memory_context,
        preferred_language=profile.preferred_language,
        companion_local_context=conversation.companion_local_context,
    )
