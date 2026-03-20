from __future__ import annotations

import asyncio
import random
from typing import Any

from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from .bot_constants import MAX_HISTORY_TURNS, MAX_TELEGRAM_LENGTH

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

async def _send_bot_bubbles(bot: Any, *, chat_id: int, bubbles: list[str]) -> None:
    for i, bubble in enumerate(bubbles):
        if len(bubble) > MAX_TELEGRAM_LENGTH:
            bubble = bubble[: MAX_TELEGRAM_LENGTH - 1] + "\u2026"
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        if i > 0:
            delay = min(0.5 + len(bubble) * 0.01, 2.5) + random.uniform(-0.3, 0.3)
            await asyncio.sleep(max(delay, 0.3))
        await bot.send_message(chat_id=chat_id, text=bubble)

