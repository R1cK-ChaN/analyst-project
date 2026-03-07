"""Telegram bot entry-point for the Analyst platform.

Uses python-telegram-bot (v20+) async API.
Reads ANALYST_TELEGRAM_TOKEN from the environment.

All user messages are routed through a persona-driven agent loop (陈襄).
The agent can autonomously decide when to fetch macro data, calendar events,
or briefings using tools backed by the analyst engine.

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
from typing import Any

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

from analyst.engine import OpenRouterAnalystEngine  # noqa: E402
from analyst.engine.agent_loop import AgentLoopConfig, PythonAgentLoop  # noqa: E402
from analyst.engine.live_provider import OpenRouterConfig, OpenRouterProvider  # noqa: E402
from analyst.engine.live_types import AgentTool, ConversationMessage  # noqa: E402
from analyst.env import get_env_value  # noqa: E402
from analyst.information import (  # noqa: E402
    AnalystInformationService,
    FileBackedInformationRepository,
)
from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig  # noqa: E402

from .soul import SOUL_SYSTEM_PROMPT  # noqa: E402

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

def _build_tools(engine: OpenRouterAnalystEngine) -> list[AgentTool]:
    """Create agent tools that wrap engine data-fetching methods."""

    def get_regime(arguments: dict[str, Any]) -> str:
        note = engine.get_regime_summary()
        return note.body_markdown

    def get_calendar(arguments: dict[str, Any]) -> str:
        items = engine.get_calendar(limit=5)
        if not items:
            return "No upcoming calendar events."
        return "\n".join(
            f"- {item.indicator} ({item.country}) | "
            f"预期 {item.expected or '待定'} | 前值 {item.previous or '未知'} | {item.notes}"
            for item in items
        )

    def get_premarket(arguments: dict[str, Any]) -> str:
        note = engine.build_premarket_briefing()
        return note.body_markdown

    return [
        AgentTool(
            name="get_regime_summary",
            description="Fetch the current macro regime state including scores, key drivers, and market snapshot.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_regime,
        ),
        AgentTool(
            name="get_calendar",
            description="Fetch upcoming economic data releases (calendar events).",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_calendar,
        ),
        AgentTool(
            name="get_premarket_briefing",
            description="Fetch the pre-market briefing including overnight highlights and today's key data.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_premarket,
        ),
    ]


# ---------------------------------------------------------------------------
# Core agent chat function
# ---------------------------------------------------------------------------

async def _chat_reply(
    user_text: str,
    context: ContextTypes.DEFAULT_TYPE,
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
) -> str:
    """Send user_text through the agent loop with persona, history, and tools."""
    history = _get_history(context)
    history_messages = [ConversationMessage(role=msg["role"], content=msg["content"]) for msg in history]

    try:
        result = await asyncio.to_thread(
            agent_loop.run,
            system_prompt=SOUL_SYSTEM_PROMPT,
            user_prompt=user_text,
            tools=tools,
            history=history_messages,
        )
        response_text = result.final_text
    except Exception:
        logger.exception("Agent loop error")
        response_text = "抱歉，我这边出了点小状况，稍后再试试？"

    _append_history(context, "user", user_text)
    _append_history(context, "assistant", response_text)

    if len(response_text) > MAX_TELEGRAM_LENGTH:
        response_text = response_text[: MAX_TELEGRAM_LENGTH - 3] + "..."

    return response_text


# ---------------------------------------------------------------------------
# Service wiring
# ---------------------------------------------------------------------------

def _build_services() -> tuple[PythonAgentLoop, list[AgentTool]]:
    """Wire up the agent loop and tools."""
    repository = FileBackedInformationRepository()
    info_service = AnalystInformationService(repository)
    or_config = OpenRouterConfig.from_env(
        model_keys=(
            "ANALYST_TELEGRAM_OPENROUTER_MODEL",
            "ANALYST_OPENROUTER_MODEL",
            "LLM_MODEL",
        ),
        default_model="google/gemini-3.1-flash-lite-preview",
    )
    runtime = OpenRouterAgentRuntime(
        provider_config=or_config,
        config=OpenRouterRuntimeConfig(
            model_keys=(
                "ANALYST_TELEGRAM_OPENROUTER_MODEL",
                "ANALYST_OPENROUTER_MODEL",
                "LLM_MODEL",
            ),
            default_model="google/gemini-3.1-flash-lite-preview",
        ),
    )
    engine = OpenRouterAnalystEngine(info_service=info_service, runtime=runtime)
    provider = OpenRouterProvider(or_config)
    agent_loop = PythonAgentLoop(
        provider=provider,
        config=AgentLoopConfig(max_turns=6, max_tokens=1500, temperature=0.6),
    )
    tools = _build_tools(engine)
    return agent_loop, tools


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
        await update.effective_message.reply_text(reply)

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
        await update.effective_message.reply_text(reply)

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
        await update.effective_message.reply_text(reply)

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
        await update.effective_message.reply_text(reply)

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
        await update.effective_message.reply_text(reply)

    return premarket


def _make_message_handler(agent_loop: PythonAgentLoop, tools: list[AgentTool]):
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None or update.effective_message.text is None:
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        reply = await _chat_reply(update.effective_message.text, context, agent_loop, tools)
        await update.effective_message.reply_text(reply)

    return handle_message


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    """Build and return a fully configured Telegram Application."""
    agent_loop, tools = _build_services()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _make_start_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("help", _make_help_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("regime", _make_regime_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("calendar", _make_calendar_handler(agent_loop, tools)))
    app.add_handler(CommandHandler("premarket", _make_premarket_handler(agent_loop, tools)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _make_message_handler(agent_loop, tools)))

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
