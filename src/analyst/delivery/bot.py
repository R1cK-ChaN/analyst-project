"""Telegram bot entry-point for the Analyst platform.

Uses python-telegram-bot (v20+) async API.
Reads ANALYST_TELEGRAM_TOKEN from the environment.

All user messages are routed through a persona-driven agent loop (陈襄).
The bot hydrates structured sales memory for each client/thread and records
the interaction after every reply.

Commands
--------
/start      - persona greeting
/regime     - current macro regime summary
/calendar   - upcoming data releases
/premarket  - pre-market briefing
/help       - explain capabilities
"""

from __future__ import annotations

import asyncio
import base64
from io import BytesIO
import logging
import os
import random
import re
import shutil
import sys
import tempfile
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
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Bootstrap the analyst package so we can import from src/
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from analyst.engine.agent_loop import PythonAgentLoop  # noqa: E402
from analyst.engine.live_provider import OpenRouterConfig  # noqa: E402
from analyst.engine.live_types import AgentTool  # noqa: E402
from analyst.env import get_env_value  # noqa: E402
from analyst.memory import (  # noqa: E402
    ClientProfileUpdate,
    build_chat_context,
    build_sales_context,
    record_chat_interaction,
    record_sales_interaction,
)
from analyst.storage import SQLiteEngineStore  # noqa: E402
from analyst.tools._request_context import RequestImageInput, bind_request_image  # noqa: E402

from .sales_chat import (  # noqa: E402
    ChatPersonaMode,
    MediaItem,
    SalesChatReply,
    build_chat_services,
    generate_chat_reply,
    resolve_chat_persona_mode,
)

logger = logging.getLogger(__name__)

MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_TURNS = 20
MAX_GROUP_CONTEXT_MESSAGES = 50
MAX_GROUP_CONTEXT_CHARS = 1500
MANAGED_MEDIA_PREFIXES = (
    "analyst_gen_",
    "analyst_live_",
)
MAX_INBOUND_IMAGE_EDGE = 1536


# ---------------------------------------------------------------------------
# Group chat detection helpers
# ---------------------------------------------------------------------------

def _is_group_chat(update: Update) -> bool:
    """Check if the message is from a group or supergroup chat."""
    if update.effective_chat is None:
        return False
    return update.effective_chat.type in ("group", "supergroup")


def _is_bot_mentioned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if the bot is @mentioned in the message entities."""
    message = update.effective_message
    if message is None:
        return False
    bot_username = (context.bot.username or "").lower()
    bot_id = context.bot.id
    entity_maps = [
        message.parse_entities(types=[MessageEntity.MENTION, MessageEntity.TEXT_MENTION]),
    ]
    caption = getattr(message, "caption", None)
    if isinstance(caption, str):
        entity_maps.append(
            message.parse_caption_entities(types=[MessageEntity.MENTION, MessageEntity.TEXT_MENTION])
        )
    for entity_map in entity_maps:
        for entity, text in entity_map.items():
            if entity.type == MessageEntity.MENTION:
                if text.lstrip("@").lower() == bot_username:
                    return True
            elif entity.type == MessageEntity.TEXT_MENTION:
                if entity.user and entity.user.id == bot_id:
                    return True
    return False


def _is_reply_to_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if the message is a reply to one of the bot's own messages."""
    message = update.effective_message
    if message is None or message.reply_to_message is None:
        return False
    reply_from = message.reply_to_message.from_user
    return reply_from is not None and reply_from.id == context.bot.id


