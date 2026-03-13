from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from analyst.agents import RoleDependencies, RolePromptContext, get_role_spec
from analyst.env import get_env_value
from analyst.engine import (
    AgentExecutor,
    AgentRunRequest,
    ExecutorBackend,
    OpenRouterAnalystEngine,
    build_agent_executor,
    coerce_agent_executor,
)
from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.backends.factory import build_llm_provider_from_env
from analyst.engine.live_types import AgentTool, ConversationMessage, LLMProvider, MessageContent
from analyst.mcp.shared_tools import BASE_SHARED_MCP_TOOL_NAMES
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
from analyst.memory import (
    ClientProfileUpdate,
    CompanionReminderUpdate,
    CompanionScheduleUpdate,
    extract_embedded_reminder_update,
    extract_embedded_schedule_update,
    split_reply_and_profile_update,
)
from analyst.storage import SQLiteEngineStore
from analyst.tools._live_calendar import build_live_calendar_tool
from analyst.information import AnalystInformationService, FileBackedInformationRepository

from .openrouter import OpenRouterAgentRuntime, OpenRouterRuntimeConfig

COMPANION_MODEL_KEYS = (
    "ANALYST_COMPANION_OPENROUTER_MODEL",
    "ANALYST_TELEGRAM_OPENROUTER_MODEL",
    "ANALYST_OPENROUTER_MODEL",
    "LLM_MODEL",
)
COMPANION_DEFAULT_MODEL = "google/gemini-3-flash-preview"
USER_MODEL_KEYS = (
    "ANALYST_TELEGRAM_OPENROUTER_MODEL",
    "ANALYST_OPENROUTER_MODEL",
    "LLM_MODEL",
)
USER_DEFAULT_MODEL = "google/gemini-3.1-flash-lite-preview"
CLAUDE_CODE_NATIVE_TOOL_NAMES = ("WebSearch", "WebFetch")
USER_SHARED_MCP_TOOL_NAMES = (
    *BASE_SHARED_MCP_TOOL_NAMES,
    "fetch_live_calendar",
    "search_news",
    "get_fed_communications",
    "get_indicator_history",
    "search_research_notes",
)
USER_CHAT_SHARED_MCP_TOOL_NAMES = (
    *USER_SHARED_MCP_TOOL_NAMES,
    "get_portfolio_risk",
    "get_portfolio_holdings",
)


class ChatPersonaMode(str, Enum):
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
    reminder_update: CompanionReminderUpdate = field(default_factory=CompanionReminderUpdate)
    schedule_update: CompanionScheduleUpdate = field(default_factory=CompanionScheduleUpdate)
    media: list[MediaItem] = field(default_factory=list)
    tool_audit: list[dict[str, Any]] = field(default_factory=list)


UserChatReply = ChatReply


@dataclass(frozen=True)
class TurnExecutionPlan:
    user_lang: str
    use_native_execution: bool
    active_tools: list[AgentTool]
    native_tool_names: tuple[str, ...]
    mcp_tool_names: tuple[str, ...]


def resolve_chat_persona_mode(value: str | ChatPersonaMode | None = None) -> ChatPersonaMode:
    del value
    return ChatPersonaMode.COMPANION


def build_companion_tools() -> list[AgentTool]:
    return get_role_spec("companion").build_tools(RoleDependencies())


def _build_configured_companion_tools(
    *,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
) -> list[AgentTool]:
    return get_role_spec("companion").build_tools(
        RoleDependencies(store=store, provider=provider),
    )


