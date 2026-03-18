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
    compute_late_night_activity_pct,
    evaluate_relationship_checkin_kind,
    _first_reply_delay_seconds,
    get_send_window,
    is_within_send_window,
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
    DEFAULT_USER_TIMEZONE,
    MAX_HISTORY_TURNS,
    MAX_TELEGRAM_LENGTH,
)
from .bot_group_chat import (  # noqa: E402
    _append_group_buffer,
    _extract_mentioned_user_ids,
    _extract_message_text,
    _extract_reply_context,
    _extract_reply_user_id,
    _get_user_display_name,
    _is_group_chat,
    _render_group_context,
    _render_group_mentions,
    _render_group_bubbles_with_mentions,
    _should_reply_in_group,
    _strip_bot_mention,
)
from .group_intervention import (  # noqa: E402
    BOT_DISPLAY_NAMES,
    BOT_USER_ID,
    evaluate_group_intervention,
    should_cancel_intervention,
)
from .bot_history import _append_history, _get_history, _send_bot_bubbles  # noqa: E402
from .bot_media import (  # noqa: E402
    _cleanup_generated_media,
    _extract_attached_document,
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
from analyst.runtime.conversation_service import (  # noqa: E402
    persist_companion_turn,
    persist_companion_turn_for_input,
    run_companion_turn,
    run_companion_turn_for_input,
    run_proactive_companion_turn,
    run_proactive_companion_turn_for_input,
)
from analyst.runtime.environment_adapter import (  # noqa: E402
    ConversationInput,
    build_proactive_conversation_input,
    build_telegram_conversation_input,
)
from analyst.runtime.platform.telegram import (  # noqa: E402
    persist_telegram_companion_turn,
    prepare_telegram_turn,
    refresh_companion_checkin_schedule,
    should_send_inactivity_ping,
    should_send_routine_ping,
)

logger = logging.getLogger(__name__)


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
    lifestyle_state = _refresh_companion_lifestyle_state(
        store,
        client_id=state.client_id,
        channel_id=state.channel,
        thread_id=state.thread_id,
        now=now,
    )
    conversation = build_proactive_conversation_input(
        user_id=state.client_id,
        channel="telegram",
        channel_id=state.channel,
        thread_id=state.thread_id,
        kind=kind,
        companion_local_context=_companion_local_context(store, lifestyle_state, now, client_id=state.client_id),
    )

    # --- Image decision for proactive outreach ---
    proactive_tools: list[AgentTool] | None = None
    try:
        from analyst.delivery.image_decision import should_generate_image

        _rel = store.get_companion_relationship_state(client_id=state.client_id)
        _prof = store.get_client_profile(state.client_id)
        _stage = str(getattr(_rel, "relationship_stage", "acquaintance") or "acquaintance")
        _images_today = store.count_images_sent_today(
            client_id=state.client_id,
            timezone_name=_prof.timezone_name,
        )
        _proactive_today = store.count_proactive_images_today(
            client_id=state.client_id,
            timezone_name=_prof.timezone_name,
        )
        _warmup_5d = store.count_warmup_images_last_5_days(client_id=state.client_id)
        _turns_gap = store.get_turns_since_last_image(
            client_id=state.client_id,
            channel=state.channel,
            thread_id=state.thread_id,
        )
        _image_decision = should_generate_image(
            reply_text="",
            relationship_stage=_stage,
            stress_level=_prof.stress_level or "",
            images_sent_today=_images_today,
            turns_since_last_image=_turns_gap,
            current_hour=now.hour,
            is_proactive=True,
            outreach_kind=kind,
            user_text="",
            proactive_images_today=_proactive_today,
            warmup_images_last_5_days=_warmup_5d,
        )
        if _image_decision.allowed and _image_decision.recommended:
            from analyst.tools._image_gen import build_image_gen_tool
            proactive_tools = [build_image_gen_tool()]
    except Exception:
        logger.debug("Proactive image decision failed, skipping image", exc_info=True)

    reply = await asyncio.to_thread(
        run_proactive_companion_turn_for_input,
        conversation=conversation,
        store=store,
        agent_loop=agent_loop,
        tools=proactive_tools,
        memory_context_builder=build_chat_context,
        proactive_reply_generator=generate_proactive_companion_reply,
    )
    apply_companion_schedule_update(
        store,
        reply.schedule_update,
        client_id=state.client_id,
        now=now,
        routine_state=str(getattr(lifestyle_state, "routine_state", "") or ""),
    )
    # Outreach dedup: reject if substantially similar to recent outreach
    from analyst.delivery.outreach_dedup import is_duplicate_outreach

    recent_outreach = store.list_recent_companion_outreach(client_id=state.client_id, days=7)
    if is_duplicate_outreach(reply.text, [r.content_raw for r in recent_outreach]):
        logger.info("Outreach dedup: blocked duplicate for client=%s kind=%s", state.client_id, kind)
        return
    bubbles = split_into_bubbles(reply.text)
    await _send_bot_bubbles(bot, chat_id=chat_id, bubbles=bubbles)

    # Send proactive media (images/videos) if generated
    for media_item in reply.media:
        try:
            if media_item.kind == "photo":
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                if media_item.url.startswith(("http://", "https://")):
                    await bot.send_photo(chat_id=chat_id, photo=media_item.url)
                elif os.path.isfile(media_item.url):
                    with open(media_item.url, "rb") as f:
                        await bot.send_photo(chat_id=chat_id, photo=f)
            elif media_item.kind == "video":
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                if media_item.url.startswith(("http://", "https://")):
                    await bot.send_video(chat_id=chat_id, video=media_item.url)
                elif os.path.isfile(media_item.url):
                    with open(media_item.url, "rb") as f:
                        await bot.send_video(chat_id=chat_id, video=f)
        except Exception:
            logger.exception("Failed to send proactive media")
        finally:
            for cleanup_path in (media_item.url, *media_item.cleanup_paths):
                _cleanup_generated_media(cleanup_path)

    # Log proactive image generation
    if reply.media:
        try:
            _rel_log = store.get_companion_relationship_state(client_id=state.client_id)
            _stage_log = str(getattr(_rel_log, "relationship_stage", "acquaintance") or "acquaintance")
            for media_item in reply.media:
                store.log_companion_image(
                    client_id=state.client_id,
                    channel=state.channel,
                    thread_id=state.thread_id,
                    mode=media_item.kind,
                    trigger_type="proactive",
                    outreach_kind=kind,
                    relationship_stage=_stage_log,
                    generated_at=utc_now().isoformat(),
                )
        except Exception:
            logger.debug("Failed to log proactive image", exc_info=True)

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
    store.log_companion_outreach(
        client_id=state.client_id,
        channel=state.channel,
        thread_id=state.thread_id,
        kind=kind,
        content_raw=reply.text,
        sent_at=sent_at,
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
        try:
            _rel2 = store.get_companion_relationship_state(client_id=state.client_id)
            _prof2 = store.get_client_profile(state.client_id)
            _tz2 = _prof2.timezone_name or DEFAULT_USER_TIMEZONE
            _stage2 = str(getattr(_rel2, "relationship_stage", "acquaintance") or "acquaintance")
            _rom2 = float(getattr(_rel2, "tendency_romantic", 0.0) or 0.0)
            _msgs2 = store.list_recent_message_timestamps(client_id=state.client_id, limit=50)
            _late2 = compute_late_night_activity_pct(_msgs2, _tz2)
            _win2 = get_send_window(_stage2, tendency_romantic=_rom2, late_night_activity_pct=_late2)
            _in_window = is_within_send_window(now, window=_win2, timezone_name=_tz2)
        except Exception:
            _in_window = _is_within_checkin_send_window(now)
        if _in_window and should_send_inactivity_ping(
            now=now,
            checkin_state=state,
            last_user_message_at=last_user_message_at,
            parse_iso_datetime=_parse_iso_datetime,
            is_same_local_day=_is_same_local_day,
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
        # Relationship-aware proactive check-in (with response rate throttling)
        if _in_window and not state.pending_kind:
            try:
                from analyst.delivery.outreach_metrics import (
                    compute_outreach_metrics,
                    compute_outreach_throttle,
                    should_send_outreach,
                )

                recent_outreach = store.list_recent_companion_outreach(client_id=state.client_id, days=7)
                metrics = compute_outreach_metrics(recent_outreach)
                throttle = compute_outreach_throttle(metrics)

                # If paused, update relationship state and skip
                if throttle.paused:
                    store.update_companion_relationship_state(
                        client_id=state.client_id,
                        outreach_paused=True,
                        outreach_paused_at=now.isoformat(),
                    )
                    continue

                today_count = store.count_outreach_sent_today(
                    client_id=state.client_id, channel=state.channel, thread_id=state.thread_id,
                )
                last_sent = store.get_last_outreach_sent_at(
                    client_id=state.client_id, channel=state.channel, thread_id=state.thread_id,
                )
                hours_since = 999.0
                if last_sent:
                    try:
                        _last_dt = datetime.fromisoformat(last_sent)
                        if _last_dt.tzinfo is None:
                            _last_dt = _last_dt.replace(tzinfo=now.tzinfo)
                        hours_since = (now - _last_dt).total_seconds() / 3600
                    except (ValueError, TypeError):
                        pass
                if not should_send_outreach(throttle, outreach_count_today=today_count, hours_since_last_outreach=hours_since):
                    continue

                rel_state = store.get_companion_relationship_state(client_id=state.client_id)
                rel_kind = evaluate_relationship_checkin_kind(
                    rel_state,
                    last_user_message_at=last_user_message_at,
                    now=now,
                    outreach_metrics=metrics,
                    last_outreach_sent_at=last_sent,
                )
                if rel_kind and not _is_same_local_day(state.last_sent_at, now):
                    await _send_companion_proactive_message(
                        store=store,
                        agent_loop=agent_loop,
                        bot=context.bot,
                        state=state,
                        kind=rel_kind,
                        now=now,
                    )
                    continue
            except Exception:
                logger.exception("Failed to send relationship-aware check-in")
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
        if not should_send_routine_ping(
            now=now,
            lifestyle_state=lifestyle_state,
            checkin_state=state,
            last_user_message_at=last_user_message_at,
            kind=routine_kind,
            parse_iso_datetime=_parse_iso_datetime,
            is_same_local_day=_is_same_local_day,
            lifestyle_ping_sent_at=_lifestyle_ping_sent_at,
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
    conversation: ConversationInput | None = None,
    store: SQLiteEngineStore | None = None,
    client_id: str = "",
    channel_id: str = "",
    group_id: str = "",
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
        if conversation is not None and store is not None:
            result = await asyncio.to_thread(
                run_companion_turn_for_input,
                conversation=conversation,
                store=store,
                agent_loop=agent_loop,
                tools=tools,
                memory_context_builder=build_chat_context,
                group_memory_context_builder=build_group_chat_context,
                reply_generator=generate_chat_reply,
            )
        elif store is not None and client_id and channel_id:
            result = await asyncio.to_thread(
                run_companion_turn,
                user_text=user_text,
                history=history,
                agent_loop=agent_loop,
                tools=tools,
                store=store,
                client_id=client_id,
                channel_id=channel_id,
                thread_id=thread_id,
                query=user_text,
                current_user_text=history_text or user_text,
                group_context=group_context,
                group_id=group_id if is_group else "",
                user_content=user_content,
                companion_local_context=companion_local_context,
                attached_image=attached_image,
                memory_context_builder=build_chat_context,
                group_memory_context_builder=build_group_chat_context,
                reply_generator=generate_chat_reply,
            )
        else:
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

    _append_history(
        context,
        "user",
        (conversation.current_user_text if conversation is not None else "") or history_text or user_text,
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


_AUTONOMOUS_INSTRUCTIONS: dict[str, str] = {
    "name_mention": "(群里有人提到了你的名字，自然回应一句。)",
    "interest_match": "(群里有人在讨论你感兴趣的话题，可以轻轻接一句。)",
    "unanswered_question": "(群里有个问题好像没人回答，你可以简短答一句。)",
    "emotional_gap": "(群里有人好像不太开心，没人回应，你可以轻轻说一句关心的话。)",
}


async def _maybe_schedule_autonomous_intervention(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    store: SQLiteEngineStore,
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
    group_id: str,
    thread_id: str,
    user_id: str,
    now_utc: datetime,
) -> None:
    """Evaluate whether to autonomously intervene, and schedule if appropriate."""
    try:
        # Send window check
        try:
            _rel = store.get_companion_relationship_state(client_id=user_id)
            _stage = str(getattr(_rel, "relationship_stage", "familiar") or "familiar")
            _rom = float(getattr(_rel, "tendency_romantic", 0.0) or 0.0)
            _msgs_ts = store.list_recent_message_timestamps(client_id=user_id, limit=50)
            _prof = store.get_client_profile(user_id)
            _tz = _prof.timezone_name or DEFAULT_USER_TIMEZONE
            _late = compute_late_night_activity_pct(_msgs_ts, _tz)
            _win = get_send_window(_stage, tendency_romantic=_rom, late_night_activity_pct=_late)
            send_window_active = is_within_send_window(now_utc, window=_win, timezone_name=_tz)
        except Exception:
            send_window_active = True  # default open if lookup fails

        today_str = now_utc.strftime("%Y-%m-%d")
        interest_count = store.get_autonomous_message_count_today(group_id, today_str)
        recent = store.list_group_messages(group_id, thread_id, limit=30)
        messages = [
            {
                "message_id": m.message_id,
                "user_id": m.user_id,
                "content": m.content,
                "display_name": m.display_name,
                "created_at": m.created_at,
            }
            for m in recent
        ]
        current = messages[-1] if messages else {}

        result = evaluate_group_intervention(
            messages=messages,
            current_message=current,
            bot_display_names=BOT_DISPLAY_NAMES,
            persona_mode="companion",
            send_window_active=send_window_active,
            bot_user_id=BOT_USER_ID,
            interest_triggers_today=interest_count,
            now=now_utc,
        )

        if not result.should_intervene or result.trigger is None:
            return

        asyncio.ensure_future(
            _delayed_autonomous_reply(
                update=update,
                context=context,
                store=store,
                agent_loop=agent_loop,
                tools=tools,
                group_id=group_id,
                thread_id=thread_id,
                trigger=result.trigger,
                trigger_message_id=result.trigger_message_id,
                delay_seconds=result.delay_seconds,
            )
        )
    except Exception:
        logger.debug("Autonomous intervention evaluation failed", exc_info=True)


async def _delayed_autonomous_reply(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    store: SQLiteEngineStore,
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
    group_id: str,
    thread_id: str,
    trigger: Any,
    trigger_message_id: int,
    delay_seconds: float,
) -> None:
    """Wait, re-evaluate, then send an autonomous reply if still appropriate."""

    try:
        await asyncio.sleep(delay_seconds)

        # Re-evaluate: check messages that arrived during the delay
        new_messages = store.list_group_messages_since(group_id, thread_id, trigger_message_id)
        msgs_dicts = [
            {"content": m.content, "user_id": m.user_id, "display_name": m.display_name}
            for m in new_messages
        ]
        if should_cancel_intervention(messages_since_trigger=msgs_dicts, trigger=trigger):
            logger.debug(
                "Autonomous intervention cancelled for group=%s trigger=%s",
                group_id, trigger.kind,
            )
            return

        # Build synthetic instruction
        instruction = _AUTONOMOUS_INSTRUCTIONS.get(trigger.kind, "")
        group_context_str = _render_group_context(context, thread_id)

        # Use the most recent messages for context
        recent = store.list_group_messages(group_id, thread_id, limit=30)
        history_lines = [f"{m.display_name}: {m.content}" for m in recent[-15:]]
        group_ctx = "\n".join(history_lines) if history_lines else group_context_str

        conversation = ConversationInput(
            user_id=BOT_USER_ID,
            channel="telegram",
            channel_id=f"telegram:{group_id}",
            thread_id=thread_id,
            message=instruction,
            current_user_text=instruction,
            group_context=group_ctx,
            group_id=group_id,
            persona_mode="companion",
            group_autonomous=True,
        )

        reply = await asyncio.to_thread(
            run_companion_turn_for_input,
            conversation=conversation,
            store=store,
            agent_loop=agent_loop,
            tools=tools,
            memory_context_builder=build_chat_context,
            group_memory_context_builder=build_group_chat_context,
            reply_generator=generate_chat_reply,
        )
        response_text = reply.text
        if not response_text or response_text == "嗯":
            return

        bubbles = split_into_bubbles(response_text)
        chat_id = int(group_id)
        await _send_bot_bubbles(context.bot, chat_id=chat_id, bubbles=bubbles)

        # Record to group buffer and store
        _append_group_buffer(context, thread_id, "陈襄", response_text, role="assistant")
        store.append_group_message(
            group_id=group_id,
            thread_id=thread_id,
            user_id=BOT_USER_ID,
            display_name="陈襄",
            content=response_text,
        )

        # Increment autonomous message count
        now_iso = utc_now().isoformat()
        today_str = now_iso[:10]
        store.increment_autonomous_message_count(group_id, today_str, now_iso)

        logger.info(
            "Autonomous intervention sent: group=%s trigger=%s",
            group_id, trigger.kind,
        )
    except Exception:
        logger.exception("Autonomous intervention reply failed for group=%s", group_id)


_DM_DEBOUNCE_SECONDS = 2.0
"""Wait this long after the last DM message before processing.

When a user sends multiple messages in quick succession (typing style),
this debounce window combines them into a single LLM turn instead of
generating a separate reply for each fragment.
"""


def _make_message_handler(
    agent_loop: AgentExecutor,
    tools: list[AgentTool],
    store: SQLiteEngineStore,
):
    # Per-chat debounce state: chat_id → asyncio.Task
    _debounce_timers: dict[int, asyncio.Task] = {}

    async def _process_batched_dm(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """Pop all buffered messages for *chat_id* and process as a single turn."""
        buf: list[dict[str, Any]] = context.chat_data.pop("_dm_buffer", [])
        _debounce_timers.pop(chat_id, None)
        if not buf:
            return
        # Combine text fragments; keep the last image/document attachment
        combined_texts: list[str] = [m["text"] for m in buf if m.get("text")]
        combined_text = "\n".join(combined_texts)
        last_image = next((m["image"] for m in reversed(buf) if m.get("image")), None)
        last_document = next((m["doc"] for m in reversed(buf) if m.get("doc")), None)
        # Use the last update for reply context
        await _handle_single_turn(
            update, context, agent_loop, tools, store,
            text=combined_text,
            attached_image=last_image,
            attached_document=last_document,
        )

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        message = update.effective_message
        attached_image = await _extract_attached_image(update, context)
        attached_document = await _extract_attached_document(update, context)
        text = _extract_message_text(message)
        if not text and attached_image is None and attached_document is None:
            return

        in_group = _is_group_chat(update)

        # --- DM debounce: buffer rapid-fire messages ---
        if not in_group and _DM_DEBOUNCE_SECONDS > 0:
            chat_id = update.effective_chat.id
            if "_dm_buffer" not in context.chat_data:
                context.chat_data["_dm_buffer"] = []
            context.chat_data["_dm_buffer"].append({
                "text": text,
                "image": attached_image,
                "doc": attached_document,
            })
            # Cancel any existing timer and reset
            existing = _debounce_timers.pop(chat_id, None)
            if existing and not existing.done():
                existing.cancel()

            async def _fire_after_debounce(
                _update: Update,
                _context: ContextTypes.DEFAULT_TYPE,
                _chat_id: int,
            ) -> None:
                await asyncio.sleep(_DM_DEBOUNCE_SECONDS)
                try:
                    await _process_batched_dm(_update, _context, _chat_id)
                except Exception:
                    logger.exception("Debounced DM processing failed for chat=%s", _chat_id)

            _debounce_timers[chat_id] = asyncio.create_task(
                _fire_after_debounce(update, context, chat_id)
            )
            return

        # --- Group messages or debounce disabled: process immediately ---
        await _handle_single_turn(
            update, context, agent_loop, tools, store,
            text=text,
            attached_image=attached_image,
            attached_document=attached_document,
        )

    async def _handle_single_turn(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        agent_loop: AgentExecutor,
        tools: list[AgentTool],
        store: SQLiteEngineStore,
        *,
        text: str,
        attached_image: Any | None,
        attached_document: Any | None,
    ) -> None:
        message = update.effective_message
        if message is None:
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
        companion_local_context = _companion_local_context(store, companion_lifestyle_state, now_utc, client_id=user_id)

        in_group = _is_group_chat(update)
        if not in_group:
            store.clear_companion_checkin_pending(
                client_id=user_id,
                channel=channel_id,
                thread_id=thread_id,
            )

        reply_context = _extract_reply_context(update)
        history_user_text = _summarize_user_message(text, image=attached_image, document=attached_document)

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
            _sender_username = ""
            if update.effective_user and update.effective_user.username:
                _sender_username = update.effective_user.username
            store.upsert_group_member(
                group_id=group_id,
                user_id=user_id,
                display_name=sender_name,
                username=_sender_username,
            )
            refresh_group_member_public_inference(store=store, group_id=group_id)

            # Detect and persist group relational role assignments
            from analyst.memory.relationship import detect_group_relational_roles

            _mentioned = _extract_mentioned_user_ids(update)
            # Enrich mention lookup with group member display names and usernames.
            # Use direct assignment to override @username placeholders from MENTION
            # entities (which lack real user_ids) with actual user_ids from DB.
            _group_members = store.list_group_members(group_id, limit=30)
            for _gm in _group_members:
                if _gm.display_name:
                    _dn = _gm.display_name.strip().lower()
                    if _dn not in _mentioned or str(_mentioned[_dn]).startswith("@"):
                        _mentioned[_dn] = _gm.user_id
                if _gm.username:
                    _un = _gm.username.strip().lower()
                    if _un not in _mentioned or str(_mentioned[_un]).startswith("@"):
                        _mentioned[_un] = _gm.user_id

            _role_update = detect_group_relational_roles(
                history_user_text,
                speaker_user_id=user_id,
                reply_to_user_id=_extract_reply_user_id(update),
                mentioned_users=_mentioned,
            )
            if _role_update.bot_role is not None:
                store.update_group_bot_relational_role(
                    group_id=group_id, bot_relational_role=_role_update.bot_role,
                )
            if _role_update.speaker_role is not None:
                store.update_group_member_relational_role(
                    group_id=group_id, user_id=user_id,
                    relational_role=_role_update.speaker_role,
                )
            for _target_uid, _rel_role in _role_update.third_party_roles:
                # Skip unresolved mentions (e.g. @username not matching any member)
                if _target_uid.startswith("@"):
                    continue
                store.update_group_member_relational_role(
                    group_id=group_id, user_id=_target_uid,
                    relational_role=_rel_role,
                )

            if not _should_reply_in_group(update, context):
                asyncio.ensure_future(
                    _maybe_schedule_autonomous_intervention(
                        update=update,
                        context=context,
                        store=store,
                        agent_loop=agent_loop,
                        tools=tools,
                        group_id=group_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        now_utc=now_utc,
                    )
                )
                return

            bot_username = context.bot.username or ""
            text = _strip_bot_mention(text, bot_username)
            history_user_text = _summarize_user_message(text, image=attached_image, document=attached_document)
            if not text and attached_image is None and attached_document is None:
                return

            group_context_str = _render_group_context(context, thread_id)
        else:
            group_id = ""
            group_context_str = ""

        # Inject document text into user message for the LLM
        if attached_document and not attached_image:
            doc_block = f"[Attached document: {attached_document.filename}]\n{attached_document.text}"
            if attached_document.truncated:
                doc_block += "\n[... document truncated ...]"
            text = f"{text}\n\n{doc_block}" if text else doc_block

        preparation = prepare_telegram_turn(
            user_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            text=text,
            reply_context=reply_context,
            history=_get_history(context, is_group=in_group, thread_id=thread_id),
            history_user_text=history_user_text,
            group_context=group_context_str,
            group_id=group_id,
            companion_local_context=companion_local_context,
            attached_image=attached_image,
            render_image_instruction=_render_image_instruction,
            first_reply_delay=_first_reply_delay_seconds,
        )
        llm_text = preparation.llm_text
        first_reply_delay_seconds = preparation.first_reply_delay_seconds
        conversation = preparation.conversation

        await update.effective_chat.send_action(ChatAction.TYPING)
        reply_started = asyncio.get_running_loop().time()
        reply = await _chat_reply(
            llm_text,
            context,
            agent_loop,
            tools,
            conversation=conversation,
            store=store,
            client_id=user_id,
            channel_id=channel_id,
            group_id=group_id,
            group_context=group_context_str,
            is_group=in_group,
            thread_id=thread_id,
            user_content=conversation.user_content,
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
        updated_profile = persist_telegram_companion_turn(
            store=store,
            conversation=conversation,
            reply=reply,
            assistant_text=rendered_reply_text,
            history_user_text=history_user_text,
            now=now_utc,
            routine_state=str(getattr(companion_lifestyle_state, "routine_state", "") or ""),
            in_group=in_group,
            refresh_schedule=refresh_companion_checkin_schedule,
            apply_companion_schedule_update=apply_companion_schedule_update,
            apply_companion_reminder_update=apply_companion_reminder_update,
            record_chat_interaction=record_chat_interaction,
            needs_emotional_follow_up=_needs_emotional_follow_up,
        )
        # Attribute user reply to most recent outreach (within 4h window)
        # and resume outreach if paused (user initiating = organic engagement)
        try:
            store.mark_outreach_replied(
                client_id=conversation.user_id,
                channel=conversation.channel_id,
                thread_id=thread_id,
                replied_at=now_utc.isoformat(),
            )
            _rel = store.get_companion_relationship_state(client_id=conversation.user_id)
            if getattr(_rel, "outreach_paused", False):
                store.update_companion_relationship_state(
                    client_id=conversation.user_id,
                    outreach_paused=False,
                    outreach_paused_at="",
                )
        except Exception:
            logger.debug("Outreach reply attribution skipped", exc_info=True)
        bubbles = rendered_bubbles or [(bubble, []) for bubble in split_into_bubbles(rendered_reply_text)]
        elapsed = asyncio.get_running_loop().time() - reply_started
        remaining_delay = first_reply_delay_seconds - elapsed
        if remaining_delay > 0:
            await update.effective_chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(remaining_delay)
        for i, (bubble_text, bubble_entities) in enumerate(bubbles):
            if len(bubble_text) > MAX_TELEGRAM_LENGTH and not bubble_entities:
                bubble_text = bubble_text[: MAX_TELEGRAM_LENGTH - 1] + "\u2026"
            if i > 0:
                await update.effective_chat.send_action(ChatAction.TYPING)
                # Typing speed ~3-5 chars/sec for Chinese; add randomness
                delay = min(3.0 + len(bubble_text) * 0.08, 15.0) + random.uniform(-1.5, 2.0)
                await asyncio.sleep(max(delay, 3.0))
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
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
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