def _should_reply_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the bot should reply in a group chat (mentioned or replied-to)."""
    return _is_bot_mentioned(update, context) or _is_reply_to_bot(update, context)


def _extract_reply_context(update: Update) -> str | None:
    """Extract text from a replied-to message, if any."""
    message = update.effective_message
    if message is None or message.reply_to_message is None:
        return None
    reply_msg = message.reply_to_message
    # Prefer quote text if available (partial quote), fall back to full message
    quote = getattr(reply_msg, "quote", None)
    if quote and getattr(quote, "text", None):
        return quote.text
    return reply_msg.text or reply_msg.caption  # may be None for non-text messages


def _strip_bot_mention(text: str, bot_username: str) -> str:
    """Remove @botusername from text and clean up whitespace."""
    pattern = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
    return pattern.sub("", text).strip()


def _is_managed_generated_media(path: str) -> bool:
    """Only delete temp files created by the image generation tool."""
    temp_dir = os.path.abspath(tempfile.gettempdir())
    abs_path = os.path.abspath(path)
    return (
        os.path.dirname(abs_path) == temp_dir
        and os.path.basename(abs_path).startswith(MANAGED_MEDIA_PREFIXES)
    )


def _cleanup_generated_media(path: str) -> None:
    if not _is_managed_generated_media(path):
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
            return
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Failed to remove generated media file: %s", path)


def _get_user_display_name(update: Update) -> str:
    """Return the sender's first name, or a fallback."""
    user = update.effective_user
    if user and user.first_name:
        return user.first_name
    return "User"


def _extract_message_text(message: Any) -> str:
    return str(message.text or message.caption or "").strip()


def _summarize_user_message(text: str, *, has_image: bool) -> str:
    if has_image and text:
        return f"{text}\n[Image attached]"
    if has_image:
        return "[Image attached]"
    return text


def _render_image_instruction(text: str) -> str:
    base = text.strip() or "The user sent an image without caption. Analyze it and respond naturally."
    return (
        f"{base}\n\n"
        "[The user attached an image. You can inspect it directly. "
        "If they ask for a variation or edit of the attached image, call generate_image with "
        "use_attached_image=true. If they ask to animate the attached image, call "
        "generate_live_photo with use_attached_image=true.]"
    )


def _encode_image_data_uri(raw_bytes: bytes, mime_type: str) -> RequestImageInput:
    normalized_mime_type = mime_type or "image/jpeg"
    payload = raw_bytes
    try:
        with Image.open(BytesIO(raw_bytes)) as source_image:
            image = ImageOps.exif_transpose(source_image)
            if image.mode not in {"RGB", "L"}:
                alpha_image = image.convert("RGBA")
                background = Image.new("RGBA", alpha_image.size, (255, 255, 255, 255))
                background.alpha_composite(alpha_image)
                image = background.convert("RGB")
            else:
                image = image.convert("RGB")
            longest_edge = max(image.size)
            if longest_edge > MAX_INBOUND_IMAGE_EDGE:
                scale = MAX_INBOUND_IMAGE_EDGE / float(longest_edge)
                image = image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            payload = buffer.getvalue()
            normalized_mime_type = "image/jpeg"
    except Exception:
        logger.warning("Failed to normalize inbound image; falling back to original bytes.")
    encoded = base64.b64encode(payload).decode("ascii")
    return RequestImageInput(data_uri=f"data:{normalized_mime_type};base64,{encoded}", mime_type=normalized_mime_type)