def build_chat_tools(
    engine: OpenRouterAnalystEngine | Any | None = None,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
    *,
    persona_mode: str | ChatPersonaMode | None = None,
) -> list[AgentTool]:
    normalized_mode = (
        persona_mode.value
        if isinstance(persona_mode, ChatPersonaMode)
        else str(persona_mode or "").strip().lower()
    )
    if normalized_mode == ChatPersonaMode.COMPANION.value or engine is None:
        return _build_configured_companion_tools(store=store, provider=provider)

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
    kit.add(
        AgentTool(
            name="get_regime_summary",
            description="Fetch the current macro regime state including scores, key drivers, and market snapshot.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_regime,
        )
    )
    kit.add(
        AgentTool(
            name="get_calendar",
            description="Fetch upcoming economic data releases from local cache. For live/real-time calendar data, prefer fetch_live_calendar instead.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_calendar,
        )
    )
    kit.add(
        AgentTool(
            name="get_premarket_briefing",
            description="Fetch the pre-market briefing including overnight highlights and today's key data.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_premarket,
        )
    )
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
        from analyst.engine.sub_agent_specs import build_user_sub_agents

        for sa_tool in build_user_sub_agents(kit.to_list(), provider, store):
            kit.add(sa_tool)
    return kit.to_list()


def build_user_chat_tools(
    engine: OpenRouterAnalystEngine | Any | None = None,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
    *,
    persona_mode: str | ChatPersonaMode | None = None,
) -> list[AgentTool]:
    return build_chat_tools(
        engine,
        store,
        provider,
        persona_mode=persona_mode,
    )


def build_chat_services(
    *,
    db_path: Path | None = None,
    persona_mode: str | ChatPersonaMode | None = None,
    provider_factory: Callable[..., LLMProvider] = build_llm_provider_from_env,
) -> tuple[AgentExecutor, list[AgentTool], SQLiteEngineStore]:
    del persona_mode
    store = SQLiteEngineStore(db_path=db_path)
    provider = provider_factory(
        model_keys=USER_MODEL_KEYS,
        default_model=USER_DEFAULT_MODEL,
    )
    executor = build_agent_executor(
        provider,
        config=AgentLoopConfig(max_turns=6, max_tokens=1500, temperature=0.6),
        mcp_tool_names=USER_CHAT_SHARED_MCP_TOOL_NAMES,
        mcp_db_path=store.db_path,
    )

    repository = FileBackedInformationRepository()
    info_service = AnalystInformationService(repository)
    from analyst.engine.sub_agent_specs import build_content_sub_agents

    content_tools = build_content_sub_agents(provider, store)
    runtime = OpenRouterAgentRuntime(
        provider=provider,
        config=OpenRouterRuntimeConfig(
            model_keys=USER_MODEL_KEYS,
            default_model=USER_DEFAULT_MODEL,
        ),
        tools=content_tools,
    )
    engine = OpenRouterAnalystEngine(info_service=info_service, runtime=runtime)
    tools = build_chat_tools(engine, store, provider=provider)
    return executor, tools, store


def build_companion_services(
    *,
    db_path: Path | None = None,
    provider_factory: Callable[..., LLMProvider] = build_llm_provider_from_env,
) -> tuple[AgentExecutor, list[AgentTool], SQLiteEngineStore]:
    store = SQLiteEngineStore(db_path=db_path)
    provider = provider_factory(
        model_keys=COMPANION_MODEL_KEYS,
        default_model=COMPANION_DEFAULT_MODEL,
    )
    executor = build_agent_executor(
        provider,
        config=AgentLoopConfig(max_turns=6, max_tokens=1500, temperature=0.6),
        mcp_tool_names=USER_SHARED_MCP_TOOL_NAMES,
        mcp_db_path=store.db_path,
    )
    tools = _build_configured_companion_tools(store=store, provider=provider)
    return executor, tools, store


