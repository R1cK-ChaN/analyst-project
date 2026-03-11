from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
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
    build_fed_comms_tool,
    build_image_gen_tool,
    build_indicator_history_tool,
    build_optional_live_photo_tool,
    build_live_markets_tool,
    build_live_news_tool,
    build_portfolio_holdings_tool,
    build_portfolio_risk_tool,
    build_portfolio_sync_tool,
    build_rate_expectations_tool,
    build_reference_rates_tool,
    build_research_search_tool,
    build_stored_news_tool,
    build_vix_regime_tool,
    build_web_fetch_tool,
    build_web_search_tool,
)
from analyst.tools._live_calendar import build_live_calendar_tool
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.memory import ClientProfileUpdate, split_reply_and_profile_update
from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig
from analyst.storage import SQLiteEngineStore

from .soul import GROUP_CHAT_ADDENDUM, get_persona_system_prompt


class ChatPersonaMode(str, Enum):
    SALES = "sales"
    COMPANION = "companion"


@dataclass(frozen=True)
class MediaItem:
    kind: str       # "photo" or "video"
    url: str        # URL or local file path
    caption: str = ""
    cleanup_paths: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatReply:
    text: str
    profile_update: ClientProfileUpdate
    media: list[MediaItem] = field(default_factory=list)
    tool_audit: list[dict[str, Any]] = field(default_factory=list)


SalesChatReply = ChatReply


def resolve_chat_persona_mode(value: str | ChatPersonaMode | None = None) -> ChatPersonaMode:
    if isinstance(value, ChatPersonaMode):
        return value
    lowered = str(value or ChatPersonaMode.SALES.value).strip().lower()
    if lowered == ChatPersonaMode.COMPANION.value:
        return ChatPersonaMode.COMPANION
    return ChatPersonaMode.SALES


def _build_companion_tools() -> list[AgentTool]:
    kit = ToolKit()
    kit.add(build_image_gen_tool())
    live_photo_tool = build_optional_live_photo_tool()
    if live_photo_tool is not None:
        kit.add(live_photo_tool)
    return kit.to_list()


def build_chat_tools(
    engine: OpenRouterAnalystEngine,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
    *,
    persona_mode: str | ChatPersonaMode = ChatPersonaMode.SALES,
) -> list[AgentTool]:
    resolved_mode = resolve_chat_persona_mode(persona_mode)
    if resolved_mode is ChatPersonaMode.COMPANION:
        return _build_companion_tools()

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
        description="Fetch upcoming economic data releases from local cache. For live/real-time calendar data, prefer fetch_live_calendar instead.",
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
        kit.add(build_live_calendar_tool(store))
        kit.add(build_portfolio_risk_tool(store))
        kit.add(build_portfolio_holdings_tool(store))
        kit.add(build_portfolio_sync_tool(store))
        kit.add(build_stored_news_tool(store))
        kit.add(build_fed_comms_tool(store))
        kit.add(build_indicator_history_tool(store))
        kit.add(build_research_search_tool(store))
    kit.add(build_vix_regime_tool())
    if provider is not None:
        from analyst.engine.sub_agent_specs import build_sales_sub_agents
        for sa_tool in build_sales_sub_agents(kit.to_list(), provider, store):
            kit.add(sa_tool)
    return kit.to_list()


def build_sales_tools(
    engine: OpenRouterAnalystEngine,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
) -> list[AgentTool]:
    return build_chat_tools(
        engine,
        store,
        provider,
        persona_mode=ChatPersonaMode.SALES,
    )


def build_chat_services(
    *,
    db_path: Path | None = None,
    persona_mode: str | ChatPersonaMode = ChatPersonaMode.SALES,
) -> tuple[PythonAgentLoop, list[AgentTool], SQLiteEngineStore]:
    resolved_mode = resolve_chat_persona_mode(persona_mode)
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
    agent_loop = PythonAgentLoop(
        provider=provider,
        config=AgentLoopConfig(max_turns=6, max_tokens=1500, temperature=0.6),
    )
    if resolved_mode is ChatPersonaMode.COMPANION:
        tools = _build_companion_tools()
        return agent_loop, tools, store

    repository = FileBackedInformationRepository()
    info_service = AnalystInformationService(repository)
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
    tools = build_chat_tools(engine, store, provider=provider, persona_mode=resolved_mode)
    return agent_loop, tools, store


