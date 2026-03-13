"""Telegram bot entry-point for the Analyst platform.

Uses python-telegram-bot (v20+) async API.
Reads ANALYST_TELEGRAM_TOKEN from the environment.

All user messages are routed through a persona-driven agent loop (陈襄).
The bot hydrates structured companion memory for each client/thread and records
the interaction after every reply.

Commands
--------
/start      - persona greeting
/help       - explain capabilities
/checkins_on  - enable occasional proactive check-ins
/checkins_off - disable proactive check-ins
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import os
import random
import sys
from pathlib import Path
from typing import Any

from telegram import MessageEntity, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Bootstrap the analyst package so we can import from src/
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from analyst.engine import AgentExecutor  # noqa: E402
from analyst.engine.backends.openrouter import OpenRouterConfig  # noqa: E402
from analyst.engine.live_types import AgentTool  # noqa: E402
from analyst.contracts import utc_now  # noqa: E402
from analyst.env import get_env_value  # noqa: E402
from analyst.memory import (  # noqa: E402
    ClientProfileUpdate,
    build_chat_context,
    build_group_chat_context,
    record_chat_interaction,
    refresh_group_member_public_inference,
)
from analyst.storage import SQLiteEngineStore  # noqa: E402
from analyst.tools._request_context import RequestImageInput, bind_request_image  # noqa: E402

from .bot_companion_timing import (  # noqa: E402
    _companion_local_context,
    _derive_companion_routine_state,
    _first_reply_delay_seconds,
    _is_same_local_day,
    _is_within_checkin_send_window,
    _lifestyle_ping_sent_at,
    _needs_emotional_follow_up,
    _next_checkin_window_start,
    _parse_iso_datetime,
    _reply_timing_bucket,
    _refresh_companion_lifestyle_state,
    _routine_checkin_kind,
    _same_day_retry_due,
    _cooldown_until,
    _telegram_chat_id_from_channel,
)
from .bot_constants import (  # noqa: E402
    COMPANION_CHECKIN_INTERVAL_SECONDS,
    MAX_HISTORY_TURNS,
    MAX_TELEGRAM_LENGTH,
)
from .bot_group_chat import (  # noqa: E402
    _append_group_buffer,
    _extract_message_text,
    _extract_reply_context,
    _get_user_display_name,
    _is_group_chat,
    _render_group_context,
    _render_group_mentions,
    _render_group_bubbles_with_mentions,
    _should_reply_in_group,
    _strip_bot_mention,
)
from .bot_history import _append_history, _get_history, _send_bot_bubbles  # noqa: E402
from .bot_media import (  # noqa: E402
    _cleanup_generated_media,
    _extract_attached_image,
    _summarize_user_message,
    _render_image_instruction,
)
from .companion_reminders import (  # noqa: E402
    apply_companion_reminder_update,
    render_companion_reminder_message,
)
from .companion_schedule import (  # noqa: E402
    apply_companion_schedule_update,
)
from analyst.runtime.chat import (  # noqa: E402
    UserChatReply,
    build_companion_services,
    generate_chat_reply,
    generate_proactive_companion_reply,
    split_into_bubbles,
)

logger = logging.getLogger(__name__)

def _refresh_companion_checkin_schedule(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    user_text: str,
    profile: Any,
    now: datetime,
) -> None:
    state = store.get_companion_checkin_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
    )
    if not state.enabled:
        return
    if _needs_emotional_follow_up(user_text, profile):
        due_at = now + timedelta(hours=18)
        store.schedule_companion_checkin(
            client_id=client_id,
            channel=channel_id,
            thread_id=thread_id,
            kind="follow_up",
            due_at=due_at.isoformat(),
        )


def _should_send_inactivity_ping(
    *,
    now: datetime,
    checkin_state: Any,
    last_user_message_at: str,
) -> bool:
    if not last_user_message_at:
        return False
    if checkin_state.pending_kind == "follow_up":
        return False
    if checkin_state.cooldown_until:
        cooldown_until = _parse_iso_datetime(checkin_state.cooldown_until)
        if cooldown_until is not None and cooldown_until > now:
            return False
    if checkin_state.last_sent_at and _is_same_local_day(checkin_state.last_sent_at, now):
        return False
    last_user_dt = _parse_iso_datetime(last_user_message_at)
    if last_user_dt is None:
        return False
    return now - last_user_dt >= timedelta(days=5)


def _should_send_routine_ping(
    *,
    now: datetime,
    lifestyle_state: Any,
    checkin_state: Any,
    last_user_message_at: str,
    kind: str,
) -> bool:
    if not kind:
        return False
    if checkin_state.pending_kind:
        return False
    if checkin_state.cooldown_until:
        cooldown_until = _parse_iso_datetime(checkin_state.cooldown_until)
        if cooldown_until is not None and cooldown_until > now:
            return False
    if last_user_message_at and _is_same_local_day(last_user_message_at, now):
        return False
    if checkin_state.last_sent_at and _is_same_local_day(checkin_state.last_sent_at, now):
        return False
    routine_sent_at = _lifestyle_ping_sent_at(lifestyle_state, kind)
    if routine_sent_at and _is_same_local_day(routine_sent_at, now):
        return False
    return True


async def _send_companion_proactive_message(
    *,
    store: SQLiteEngineStore,
    agent_loop: AgentExecutor,
    bot: Any,
    state: Any,
    kind: str,
    now: datetime,
) -> None:
    chat_id = _telegram_chat_id_from_channel(state.channel)
    if chat_id is None:
        return
    profile = store.get_client_profile(state.client_id)
    lifestyle_state = _refresh_companion_lifestyle_state(
        store,
        client_id=state.client_id,
        channel_id=state.channel,
        thread_id=state.thread_id,
        now=now,
    )
    memory_context = build_chat_context(
        store=store,
        client_id=state.client_id,
        channel_id=state.channel,
        thread_id=state.thread_id,
        query="",
        current_user_text="",
        persona_mode="companion",
    )
    reply = await asyncio.to_thread(
        generate_proactive_companion_reply,
        kind=kind,
        agent_loop=agent_loop,
        memory_context=memory_context,
        preferred_language=profile.preferred_language,
        companion_local_context=_companion_local_context(store, lifestyle_state, now),
    )
    apply_companion_schedule_update(
        store,
        reply.schedule_update,
        now=now,
        routine_state=str(getattr(lifestyle_state, "routine_state", "") or ""),
    )
    bubbles = split_into_bubbles(reply.text)
    await _send_bot_bubbles(bot, chat_id=chat_id, bubbles=bubbles)
    sent_at = utc_now().isoformat()
    store.append_conversation_message(
        client_id=state.client_id,
        channel=state.channel,
        thread_id=state.thread_id,
        role="assistant",
        content=reply.text,
        metadata={"proactive_kind": kind, "channel": state.channel},
    )
    store.enqueue_delivery(
        client_id=state.client_id,
        channel=state.channel,
        thread_id=state.thread_id,
        source_type="companion_checkin",
        content_rendered=reply.text,
        status="delivered",
        delivered_at=sent_at,
        metadata={"kind": kind},
    )
    if kind in {"morning", "evening", "weekend"}:
        store.mark_companion_lifestyle_ping_sent(
            client_id=state.client_id,
            channel=state.channel,
            thread_id=state.thread_id,
            kind=kind,
            sent_at=sent_at,
        )
        store.mark_companion_checkin_sent(
            client_id=state.client_id,
            channel=state.channel,
            thread_id=state.thread_id,
            kind=kind,
            sent_at=sent_at,
            cooldown_until="",
        )
        return
    store.mark_companion_checkin_sent(
        client_id=state.client_id,
        channel=state.channel,
        thread_id=state.thread_id,
        kind=kind,
        sent_at=sent_at,
        cooldown_until=_cooldown_until(utc_now()).isoformat(),
    )


async def _send_companion_user_reminder(
    *,
    store: SQLiteEngineStore,
    bot: Any,
    reminder: Any,
) -> None:
    chat_id = _telegram_chat_id_from_channel(reminder.channel)
    if chat_id is None:
        return
    text = render_companion_reminder_message(reminder)
    bubbles = split_into_bubbles(text)
    await _send_bot_bubbles(bot, chat_id=chat_id, bubbles=bubbles)
    sent_at = utc_now().isoformat()
    store.append_conversation_message(
        client_id=reminder.client_id,
        channel=reminder.channel,
        thread_id=reminder.thread_id,
        role="assistant",
        content=text,
        metadata={"reminder_id": reminder.reminder_id, "channel": reminder.channel},
    )
    store.enqueue_delivery(
        client_id=reminder.client_id,
        channel=reminder.channel,
        thread_id=reminder.thread_id,
        source_type="companion_reminder",
        content_rendered=text,
        status="delivered",
        delivered_at=sent_at,
        metadata={"reminder_id": reminder.reminder_id, "due_at": reminder.due_at},
    )
    store.mark_companion_reminder_sent(reminder_id=reminder.reminder_id, sent_at=sent_at)


async def _run_companion_checkins_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = getattr(context.job, "data", {}) or {}
    store: SQLiteEngineStore | None = job_data.get("store")
    agent_loop: AgentExecutor | None = job_data.get("agent_loop")
    if store is None:
        return
    now = utc_now()
    due_reminders = store.list_due_companion_reminders(now_iso=now.isoformat(), limit=20)
    for reminder in due_reminders:
        try:
            await _send_companion_user_reminder(
                store=store,
                bot=context.bot,
                reminder=reminder,
            )
        except Exception:
            logger.exception("Failed to send companion reminder")
    if agent_loop is None:
        return
    due_states = store.list_due_companion_checkins(now_iso=now.isoformat(), limit=10)
    for state in due_states:
        if state.pending_kind in {"follow_up", "inactivity"} and not _is_within_checkin_send_window(now):
            continue
        try:
            await _send_companion_proactive_message(
                store=store,
                agent_loop=agent_loop,
                bot=context.bot,
                state=state,
                kind=state.pending_kind,
                now=now,
            )
        except Exception:
            logger.exception("Failed to send companion proactive check-in")
            retry_due = _same_day_retry_due(now) if state.retry_count == 0 else None
            if retry_due is not None:
                store.reschedule_companion_checkin_retry(
                    client_id=state.client_id,
                    channel=state.channel,
                    thread_id=state.thread_id,
                    next_due_at=retry_due.isoformat(),
                    retry_count=1,
                )
            else:
                next_window = _next_checkin_window_start(now)
                store.reschedule_companion_checkin_retry(
                    client_id=state.client_id,
                    channel=state.channel,
                    thread_id=state.thread_id,
                    next_due_at=next_window.isoformat(),
                    retry_count=0,
                )
    enabled_states = store.list_enabled_companion_checkins(limit=100)
    for state in enabled_states:
        last_user_message_at = store.get_last_user_message_at(
            client_id=state.client_id,
            channel=state.channel,
            thread_id=state.thread_id,
        )
        if _is_within_checkin_send_window(now) and _should_send_inactivity_ping(
            now=now,
            checkin_state=state,
            last_user_message_at=last_user_message_at,
        ):
            try:
                await _send_companion_proactive_message(
                    store=store,
                    agent_loop=agent_loop,
                    bot=context.bot,
                    state=state,
                    kind="inactivity",
                    now=now,
                )
            except Exception:
                logger.exception("Failed to send companion inactivity check-in")
            continue
        routine_kind = _routine_checkin_kind(now)
        if not routine_kind:
            continue
        lifestyle_state = _refresh_companion_lifestyle_state(
            store,
            client_id=state.client_id,
            channel_id=state.channel,
            thread_id=state.thread_id,
            now=now,
        )
        if not _should_send_routine_ping(
            now=now,
            lifestyle_state=lifestyle_state,
            checkin_state=state,
            last_user_message_at=last_user_message_at,
            kind=routine_kind,
        ):
            continue
        try:
            await _send_companion_proactive_message(
                store=store,
                agent_loop=agent_loop,
                bot=context.bot,
                state=state,
                kind=routine_kind,
                now=now,
            )
        except Exception:
            logger.exception("Failed to send companion routine check-in")


async def _chat_reply(
    user_text: str,
    context: ContextTypes.DEFAULT_TYPE,
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
    group_context: str = "",
    is_group: bool = False,
    thread_id: str = "main",
    user_content: Any | None = None,
    history_text: str | None = None,
    attached_image: RequestImageInput | None = None,
    companion_local_context: str = "",
    persona_mode: str | None = None,
) -> UserChatReply:
    """Send user_text through the agent loop with persona, history, tools, and chat context."""
    del persona_mode
    history = _get_history(context, is_group=is_group, thread_id=thread_id)

    try:
        with bind_request_image(attached_image):
            result = await asyncio.to_thread(
                generate_chat_reply,
                user_text,
                history=history,
                agent_loop=agent_loop,
                tools=tools,
                memory_context=memory_context,
                preferred_language=preferred_language,
                group_context=group_context,
                user_content=user_content,
                companion_local_context=companion_local_context,
            )
        response_text = result.text
        profile_update = result.profile_update
        media = result.media
    except Exception:
        logger.exception("Agent loop error")
        response_text = "抱歉，我这边出了点小状况，稍后再试试？"
        profile_update = ClientProfileUpdate()
        media = []
        tool_audit = []
    else:
        tool_audit = result.tool_audit

    if len(response_text) > MAX_TELEGRAM_LENGTH:
        response_text = response_text[: MAX_TELEGRAM_LENGTH - 3] + "..."

    _append_history(
        context,
        "user",
        history_text or user_text,
        is_group=is_group,
        thread_id=thread_id,
    )
    _append_history(context, "assistant", response_text, is_group=is_group, thread_id=thread_id)

    return UserChatReply(
        text=response_text,
        profile_update=profile_update,
        media=media,
        tool_audit=tool_audit,
    )


def _build_services() -> tuple[AgentExecutor, list[AgentTool], SQLiteEngineStore]:
    """Wire up the agent loop, tools, and memory store."""
    agent_loop, tools, store = build_companion_services()
    return agent_loop, tools, store


def _make_start_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        if _is_group_chat(update):
            return
        context.user_data["history"] = []
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "(A new user just opened a conversation with you. Greet them and introduce yourself briefly.)",
            context,
            agent_loop,
            tools,
        )
        await update.effective_message.reply_text(reply.text)

    return start


def _make_help_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
):
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "(The user wants to know what you can help with. Explain naturally, and mention /checkins_on plus /checkins_off for occasional opt-in check-ins.)",
            context,
            agent_loop,
            tools,
        )
        await update.effective_message.reply_text(reply.text)

    return help_command


def _make_checkins_toggle_handler(
    store: SQLiteEngineStore,
    *,
    enabled: bool,
):
    async def toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None or update.effective_chat is None:
            return
        if _is_group_chat(update):
            return
        user_id = str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id)
        channel_id = f"telegram:{update.effective_chat.id}"
        topic_id = getattr(update.effective_message, "message_thread_id", None)
        thread_id = str(topic_id) if topic_id is not None else "main"
        now = utc_now()
        _refresh_companion_lifestyle_state(
            store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            now=now,
        )
        state = store.set_companion_checkins_enabled(
            client_id=user_id,
            channel=channel_id,
            thread_id=thread_id,
            enabled=enabled,
        )
        if enabled and state.enabled:
            text = "行，那我之后会很偶尔地主动来问候你一下。你想停的话，随时 /checkins_off。"
        else:
            text = "好，我不再主动发 check-in 了。你之后想开回来，随时 /checkins_on。"
        await update.effective_message.reply_text(text)

    return toggle


def _make_regime_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
):
    async def regime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "请展示当前宏观状态。",
            context,
            agent_loop,
            tools,
        )
        await update.effective_message.reply_text(reply.text)

    return regime


def _make_calendar_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
):
    async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "请展示近期经济数据日历。",
            context,
            agent_loop,
            tools,
        )
        await update.effective_message.reply_text(reply.text)

    return calendar


def _make_premarket_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
):
    async def premarket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "请展示早盘速递。",
            context,
            agent_loop,
            tools,
        )
        await update.effective_message.reply_text(reply.text)

    return premarket


def _make_message_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
    store: SQLiteEngineStore,
):
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        message = update.effective_message
        attached_image = await _extract_attached_image(update, context)
        text = _extract_message_text(message)
        if not text and attached_image is None:
            return
        user_id = str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id)
        channel_id = f"telegram:{update.effective_chat.id}"
        topic_id = getattr(message, "message_thread_id", None)
        thread_id = str(topic_id) if topic_id is not None else "main"
        now_utc = utc_now()
        companion_lifestyle_state = None
        companion_local_context = ""
        companion_lifestyle_state = _refresh_companion_lifestyle_state(
            store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            now=now_utc,
        )
        companion_local_context = _companion_local_context(store, companion_lifestyle_state, now_utc)

        in_group = _is_group_chat(update)
        if not in_group:
            store.clear_companion_checkin_pending(
                client_id=user_id,
                channel=channel_id,
                thread_id=thread_id,
            )

        reply_context = _extract_reply_context(update)
        history_user_text = _summarize_user_message(text, image=attached_image)

        if in_group:
            sender_name = _get_user_display_name(update)
            group_id = str(update.effective_chat.id)
            _append_group_buffer(context, thread_id, sender_name, history_user_text)

            # Persist group message and track member
            store.append_group_message(
                group_id=group_id,
                thread_id=thread_id,
                user_id=user_id,
                display_name=sender_name,
                content=history_user_text,
            )
            store.upsert_group_member(
                group_id=group_id,
                user_id=user_id,
                display_name=sender_name,
            )
            refresh_group_member_public_inference(store=store, group_id=group_id)

            if not _should_reply_in_group(update, context):
                return

            bot_username = context.bot.username or ""
            text = _strip_bot_mention(text, bot_username)
            history_user_text = _summarize_user_message(text, image=attached_image)
            if not text and attached_image is None:
                return

            group_context_str = _render_group_context(context, thread_id)
        else:
            group_id = ""
            group_context_str = ""

        # Build enriched text for LLM (includes reply context)
        base_llm_text = text or "The user sent an image without caption."
        if reply_context:
            llm_text = f'回复消息：\n"{reply_context}"\n\n用户说：\n{base_llm_text}'
        else:
            llm_text = base_llm_text
        first_reply_delay_seconds = _first_reply_delay_seconds(
            text,
            has_image=attached_image is not None,
        )
        user_content = (
            [
                {"type": "text", "text": _render_image_instruction(llm_text, image=attached_image)},
                {"type": "image_url", "image_url": {"url": attached_image.data_uri}},
            ]
            if attached_image is not None
            else llm_text
        )

        await update.effective_chat.send_action(ChatAction.TYPING)
        reply_started = asyncio.get_running_loop().time()
        if in_group and group_id:
            # Three-layer context: group messages + speaker memory + participant model
            memory_context = build_group_chat_context(
                store=store,
                group_id=group_id,
                thread_id=thread_id,
                speaker_user_id=user_id,
                persona_mode="companion",
            )
        else:
            memory_context = build_chat_context(
                store=store,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                query=llm_text,
                current_user_text=history_user_text,
                persona_mode="companion",
            )
        profile = store.get_client_profile(user_id)
        reply = await _chat_reply(
            llm_text,
            context,
            agent_loop,
            tools,
            memory_context=memory_context,
            preferred_language=profile.preferred_language,
            group_context=group_context_str,
            is_group=in_group,
            thread_id=thread_id,
            user_content=user_content,
            history_text=history_user_text,
            attached_image=attached_image,
            companion_local_context=companion_local_context,
        )
        mention_members = store.list_group_members(group_id, limit=100) if in_group and group_id else []
        rendered_reply_text = reply.text
        rendered_bubbles: list[tuple[str, list[MessageEntity]]] | None = None
        if mention_members:
            rendered_reply_text, rendered_bubbles = _render_group_bubbles_with_mentions(reply.text, mention_members)
            history = _get_history(context, is_group=in_group, thread_id=thread_id)
            if history and history[-1]["role"] == "assistant":
                history[-1]["content"] = rendered_reply_text
        apply_companion_schedule_update(
            store,
            reply.schedule_update,
            now=now_utc,
            routine_state=str(getattr(companion_lifestyle_state, "routine_state", "") or ""),
            user_text=history_user_text,
        )
        if not in_group:
            apply_companion_reminder_update(
                store,
                reply.reminder_update,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                now=now_utc,
                preferred_language=profile.preferred_language,
            )
        record_chat_interaction(
            store=store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            user_text=history_user_text,
            assistant_text=rendered_reply_text,
            assistant_profile_update=reply.profile_update,
            tool_audit=reply.tool_audit,
            persona_mode="companion",
        )
        updated_profile = store.get_client_profile(user_id)
        if not in_group:
            _refresh_companion_checkin_schedule(
                store,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                user_text=history_user_text,
                profile=updated_profile,
                now=now_utc,
            )
        bubbles = rendered_bubbles or [(bubble, []) for bubble in split_into_bubbles(rendered_reply_text)]
        elapsed = asyncio.get_running_loop().time() - reply_started
        remaining_delay = first_reply_delay_seconds - elapsed
        if remaining_delay > 0:
            await update.effective_chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(remaining_delay)
        for i, (bubble_text, bubble_entities) in enumerate(bubbles):
            if i > 0:
                await update.effective_chat.send_action(ChatAction.TYPING)
                delay = min(0.5 + len(bubble_text) * 0.01, 2.5) + random.uniform(-0.3, 0.3)
                await asyncio.sleep(max(delay, 0.3))
            reply_kwargs: dict[str, Any] = {"text": bubble_text}
            if bubble_entities:
                reply_kwargs["entities"] = bubble_entities
            await update.effective_message.reply_text(**reply_kwargs)

        for media_item in reply.media:
            try:
                if media_item.kind == "photo":
                    await update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO)
                    if media_item.url.startswith(("http://", "https://")):
                        await update.effective_message.reply_photo(
                            photo=media_item.url, caption=media_item.caption or None,
                        )
                    elif os.path.isfile(media_item.url):
                        with open(media_item.url, "rb") as f:
                            await update.effective_message.reply_photo(
                                photo=f, caption=media_item.caption or None,
                            )
                elif media_item.kind == "video":
                    await update.effective_chat.send_action(ChatAction.UPLOAD_VIDEO)
                    if media_item.url.startswith(("http://", "https://")):
                        await update.effective_message.reply_video(
                            video=media_item.url,
                            caption=media_item.caption or None,
                        )
                    elif os.path.isfile(media_item.url):
                        with open(media_item.url, "rb") as f:
                            await update.effective_message.reply_video(
                                video=f,
                                caption=media_item.caption or None,
                                supports_streaming=True,
                            )
            except Exception:
                logger.exception("Failed to send media item")
            finally:
                for cleanup_path in (media_item.url, *media_item.cleanup_paths):
                    _cleanup_generated_media(cleanup_path)

        if in_group and group_id:
            _append_group_buffer(context, thread_id, "陈襄", rendered_reply_text, role="assistant")
            store.append_group_message(
                group_id=group_id,
                thread_id=thread_id,
                user_id="assistant",
                display_name="陈襄",
                content=rendered_reply_text,
            )

    return handle_message


def build_application(token: str) -> Application:
    """Build and return a fully configured Telegram Application."""
    agent_loop, tools, store = _build_services()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _make_start_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("help", _make_help_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("checkins_on", _make_checkins_toggle_handler(store, enabled=True)))
    app.add_handler(CommandHandler("checkins_off", _make_checkins_toggle_handler(store, enabled=False)))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND,
            _make_message_handler(agent_loop, tools, store),
        )
    )
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            _run_companion_checkins_job,
            interval=COMPANION_CHECKIN_INTERVAL_SECONDS,
            first=60,
            data={"store": store, "agent_loop": agent_loop},
            name="companion_checkins",
        )
    else:
        logger.warning(
            "Companion proactive check-ins require python-telegram-bot[job-queue]; scheduler not started."
        )

    return app


def main() -> None:
    """CLI entry-point: read token from env and start polling."""
    logging.basicConfig(
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = get_env_value("ANALYST_TELEGRAM_TOKEN")
    if not token:
        logger.error("ANALYST_TELEGRAM_TOKEN environment variable is not set")
        sys.exit(1)

    logger.info("Starting Analyst Telegram bot ...")
    app = build_application(token)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