def build_user_chat_services(
    *,
    db_path: Path | None = None,
) -> tuple[AgentExecutor, list[AgentTool], SQLiteEngineStore]:
    return build_chat_services(db_path=db_path)


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
    user_text: str = "",
    user_lang: str = "",
    group_context: str = "",
    proactive_kind: str = "",
    companion_local_context: str = "",
    persona_mode: str | ChatPersonaMode | None = None,
    executor: AgentExecutor | Any | None = None,
    tools: list[AgentTool] | None = None,
    native_tool_names: tuple[str, ...] = (),
    mcp_tool_names: tuple[str, ...] = (),
) -> str:
    del persona_mode
    resolved_executor = coerce_agent_executor(executor) if executor is not None else None
    capability_overlay = _build_capability_overlay(
        executor=resolved_executor,
        tools=tools or [],
        native_tool_names=native_tool_names,
        mcp_tool_names=mcp_tool_names,
    )
    base_prompt = get_role_spec("companion").build_system_prompt(
        RolePromptContext(
            memory_context=memory_context,
            user_text=user_text,
            user_lang=user_lang,
            group_context=group_context,
            proactive_kind=proactive_kind,
            companion_local_context=companion_local_context,
        )
    )
    return f"{base_prompt}\n\n{capability_overlay}".strip() if capability_overlay else base_prompt


def _build_capability_overlay(
    *,
    executor: AgentExecutor | None,
    tools: list[AgentTool],
    native_tool_names: tuple[str, ...],
    mcp_tool_names: tuple[str, ...],
) -> str:
    tool_names = tuple(
        str(getattr(tool, "name", ""))
        for tool in tools
        if str(getattr(tool, "name", "")).strip()
    )
    if not tool_names and not native_tool_names:
        return ""

    lines = [
        "[CURRENT CAPABILITIES]",
        "Use only the capabilities listed for this turn. Do not invent tool names or assume hidden tools exist.",
    ]
    if tool_names:
        lines.append("Host-managed tools available now: " + ", ".join(tool_names))
    if native_tool_names:
        native_label = "Claude native tools" if executor and executor.backend is ExecutorBackend.CLAUDE_CODE else "Native tools"
        lines.append(f"{native_label} available now: " + ", ".join(native_tool_names))
    if mcp_tool_names:
        lines.append("Shared analyst tools available now: " + ", ".join(mcp_tool_names))
    if executor and executor.backend is ExecutorBackend.CLAUDE_CODE and native_tool_names:
        lines.append(
            "Use native Claude web tools for open-web lookup. Use shared analyst tools for product-owned market, calendar, archive, or portfolio data."
        )
    elif tool_names:
        lines.append("For time-sensitive market or news questions, call the appropriate live tool before answering.")
    return "\n".join(lines)


def _claude_native_agent_enabled() -> bool:
    return get_env_value("ANALYST_CLAUDE_CODE_USE_NATIVE_AGENT", default="").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


def normalize_user_reply(text: str) -> str:
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