def build_sales_services(
    *,
    db_path: Path | None = None,
) -> tuple[PythonAgentLoop, list[AgentTool], SQLiteEngineStore]:
    return build_chat_services(db_path=db_path, persona_mode=ChatPersonaMode.SALES)


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
    persona_mode: str | ChatPersonaMode = ChatPersonaMode.SALES,
) -> str:
    parts = [get_persona_system_prompt(resolve_chat_persona_mode(persona_mode).value)]
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
            "⚠ WARNING: sent_content below is PAST data (already delivered). It may be hours or days old. "
            "Do NOT treat it as current information. For ANY time-sensitive question (news, events, prices, "
            "data releases, \"最新/现在/今天\" queries), you MUST call a live tool first.\n"
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


def _extract_tool_audit(messages: list[ConversationMessage]) -> list[dict[str, Any]]:
    tool_calls: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tool_call in msg.tool_calls:
                tool_calls[tool_call.call_id] = {
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
            continue
        if msg.role != "tool":
            continue
        call_meta = tool_calls.get(msg.tool_call_id or "", {})
        tool_name = msg.tool_name or str(call_meta.get("tool_name", ""))
        payload: dict[str, Any] = {}
        try:
            raw_payload = json.loads(msg.content or "{}")
            if isinstance(raw_payload, dict):
                payload = raw_payload
        except (json.JSONDecodeError, TypeError):
            payload = {}
        entry: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_call_id": msg.tool_call_id or "",
            "arguments": call_meta.get("arguments", {}),
            "status": payload.get("status", ""),
        }
        for key in (
            "fallback_kind",
            "warning",
            "error",
            "image_path",
            "image_url",
            "delivery_video_path",
            "delivery_video_url",
            "mode",
            "scene_key",
            "scene_prompt",
        ):
            value = payload.get(key)
            if value:
                entry[key] = value
        audit.append(entry)
    return audit


SPLIT_MARKER = "[SPLIT]"
IMAGE_PLACEHOLDER = "[IMAGE]"
VIDEO_PLACEHOLDER = "[VIDEO]"


def normalize_sales_reply(text: str) -> str:
    cleaned = (
        text.replace("**", "")
        .replace("__", "")
        .replace("`", "")
        .replace(IMAGE_PLACEHOLDER, "")
        .replace(VIDEO_PLACEHOLDER, "")
    )
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


def _find_tool(tools: list[AgentTool], name: str) -> AgentTool | None:
    for tool in tools:
        if tool.name == name:
            return tool
    return None


def _has_attached_image(user_content: MessageContent | None) -> bool:
    if not isinstance(user_content, list):
        return False
    for item in user_content:
        if isinstance(item, dict) and item.get("type") == "image_url":
            return True
    return False


