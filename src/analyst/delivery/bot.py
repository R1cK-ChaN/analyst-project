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
import logging
import sys
from pathlib import Path

from telegram import Update
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

from analyst.engine.agent_loop import PythonAgentLoop  # noqa: E402
from analyst.engine.live_provider import OpenRouterConfig  # noqa: E402
from analyst.engine.live_types import AgentTool  # noqa: E402
from analyst.env import get_env_value  # noqa: E402
from analyst.memory import (  # noqa: E402
    ClientProfileUpdate,
    build_sales_context,
    record_sales_interaction,
)
from analyst.storage import SQLiteEngineStore  # noqa: E402

from .sales_chat import (  # noqa: E402
    SalesChatReply,
    build_sales_services,
    generate_sales_reply,
)

logger = logging.getLogger(__name__)

MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_TURNS = 20


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

def _get_history(context: ContextTypes.DEFAULT_TYPE) -> list[dict[str, str]]:
    if "history" not in context.user_data:
        context.user_data["history"] = []
    return context.user_data["history"]


def _append_history(context: ContextTypes.DEFAULT_TYPE, role: str, content: str) -> None:
    history = _get_history(context)
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
) -> SalesChatReply:
    """Send user_text through the agent loop with persona, history, tools, and sales context."""
    history = _get_history(context)

    try:
        result = await asyncio.to_thread(
            generate_sales_reply,
            user_text,
            history=history,
            agent_loop=agent_loop,
            tools=tools,
            memory_context=memory_context,
        )
        response_text = result.text
        profile_update = result.profile_update
    except Exception:
        logger.exception("Agent loop error")
        response_text = "抱歉，我这边出了点小状况，稍后再试试？"
        profile_update = ClientProfileUpdate()

    if len(response_text) > MAX_TELEGRAM_LENGTH:
        response_text = response_text[: MAX_TELEGRAM_LENGTH - 3] + "..."

    _append_history(context, "user", user_text)
    _append_history(context, "assistant", response_text)

    return SalesChatReply(text=response_text, profile_update=profile_update)


# ---------------------------------------------------------------------------
# Service wiring
# ---------------------------------------------------------------------------

def _build_services() -> tuple[PythonAgentLoop, list[AgentTool], SQLiteEngineStore]:
    """Wire up the agent loop, tools, and sales-memory store."""
    return build_sales_services()


# ---------------------------------------------------------------------------
# Handler factories
# ---------------------------------------------------------------------------

def _make_start_handler(agent_loop: PythonAgentLoop, tools: list[AgentTool]):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
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


def _make_help_handler(agent_loop: PythonAgentLoop, tools: list[AgentTool]):
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(
            "(The user wants to know what you can help with. Explain naturally.)",
            context,
            agent_loop,
            tools,
        )
        await update.effective_message.reply_text(reply.text)

    return help_command


def _make_regime_handler(agent_loop: PythonAgentLoop, tools: list[AgentTool]):
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


def _make_calendar_handler(agent_loop: PythonAgentLoop, tools: list[AgentTool]):
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


def _make_premarket_handler(agent_loop: PythonAgentLoop, tools: list[AgentTool]):
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
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    store: SQLiteEngineStore,
):
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None or update.effective_message.text is None:
            return
        user_id = str(update.effective_user.id) if update.effective_user else str(update.effective_chat.id)
        text = update.effective_message.text
        channel_id = f"telegram:{update.effective_chat.id}"
        topic_id = getattr(update.effective_message, "message_thread_id", None)
        thread_id = str(topic_id) if topic_id is not None else "main"

        await update.effective_chat.send_action(ChatAction.TYPING)
        memory_context = build_sales_context(
            store=store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            query=text,
        )
        reply = await _chat_reply(
            text,
            context,
            agent_loop,
            tools,
            memory_context=memory_context,
        )
        record_sales_interaction(
            store=store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            user_text=text,
            assistant_text=reply.text,
            assistant_profile_update=reply.profile_update,
        )
        await update.effective_message.reply_text(reply.text)

    return handle_message


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    """Build and return a fully configured Telegram Application."""
    agent_loop, tools, store = _build_services()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _make_start_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("help", _make_help_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("regime", _make_regime_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("calendar", _make_calendar_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("premarket", _make_premarket_handler(agent_loop, tools)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _make_message_handler(agent_loop, tools, store)))

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