def _looks_like_back_camera_request(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(
        token in lowered
        for token in (
            "what are you eating",
            "what are you doing",
            "what are you up to",
            "lunch",
            "dinner",
            "coffee",
            "meal",
            "desk",
            "office",
            "walking",
            "walk",
            "吃什么",
            "午饭",
            "晚饭",
            "咖啡",
            "在干嘛",
            "在做什么",
            "现在在干嘛",
            "生活照",
            "日常照",
            "随手拍",
            "发张你现在",
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


def _infer_back_camera_scene_key(user_text: str) -> str:
    lowered = user_text.lower()
    scene_hints = (
        ("lunch_table_food", ("beef rice", "char siu", "roast pork", "roast meat", "吃什么", "午饭", "午餐", "dinner", "晚饭")),
        ("coffee_table_pov", ("coffee", "cafe", "咖啡")),
        ("desk_midday_pov", ("desk", "office", "work", "在干嘛", "working", "办公")),
        ("home_window_view", ("home", "window", "在家", "窗边", "room", "house")),
        ("street_walk_view", ("walk", "walking", "outside", "street", "散步", "路上", "外面")),
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
            arguments["prompt"] = (
                "quick front camera selfie at home near a window\n"
                "slightly off-center framing\n"
                "soft uneven daylight"
            )
        return arguments

    if _looks_like_back_camera_request(user_text):
        arguments = {"mode": "back_camera"}
        scene_key = _infer_back_camera_scene_key(user_text)
        if scene_key:
            arguments["back_camera_scene_key"] = scene_key
        else:
            arguments["prompt"] = (
                "back camera phone photo taken in the middle of a normal day\n"
                "imperfect framing\n"
                "slight tilt\n"
                "point of view shot"
            )
        return arguments

    arguments = {
        "prompt": user_text.strip() or "Create a photorealistic image that matches the user's request.",
    }
    if _has_attached_image(user_content):
        arguments["use_attached_image"] = True
    return arguments


def _requires_image_tool_path(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(
        token in lowered
        for token in (
            "animate",
            "animation",
            "live photo",
            "video",
            "edit this image",
            "edit this photo",
            "change this image",
            "change this photo",
            "make this image",
            "make this photo",
            "改图",
            "修图",
            "p图",
            "动起来",
            "视频",
            "改成",
            "生成一张",
            "generate image",
            "selfie",
            "自拍",
        )
    )


def _is_visual_analysis_request(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(
        token in lowered
        for token in (
            "what color is this image",
            "what color is this photo",
            "what do you see",
            "describe this image",
            "describe this photo",
            "answer one word",
            "what's in this image",
            "what is in this image",
            "图里是什么",
            "这张图是什么",
            "这张图里有什么",
            "这是什么颜色",
            "看这张图",
        )
    )


def _should_prefer_direct_visual_reply(
    *,
    user_text: str,
    user_content: MessageContent | None,
) -> bool:
    return (
        _has_attached_image(user_content)
        and not _requires_image_tool_path(user_text)
        and _is_visual_analysis_request(user_text)
    )


def _should_use_claude_native_agent(
    *,
    executor: AgentExecutor,
    user_text: str,
    user_content: MessageContent | None,
) -> bool:
    if executor.backend is not ExecutorBackend.CLAUDE_CODE:
        return False
    if not _claude_native_agent_enabled():
        return False
    if _requires_image_tool_path(user_text):
        return False
    if _has_attached_image(user_content) and not _is_visual_analysis_request(user_text):
        return False
    return True


def resolve_turn_execution_plan(
    *,
    executor: AgentExecutor,
    tools: list[AgentTool],
    user_text: str,
    user_content: MessageContent | None,
    preferred_language: str = "",
    native_tool_names: tuple[str, ...] = (),
) -> TurnExecutionPlan:
    user_lang = _detect_language(user_text, fallback=preferred_language)
    prefer_direct_reply = _should_prefer_direct_visual_reply(
        user_text=user_text,
        user_content=user_content,
    )
    use_native_agent = _should_use_claude_native_agent(
        executor=executor,
        user_text=user_text,
        user_content=user_content,
    )
    use_native_execution = prefer_direct_reply or use_native_agent
    native_tool_names_for_turn = CLAUDE_CODE_NATIVE_TOOL_NAMES if use_native_agent else ()
    return TurnExecutionPlan(
        user_lang=user_lang,
        use_native_execution=use_native_execution,
        active_tools=[] if use_native_execution else tools,
        native_tool_names=native_tool_names or native_tool_names_for_turn,
        mcp_tool_names=executor.mcp_tool_names if use_native_agent else (),
    )


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
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
    group_context: str = "",
    user_content: MessageContent | None = None,
    companion_local_context: str = "",
    persona_mode: str | ChatPersonaMode | None = None,
    native_tool_names: tuple[str, ...] = (),
) -> ChatReply:
    del persona_mode
    executor = coerce_agent_executor(agent_loop)
    history_messages = [
        ConversationMessage(role=message["role"], content=message["content"])
        for message in (history or [])
    ]
    plan = resolve_turn_execution_plan(
        executor=executor,
        tools=tools,
        user_text=user_text,
        user_content=user_content,
        preferred_language=preferred_language,
        native_tool_names=native_tool_names,
    )
    system_prompt = system_prompt_with_memory(
        memory_context,
        user_text=user_text,
        user_lang=plan.user_lang,
        group_context=group_context,
        companion_local_context=companion_local_context,
        executor=executor,
        tools=plan.active_tools,
        native_tool_names=plan.native_tool_names,
        mcp_tool_names=plan.mcp_tool_names,
    )
    result = executor.run_turn(
        AgentRunRequest(
            system_prompt=system_prompt,
            user_prompt=user_content or user_text,
            tools=plan.active_tools,
            history=history_messages,
            prefer_direct_response=plan.use_native_execution,
            native_tool_names=plan.native_tool_names,
            mcp_tool_names=plan.mcp_tool_names,
        )
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    reminder_update = extract_embedded_reminder_update(result.final_text)
    schedule_update = extract_embedded_schedule_update(result.final_text)
    contains_image_placeholder = IMAGE_PLACEHOLDER in response_text
    response_text = normalize_user_reply(response_text)
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
        reminder_update=reminder_update,
        schedule_update=schedule_update,
        media=media,
        tool_audit=tool_audit,
    )


def _proactive_companion_instruction(kind: str) -> str:
    normalized = str(kind).strip().lower()
    if normalized == "follow_up":
        return (
            "Send a gentle proactive follow-up message now. The user previously sounded emotionally strained. "
            "Write like a warm companion checking in naturally, not like a service follow-up. Keep it brief."
        )
    if normalized == "morning":
        return (
            "Send a light weekday morning greeting now. It should feel like a natural Singapore morning check-in "
            "before or during the Tanjong Pagar commute, not like a formal good-morning broadcast."
        )
    if normalized == "evening":
        return (
            "Send a light weekday evening check-in now. It should feel like someone who has wrapped up work in "
            "Singapore and is settling into the evening, not like office-hours talk."
        )
    if normalized == "weekend":
        return (
            "Send a light weekend daytime check-in now. It should feel relaxed and off-duty, with no market-open "
            "or workday framing."
        )
    return (
        "Send a gentle inactivity check-in now. The user has been quiet for a while. "
        "Write like a warm companion casually checking in, with no guilt or pressure. Keep it brief."
    )


def generate_proactive_companion_reply(
    *,
    kind: str,
    agent_loop: AgentExecutor | Any,
    memory_context: str = "",
    preferred_language: str = "",
    companion_local_context: str = "",
) -> ChatReply:
    executor = coerce_agent_executor(agent_loop)
    user_lang = preferred_language if preferred_language in {"zh", "en"} else ""
    result = executor.run_turn(
        AgentRunRequest(
            system_prompt=system_prompt_with_memory(
                memory_context,
                user_text="",
                user_lang=user_lang,
                proactive_kind=kind,
                companion_local_context=companion_local_context,
                executor=executor,
                tools=[],
            ),
            user_prompt=_proactive_companion_instruction(kind),
            tools=[],
            history=[],
        )
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    reminder_update = extract_embedded_reminder_update(result.final_text)
    schedule_update = extract_embedded_schedule_update(result.final_text)
    response_text = normalize_user_reply(response_text)
    if not response_text:
        response_text = "在想你今天过得怎么样。"
    return ChatReply(
        text=response_text,
        profile_update=profile_update,
        reminder_update=reminder_update,
        schedule_update=schedule_update,
        media=[],
        tool_audit=[],
    )


def generate_user_reply(
    user_text: str,
    *,
    history: list[dict[str, str]] | None,
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool],
    memory_context: str = "",
    preferred_language: str = "",
    group_context: str = "",
    user_content: MessageContent | None = None,
) -> UserChatReply:
    return generate_chat_reply(
        user_text,
        history=history,
        agent_loop=agent_loop,
        tools=tools,
        memory_context=memory_context,
        preferred_language=preferred_language,
        group_context=group_context,
        user_content=user_content,
    )