def _looks_like_selfie_request(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(
        token in lowered
        for token in (
            "自拍",
            "selfie",
            "my photo",
            "your photo",
            "your pic",
            "your selfie",
            "发张照片",
            "发你照片",
            "看看你",
            "看看自拍",
            "你长什么样",
        )
    )


def _infer_selfie_scene_key(user_text: str) -> str:
    lowered = user_text.lower()
    scene_hints = (
        ("coffee_shop", ("咖啡", "coffee", "cafe")),
        ("lazy_sunday_home", ("宅家", "在家", "home", "sofa", "couch")),
        ("night_walk", ("散步", "walk", "night street", "city light")),
        ("gym_mirror", ("健身", "gym", "mirror")),
        ("airport_waiting", ("机场", "airport", "gate", "boarding")),
        ("bedroom_late_night", ("卧室", "bedroom", "late night", "bed", "熬夜")),
        ("rainy_day_window", ("下雨", "rain", "window", "雨天")),
        ("weekend_street", ("周末", "street", "逛街", "outside")),
    )
    for scene_key, tokens in scene_hints:
        if any(token in lowered for token in tokens):
            return scene_key
    return ""


def _build_placeholder_image_arguments(
    user_text: str,
    *,
    user_content: MessageContent | None,
) -> dict[str, Any]:
    if _looks_like_selfie_request(user_text):
        arguments: dict[str, Any] = {"mode": "selfie"}
        scene_key = _infer_selfie_scene_key(user_text)
        if scene_key:
            arguments["scene_key"] = scene_key
        else:
            arguments["prompt"] = "casual home selfie near a window\nsoft daylight\nrelaxed friendly expression"
        return arguments

    arguments = {
        "prompt": user_text.strip() or "Create a photorealistic image that matches the user's request.",
    }
    if _has_attached_image(user_content):
        arguments["use_attached_image"] = True
    return arguments


def _repair_missing_image_media(
    *,
    response_text: str,
    user_text: str,
    user_content: MessageContent | None,
    tools: list[AgentTool],
) -> tuple[list[MediaItem], list[dict[str, Any]]]:
    if IMAGE_PLACEHOLDER not in response_text:
        return [], []

    image_tool = _find_tool(tools, "generate_image")
    if image_tool is None:
        return [], [{
            "tool_name": "generate_image",
            "tool_call_id": "",
            "arguments": {},
            "status": "error",
            "error": "generate_image tool unavailable for placeholder repair",
            "repair_kind": "placeholder_image",
        }]

    arguments = _build_placeholder_image_arguments(user_text, user_content=user_content)
    try:
        raw_result = image_tool.handler(arguments)
    except Exception as exc:  # pragma: no cover - defensive guard
        return [], [{
            "tool_name": "generate_image",
            "tool_call_id": "",
            "arguments": arguments,
            "status": "error",
            "error": str(exc),
            "repair_kind": "placeholder_image",
        }]

    if not isinstance(raw_result, dict):
        raw_result = {"status": "error", "error": "Invalid generate_image repair result."}

    media = _extract_media([
        ConversationMessage(
            role="tool",
            tool_name="generate_image",
            content=json.dumps(raw_result, ensure_ascii=False),
        )
    ])
    audit_entry: dict[str, Any] = {
        "tool_name": "generate_image",
        "tool_call_id": "",
        "arguments": arguments,
        "status": str(raw_result.get("status", "")),
        "repair_kind": "placeholder_image",
    }
    for key in (
        "fallback_kind",
        "warning",
        "error",
        "image_path",
        "image_url",
        "mode",
        "scene_key",
        "scene_prompt",
    ):
        value = raw_result.get(key)
        if value:
            audit_entry[key] = value
    return media, [audit_entry]


def generate_chat_reply(
    user_text: str,
    *,
    history: list[dict[str, str]] | None,
    agent_loop: PythonAgentLoop,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
    group_context: str = "",
    user_content: MessageContent | None = None,
    persona_mode: str | ChatPersonaMode = ChatPersonaMode.SALES,
) -> ChatReply:
    history_messages = [
        ConversationMessage(role=message["role"], content=message["content"])
        for message in (history or [])
    ]
    user_lang = _detect_language(user_text, fallback=preferred_language)
    result = agent_loop.run(
        system_prompt=system_prompt_with_memory(
            memory_context,
            user_lang=user_lang,
            group_context=group_context,
            persona_mode=persona_mode,
        ),
        user_prompt=user_content or user_text,
        tools=tools,
        history=history_messages,
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    contains_image_placeholder = IMAGE_PLACEHOLDER in response_text
    response_text = normalize_sales_reply(response_text)
    if not response_text:
        response_text = "嗯"
    media = _extract_media(result.messages)
    tool_audit = _extract_tool_audit(result.messages)
    if contains_image_placeholder and not media:
        repaired_media, repaired_audit = _repair_missing_image_media(
            response_text=result.final_text,
            user_text=user_text,
            user_content=user_content,
            tools=tools,
        )
        if repaired_media:
            media = repaired_media
        if repaired_audit:
            tool_audit = [*tool_audit, *repaired_audit]
    return ChatReply(
        text=response_text,
        profile_update=profile_update,
        media=media,
        tool_audit=tool_audit,
    )


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
    return generate_chat_reply(
        user_text,
        history=history,
        agent_loop=agent_loop,
        tools=tools,
        memory_context=memory_context,
        preferred_language=preferred_language,
        group_context=group_context,
        user_content=user_content,
        persona_mode=ChatPersonaMode.SALES,
    )
