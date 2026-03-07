"""Telegram bot entry-point for the Analyst platform.

Uses python-telegram-bot (v20+) async API.
Reads ANALYST_TELEGRAM_TOKEN from the environment.

The bot is a thin delivery shell: it receives messages, routes them
through the existing AnalystIntegrationService (keyword detection ->
engine -> formatter), and replies with the formatted output.

Commands
--------
/start      - welcome message
/regime     - current macro regime summary
/calendar   - upcoming data releases
/premarket  - pre-market briefing
/help       - list available commands

Any other text is routed through the integration service (auto-detects
draft / meeting-prep / regime / calendar / Q&A).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from telegram import Update
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

from analyst.contracts import InteractionMode  # noqa: E402
from analyst.delivery.telegram import TelegramFormatter  # noqa: E402
from analyst.engine import OpenRouterAnalystEngine  # noqa: E402
from analyst.engine.live_provider import OpenRouterConfig  # noqa: E402
from analyst.env import get_env_value  # noqa: E402
from analyst.information import (  # noqa: E402
    AnalystInformationService,
    FileBackedInformationRepository,
)
from analyst.integration import AnalystIntegrationService  # noqa: E402
from analyst.memory import build_sales_context, record_sales_interaction  # noqa: E402
from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig  # noqa: E402
from analyst.storage import SQLiteEngineStore  # noqa: E402

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "你好！我是 Analyst 宏观助手。\n\n"
    "你可以直接用中文提问，我会自动识别你的意图：\n"
    "- 帮我写一段… → 客户消息初稿\n"
    "- 准备要点… → 客户沟通准备\n"
    "- 宏观状态 → 当前宏观框架\n"
    "- 今天有什么 → 数据日历\n"
    "- 其他问题 → 宏观问答\n\n"
    "也可以使用命令：\n"
    "/regime - 宏观状态\n"
    "/calendar - 数据日历\n"
    "/premarket - 早盘速递\n"
    "/help - 帮助"
)

HELP_TEXT = (
    "*Analyst 宏观助手 - 使用指南*\n\n"
    "*命令*\n"
    "/regime - 查看当前宏观状态评分\n"
    "/calendar - 查看近期数据日历\n"
    "/premarket - 查看早盘速递\n"
    "/help - 显示此帮助\n\n"
    "*自然语言*\n"
    "直接发送中文消息即可，系统自动识别意图。\n"
    "例如：「帮我写一段关于今晚非农数据的客户消息」"
)


def _build_services() -> tuple[
    OpenRouterAnalystEngine,
    TelegramFormatter,
    AnalystIntegrationService,
    SQLiteEngineStore,
]:
    """Wire up the analyst service stack."""
    repository = FileBackedInformationRepository()
    info_service = AnalystInformationService(repository)
    runtime = OpenRouterAgentRuntime(
        provider_config=OpenRouterConfig.from_env(
            model_keys=(
                "ANALYST_TELEGRAM_OPENROUTER_MODEL",
                "ANALYST_OPENROUTER_MODEL",
                "LLM_MODEL",
            ),
            default_model="google/gemini-3.1-flash-lite-preview",
        ),
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
    formatter = TelegramFormatter()
    integration = AnalystIntegrationService(engine=engine, formatter=formatter)
    store = SQLiteEngineStore()
    return engine, formatter, integration, store


# ---------------------------------------------------------------------------
# Handler factories — each returns an async callback for python-telegram-bot
# ---------------------------------------------------------------------------

def _make_start_handler(
    _engine: OpenRouterAnalystEngine,
    _formatter: TelegramFormatter,
    _integration: AnalystIntegrationService,
):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(WELCOME_TEXT)

    return start


def _make_help_handler(
    _engine: OpenRouterAnalystEngine,
    _formatter: TelegramFormatter,
    _integration: AnalystIntegrationService,
):
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(HELP_TEXT, parse_mode="Markdown")

    return help_command


def _make_regime_handler(
    engine: OpenRouterAnalystEngine,
    formatter: TelegramFormatter,
    _integration: AnalystIntegrationService,
):
    async def regime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        note = engine.get_regime_summary()
        msg = formatter.format_research_note(note, mode=InteractionMode.REGIME)
        await update.effective_message.reply_text(msg.plain_text)

    return regime


def _make_calendar_handler(
    engine: OpenRouterAnalystEngine,
    formatter: TelegramFormatter,
    _integration: AnalystIntegrationService,
):
    async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        msg = formatter.format_calendar(engine.get_calendar(limit=5))
        await update.effective_message.reply_text(msg.plain_text)

    return calendar


def _make_premarket_handler(
    engine: OpenRouterAnalystEngine,
    formatter: TelegramFormatter,
    _integration: AnalystIntegrationService,
):
    async def premarket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        note = engine.build_premarket_briefing()
        msg = formatter.format_research_note(note, mode=InteractionMode.PREMARKET)
        await update.effective_message.reply_text(msg.plain_text)

    return premarket


def _make_message_handler(
    _engine: OpenRouterAnalystEngine,
    _formatter: TelegramFormatter,
    integration: AnalystIntegrationService,
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
        memory_context = build_sales_context(
            store=store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            query=text,
        )
        reply = integration.handle_message(text, user_id=user_id, memory_context=memory_context)
        record_sales_interaction(
            store=store,
            client_id=user_id,
            channel_id=channel_id,
            thread_id=thread_id,
            user_text=text,
            assistant_text=reply.plain_text,
        )
        await update.effective_message.reply_text(reply.plain_text)

    return handle_message


def build_application(token: str) -> Application:
    """Build and return a fully configured Telegram Application.

    Does NOT call .run_polling(); the caller decides how to start it.
    """
    engine, formatter, integration, store = _build_services()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _make_start_handler(engine, formatter, integration)))
    app.add_handler(CommandHandler("help", _make_help_handler(engine, formatter, integration)))
    app.add_handler(CommandHandler("regime", _make_regime_handler(engine, formatter, integration)))
    app.add_handler(CommandHandler("calendar", _make_calendar_handler(engine, formatter, integration)))
    app.add_handler(CommandHandler("premarket", _make_premarket_handler(engine, formatter, integration)))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            _make_message_handler(engine, formatter, integration, store),
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

    logger.info("Starting Analyst Telegram bot …")
    app = build_application(token)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
