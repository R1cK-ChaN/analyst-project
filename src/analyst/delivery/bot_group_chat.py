from __future__ import annotations

import re
from typing import Any

from telegram import MessageEntity, Update, User
from telegram.ext import ContextTypes

from .bot_constants import (
    GROUP_MEMBER_MENTION_RE,
    MAX_GROUP_CONTEXT_CHARS,
    MAX_GROUP_CONTEXT_MESSAGES,
)
from .user_chat import SPLIT_MARKER, split_into_bubbles

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

def _extract_reply_user_id(update: Update) -> str | None:
    """Return the user_id of the replied-to message author, if any."""
    message = update.effective_message
    if message is None or message.reply_to_message is None:
        return None
    from_user = message.reply_to_message.from_user
    if from_user is None:
        return None
    return str(from_user.id)


def _extract_mentioned_user_ids(update: Update) -> dict[str, str]:
    """Extract @-mentioned users from message entities.

    Returns {display_name_lower: str(user_id)} for TEXT_MENTION entities.
    """
    message = update.effective_message
    if message is None or not message.entities:
        return {}
    result: dict[str, str] = {}
    text = message.text or ""
    for entity in message.entities:
        if entity.type == MessageEntity.TEXT_MENTION and entity.user:
            name = text[entity.offset : entity.offset + entity.length].lstrip("@")
            result[name.strip().lower()] = str(entity.user.id)
    return result


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

def _get_user_display_name(update: Update) -> str:
    """Return the sender's first name, or a fallback."""
    user = update.effective_user
    if user and user.first_name:
        return user.first_name
    return "User"

def _extract_message_text(message: Any) -> str:
    return str(message.text or message.caption or "").strip()

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

def _normalize_group_member_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()

def _build_group_member_lookup(members: list[Any]) -> dict[str, tuple[str, int]]:
    lookup: dict[str, tuple[str, int]] = {}
    ambiguous: set[str] = set()
    for member in members:
        key = _normalize_group_member_name(getattr(member, "display_name", ""))
        raw_user_id = getattr(member, "user_id", "")
        if not key:
            continue
        try:
            user_id = int(str(raw_user_id))
        except (TypeError, ValueError):
            continue
        if key in ambiguous:
            continue
        existing = lookup.get(key)
        if existing is not None and existing[1] != user_id:
            ambiguous.add(key)
            lookup.pop(key, None)
            continue
        display_name = str(getattr(member, "display_name", "") or "").strip()
        lookup[key] = (display_name or str(raw_user_id), user_id)
    return lookup

def _render_group_mentions(text: str, members: list[Any]) -> tuple[str, list[MessageEntity]]:
    if "@[" not in text:
        return text, []
    lookup = _build_group_member_lookup(members)
    rendered_parts: list[str] = []
    entities: list[MessageEntity] = []
    cursor = 0
    rendered_length = 0
    for match in GROUP_MEMBER_MENTION_RE.finditer(text):
        literal = text[cursor:match.start()]
        rendered_parts.append(literal)
        rendered_length += len(literal)

        raw_name = re.sub(r"\s+", " ", match.group("name")).strip()
        mention_text = f"@{raw_name}" if raw_name else match.group(0)
        mention_meta = lookup.get(_normalize_group_member_name(raw_name))
        if mention_meta is not None:
            display_name, user_id = mention_meta
            mention_text = f"@{display_name}"
            entities.append(
                MessageEntity(
                    type=MessageEntity.TEXT_MENTION,
                    offset=rendered_length,
                    length=len(mention_text),
                    user=User(
                        id=user_id,
                        first_name=display_name or raw_name or "user",
                        is_bot=False,
                    ),
                )
            )
        rendered_parts.append(mention_text)
        rendered_length += len(mention_text)
        cursor = match.end()

    tail = text[cursor:]
    rendered_parts.append(tail)
    return "".join(rendered_parts), entities

def _render_group_bubbles_with_mentions(
    text: str,
    members: list[Any],
) -> tuple[str, list[tuple[str, list[MessageEntity]]]]:
    raw_bubbles = split_into_bubbles(text)
    rendered_bubbles = [_render_group_mentions(bubble, members) for bubble in raw_bubbles]
    rendered_text = SPLIT_MARKER.join(rendered for rendered, _ in rendered_bubbles)
    return rendered_text, rendered_bubbles

