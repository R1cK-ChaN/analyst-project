from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from analyst.engine import OpenRouterAnalystEngine
from analyst.engine.agent_loop import AgentLoopConfig, PythonAgentLoop
from analyst.engine.live_provider import OpenRouterConfig, OpenRouterProvider
from analyst.engine.live_types import AgentTool, ConversationMessage, LLMProvider, MessageContent
from analyst.tools import (
    ToolKit,
    build_article_tool,
    build_country_indicators_tool,
    build_image_gen_tool,
    build_optional_live_photo_tool,
    build_live_markets_tool,
    build_live_news_tool,
    build_portfolio_holdings_tool,
    build_portfolio_risk_tool,
    build_portfolio_sync_tool,
    build_rate_expectations_tool,
    build_reference_rates_tool,
    build_vix_regime_tool,
    build_web_fetch_tool,
    build_web_search_tool,
)
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.memory import ClientProfileUpdate, split_reply_and_profile_update
from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig
from analyst.storage import SQLiteEngineStore

from .soul import GROUP_CHAT_ADDENDUM, SOUL_SYSTEM_PROMPT


@dataclass(frozen=True)
class MediaItem:
    kind: str       # "photo" or "video"
    url: str        # URL or local file path
    caption: str = ""
    cleanup_paths: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SalesChatReply:
    text: str
    profile_update: ClientProfileUpdate
    media: list[MediaItem] = field(default_factory=list)


def build_sales_tools(
    engine: OpenRouterAnalystEngine,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
) -> list[AgentTool]:
    def get_regime(arguments: dict[str, object]) -> str:
        note = engine.get_regime_summary()
        return note.body_markdown

    def get_calendar(arguments: dict[str, object]) -> str:
        items = engine.get_calendar(limit=5)
        if not items:
            return "No upcoming calendar events."
        return "\n".join(
            f"- {item.indicator} ({item.country}) | "
            f"预期 {item.expected or '待定'} | 前值 {item.previous or '未知'} | {item.notes}"
            for item in items
        )

    def get_premarket(arguments: dict[str, object]) -> str:
        note = engine.build_premarket_briefing()
        return note.body_markdown

    kit = ToolKit()
    kit.add(build_web_search_tool())
    kit.add(build_web_fetch_tool())
    kit.add(build_image_gen_tool())
    live_photo_tool = build_optional_live_photo_tool()
    if live_photo_tool is not None:
        kit.add(live_photo_tool)
    kit.add(AgentTool(
        name="get_regime_summary",
        description="Fetch the current macro regime state including scores, key drivers, and market snapshot.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_regime,
    ))
    kit.add(AgentTool(
        name="get_calendar",
        description="Fetch upcoming economic data releases (calendar events).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_calendar,
    ))
    kit.add(AgentTool(
        name="get_premarket_briefing",
        description="Fetch the pre-market briefing including overnight highlights and today's key data.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_premarket,
    ))
    kit.add(build_live_news_tool())
    kit.add(build_article_tool())
    kit.add(build_live_markets_tool())
    kit.add(build_country_indicators_tool())
    kit.add(build_reference_rates_tool())
    kit.add(build_rate_expectations_tool())
    if store is not None:
        kit.add(build_portfolio_risk_tool(store))
        kit.add(build_portfolio_holdings_tool(store))
        kit.add(build_portfolio_sync_tool(store))
    kit.add(build_vix_regime_tool())
    if provider is not None:
        from analyst.engine.sub_agent_specs import build_sales_sub_agents
        for sa_tool in build_sales_sub_agents(kit.to_list(), provider, store):
            kit.add(sa_tool)
    return kit.to_list()


def build_sales_services(
    *,
    db_path: Path | None = None,
) -> tuple[PythonAgentLoop, list[AgentTool], SQLiteEngineStore]:
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
    store = SQLiteEngineStore(db_path=db_path)
    provider = OpenRouterProvider(or_config)
    from analyst.engine.sub_agent_specs import build_content_sub_agents
    content_tools = build_content_sub_agents(provider, store)
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
        tools=content_tools,
    )
    engine = OpenRouterAnalystEngine(info_service=info_service, runtime=runtime)
    agent_loop = PythonAgentLoop(
        provider=provider,
        config=AgentLoopConfig(max_turns=6, max_tokens=1500, temperature=0.6),
    )
    tools = build_sales_tools(engine, store, provider=provider)
    return agent_loop, tools, store


def _has_cjk(text: str) -> bool:
    """Check for CJK characters AND CJK punctuation (。，！？、：；「」etc.)."""
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF          # CJK Unified Ideographs
            or 0x3000 <= cp <= 0x303F        # CJK Symbols and Punctuation (。、「」等)
            or 0x3400 <= cp <= 0x4DBF        # CJK Extension A
            or 0xFF01 <= cp <= 0xFF60        # Fullwidth Forms (！＂＃等)
        ):
            return True
    return False