async def _extract_attached_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> RequestImageInput | None:
    message = update.effective_message
    if message is None:
        return None
    file_id = ""
    mime_type = "image/jpeg"
    filename = ""
    photo_items = getattr(message, "photo", None)
    if isinstance(photo_items, (list, tuple)) and photo_items:
        photo = photo_items[-1]
        file_id = photo.file_id
        filename = f"{file_id}.jpg"
    else:
        document = getattr(message, "document", None)
        mime_type = getattr(document, "mime_type", "") if document is not None else ""
        if not mime_type.startswith("image/"):
            return None
        file_id = document.file_id
        filename = document.file_name or f"{file_id}.jpg"
    if not file_id:
        return None

    telegram_file = await context.bot.get_file(file_id)
    raw_bytes = bytes(await telegram_file.download_as_bytearray())
    request_image = _encode_image_data_uri(raw_bytes, mime_type)
    return RequestImageInput(
        data_uri=request_image.data_uri,
        mime_type=request_image.mime_type,
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Group context buffer helpers
# ---------------------------------------------------------------------------

def _get_group_buffer(
    context: ContextTypes.DEFAULT_TYPE, thread_id: str,
) -> list[dict[str, str]]:
    """Return the group message buffer for a given thread."""
    if "group_buffers" not in context.chat_data:
        context.chat_data["group_buffers"] = {}
    buffers = context.chat_data["group_buffers"]
    if thread_id not in buffers:
        buffers[thread_id] = []
    return buffers[thread_id]


def _append_group_buffer(
    context: ContextTypes.DEFAULT_TYPE,
    thread_id: str,
    name: str,
    text: str,
    role: str = "user",
) -> None:
    """Append a message to the group buffer and trim to max size."""
    buf = _get_group_buffer(context, thread_id)
    buf.append({"name": name, "text": text, "role": role})
    if len(buf) > MAX_GROUP_CONTEXT_MESSAGES:
        del buf[: len(buf) - MAX_GROUP_CONTEXT_MESSAGES]


def _render_group_context(context: ContextTypes.DEFAULT_TYPE, thread_id: str) -> str:
    """Render recent group messages as 'name: text' lines within char budget."""
    buf = _get_group_buffer(context, thread_id)
    lines: list[str] = []
    total = 0
    for msg in reversed(buf):
        line = f"{msg['name']}: {msg['text']}"
        if total + len(line) + 1 > MAX_GROUP_CONTEXT_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    lines.reverse()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

def _get_history(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    is_group: bool = False,
    thread_id: str = "main",
) -> list[dict[str, str]]:
    if is_group:
        if "agent_history" not in context.chat_data:
            context.chat_data["agent_history"] = {}
        histories = context.chat_data["agent_history"]
        if thread_id not in histories:
            histories[thread_id] = []
        return histories[thread_id]
    if "history" not in context.user_data:
        context.user_data["history"] = []
    return context.user_data["history"]


def _append_history(
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    content: str,
    *,
    is_group: bool = False,
    thread_id: str = "main",
) -> None:
    history = _get_history(context, is_group=is_group, thread_id=thread_id)
    history.append({"role": role, "content": content})
    max_messages = MAX_HISTORY_TURNS * 2
    if len(history) > max_messages:
        del history[: len(history) - max_messages]


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Core agent chat function
# ---------------------------------------------------------------------------

async def _chat_reply(
    user_text: str,
    context: ContextTypes.DEFAULT_TYPE,
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
    group_context: str = "",
    is_group: bool = False,
    thread_id: str = "main",
    user_content: Any | None = None,
    history_text: str | None = None,
    attached_image: RequestImageInput | None = None,
    persona_mode: str | ChatPersonaMode = ChatPersonaMode.SALES,
) -> SalesChatReply:
    """Send user_text through the agent loop with persona, history, tools, and sales context."""
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
                persona_mode=persona_mode,
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

    return SalesChatReply(
        text=response_text,
        profile_update=profile_update,
        media=media,
        tool_audit=tool_audit,
    )


# ---------------------------------------------------------------------------
# Service wiring
# ---------------------------------------------------------------------------

def _resolve_runtime_persona_mode() -> ChatPersonaMode:
    return resolve_chat_persona_mode(
        get_env_value("ANALYST_CHAT_PERSONA_MODE", default=ChatPersonaMode.SALES.value)
    )


def _build_services() -> tuple[PythonAgentLoop, list[AgentTool], SQLiteEngineStore, ChatPersonaMode]:
    """Wire up the agent loop, tools, memory store, and active chat persona."""
    persona_mode = _resolve_runtime_persona_mode()
    agent_loop, tools, store = build_chat_services(persona_mode=persona_mode)
    return agent_loop, tools, store, persona_mode


# ---------------------------------------------------------------------------
# Handler factories
# ---------------------------------------------------------------------------

def _make_start_handler(
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    *,
    persona_mode: ChatPersonaMode = ChatPersonaMode.SALES,
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
            persona_mode=persona_mode,
        )
        await update.effective_message.reply_text(reply.text)

    return start


def _make_help_handler(
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    *,
    persona_mode: ChatPersonaMode = ChatPersonaMode.SALES,
):
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "(The user wants to know what you can help with. Explain naturally.)",
            context,
            agent_loop,
            tools,
            persona_mode=persona_mode,
        )
        await update.effective_message.reply_text(reply.text)

    return help_command


def _make_regime_handler(
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    *,
    persona_mode: ChatPersonaMode = ChatPersonaMode.SALES,
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
            persona_mode=persona_mode,
        )
        await update.effective_message.reply_text(reply.text)

    return regime


def _make_calendar_handler(
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    *,
    persona_mode: ChatPersonaMode = ChatPersonaMode.SALES,
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
            persona_mode=persona_mode,
        )
        await update.effective_message.reply_text(reply.text)

    return calendar


def _make_premarket_handler(
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    *,
    persona_mode: ChatPersonaMode = ChatPersonaMode.SALES,
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
            persona_mode=persona_mode,
        )
        await update.effective_message.reply_text(reply.text)

    return premarket


def _make_message_handler(
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    store: SQLiteEngineStore,
    *,
    persona_mode: ChatPersonaMode = ChatPersonaMode.SALES,
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

        in_group = _is_group_chat(update)

        reply_context = _extract_reply_context(update)
        history_user_text = _summarize_user_message(text, has_image=attached_image is not None)

        if in_group:
            sender_name = _get_user_display_name(update)
            _append_group_buffer(context, thread_id, sender_name, history_user_text)

            if not _should_reply_in_group(update, context):
                return

            bot_username = context.bot.username or ""
            text = _strip_bot_mention(text, bot_username)
            history_user_text = _summarize_user_message(text, has_image=attached_image is not None)
            if not text and attached_image is None:
                return

            group_context_str = _render_group_context(context, thread_id)
        else:
            group_context_str = ""

        # Build enriched text for LLM (includes reply context)
        base_llm_text = text or "The user sent an image without caption."
        if reply_context:
            llm_text = f'回复消息：\n"{reply_context}"\n\n用户说：\n{base_llm_text}'
        else:
            llm_text = base_llm_text
        user_content = (
            [
                {"type": "text", "text": _render_image_instruction(llm_text)},
                {"type": "image_url", "image_url": {"url": attached_image.data_uri}},
            ]
            if attached_image is not None
            else llm_text
        )

        await update.effective_chat.send_action(ChatAction.TYPING)
        if persona_mode is ChatPersonaMode.COMPANION:
            memory_context = build_chat_context(
                store=store,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                query=llm_text,
                persona_mode=persona_mode.value,
            )
        else:
            memory_context = build_sales_context(
                store=store,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                query=llm_text,
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
            persona_mode=persona_mode,
        )
        if persona_mode is ChatPersonaMode.COMPANION:
            record_chat_interaction(
                store=store,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                user_text=history_user_text,
                assistant_text=reply.text,
                assistant_profile_update=reply.profile_update,
                tool_audit=reply.tool_audit,
                persona_mode=persona_mode.value,
            )
        else:
            record_sales_interaction(
                store=store,
                client_id=user_id,
                channel_id=channel_id,
                thread_id=thread_id,
                user_text=history_user_text,
                assistant_text=reply.text,
                assistant_profile_update=reply.profile_update,
                tool_audit=reply.tool_audit,
            )
        from analyst.delivery.sales_chat import split_into_bubbles
        bubbles = split_into_bubbles(reply.text)
        for i, bubble in enumerate(bubbles):
            if i > 0:
                await update.effective_chat.send_action(ChatAction.TYPING)
                delay = min(0.5 + len(bubble) * 0.01, 2.5) + random.uniform(-0.3, 0.3)
                await asyncio.sleep(max(delay, 0.3))
            await update.effective_message.reply_text(bubble)

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

        if in_group:
            _append_group_buffer(context, thread_id, "陈襄", reply.text, role="assistant")

    return handle_message


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    """Build and return a fully configured Telegram Application."""
    agent_loop, tools, store, persona_mode = _build_services()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _make_start_handler(agent_loop, tools, persona_mode=persona_mode)))
    app.add_handler(CommandHandler("help", _make_help_handler(agent_loop, tools, persona_mode=persona_mode)))
    if persona_mode is ChatPersonaMode.SALES:
        app.add_handler(CommandHandler("regime", _make_regime_handler(agent_loop, tools, persona_mode=persona_mode)))
        app.add_handler(CommandHandler("calendar", _make_calendar_handler(agent_loop, tools, persona_mode=persona_mode)))
        app.add_handler(CommandHandler("premarket", _make_premarket_handler(agent_loop, tools, persona_mode=persona_mode)))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND,
            _make_message_handler(agent_loop, tools, store, persona_mode=persona_mode),
        )
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