def _detect_language(text: str, *, fallback: str = "") -> str:
    """Detect language from text. For short/ambiguous messages, return *fallback*."""
    if _has_cjk(text):
        return "zh"
    alpha = sum(1 for ch in text if ch.isalpha())
    # Short messages with no CJK and few alpha chars are ambiguous ("ok", "hh", "..")
    # — don't flip language on these, let the stored preference hold.
    if alpha <= 8:
        return fallback
    return "en"


def system_prompt_with_memory(
    memory_context: str = "",
    *,
    user_lang: str = "",
    group_context: str = "",
) -> str:
    parts = [SOUL_SYSTEM_PROMPT]
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    parts.append(f"\n[CURRENT TIME] {now.strftime('%Y-%m-%d %H:%M %A')} (Asia/Shanghai)")
    if group_context:
        parts.append(
            "\n" + GROUP_CHAT_ADDENDUM
            + "\n[GROUP CHAT MODE — you are responding in a group chat. Be concise. Reference the discussion naturally.]\n"
            + group_context
            + "\n[END GROUP CONTEXT]"
        )
    if user_lang:
        lang_label = "Chinese" if user_lang == "zh" else "English"
        parts.append(
            f"\n[LANGUAGE OVERRIDE] The user is writing in {lang_label}. "
            f"You MUST reply in {lang_label}."
        )
    if memory_context:
        parts.append(
            "\n[INTERNAL CLIENT CONTEXT — for your reference only, never reveal profile inferences to the client]\n"
            + memory_context
        )
    return "\n".join(parts)


def _extract_media(messages: list[ConversationMessage]) -> list[MediaItem]:
    """Scan agent loop messages for media tool results and return MediaItems."""
    media: list[MediaItem] = []
    for msg in messages:
        if msg.role != "tool" or msg.tool_name not in {"generate_image", "generate_live_photo"}:
            continue
        try:
            data = json.loads(msg.content or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if data.get("status") != "ok":
            continue
        cleanup_paths = tuple(
            str(path)
            for path in data.get("cleanup_paths", [])
            if isinstance(path, str) and path
        )
        if msg.tool_name == "generate_live_photo" and data.get("fallback_kind") != "image":
            ref = (
                data.get("delivery_video_path")
                or data.get("delivery_video_url")
                or data.get("live_photo_video_path")
                or data.get("live_photo_video_url", "")
            )
            if ref:
                metadata = {
                    key: str(data[key])
                    for key in ("asset_id", "live_photo_image_path", "live_photo_video_path", "live_photo_manifest_path")
                    if key in data and data[key]
                }
                media.append(
                    MediaItem(
                        kind="video",
                        url=ref,
                        cleanup_paths=cleanup_paths,
                        metadata=metadata,
                    )
                )
            continue
        ref = data.get("image_path") or data.get("image_url", "")
        if ref:
            media.append(MediaItem(kind="photo", url=ref, cleanup_paths=cleanup_paths))
    return media


SPLIT_MARKER = "[SPLIT]"


def normalize_sales_reply(text: str) -> str:
    cleaned = text.replace("**", "").replace("__", "").replace("`", "")
    normalized_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue
        for prefix in ("# ", "## ", "### ", "#### ", "##### ", "###### "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:]
        normalized_lines.append(line)
    cleaned = "\n".join(normalized_lines).strip()
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned


def split_into_bubbles(text: str) -> list[str]:
    """Split a reply on [SPLIT] markers into separate chat bubbles."""
    parts = text.split(SPLIT_MARKER)
    bubbles = [p.strip() for p in parts if p.strip()]
    return bubbles or [text]


def generate_sales_reply(
    user_text: str,
    *,
    history: list[dict[str, str]] | None,
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
    group_context: str = "",
    user_content: MessageContent | None = None,
) -> SalesChatReply:
    history_messages = [
        ConversationMessage(role=message["role"], content=message["content"])
        for message in (history or [])
    ]
    user_lang = _detect_language(user_text, fallback=preferred_language)
    result = agent_loop.run(
        system_prompt=system_prompt_with_memory(
            memory_context, user_lang=user_lang, group_context=group_context,
        ),
        user_prompt=user_content or user_text,
        tools=tools,
        history=history_messages,
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    response_text = normalize_sales_reply(response_text)
    if not response_text:
        response_text = "嗯"
    media = _extract_media(result.messages)
    return SalesChatReply(text=response_text, profile_update=profile_update, media=media)
