from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from analyst.agents import RolePromptContext, get_role_spec
from analyst.engine import (
    AgentExecutor,
    AgentRunRequest,
    ExecutorBackend,
    OpenRouterAnalystEngine,
    build_agent_executor,
    coerce_agent_executor,
)
from analyst.engine.backends import ClaudeCodeProvider
from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.backends.factory import build_llm_provider_from_env
from analyst.engine.live_types import AgentTool, ConversationMessage, LLMProvider, MessageContent
from analyst.memory import (
    ClientProfileUpdate,
    CompanionReminderUpdate,
    CompanionScheduleUpdate,
    extract_embedded_reminder_update,
    extract_embedded_schedule_update,
    split_reply_and_profile_update,
)
from analyst.storage import SQLiteEngineStore

from .capabilities import (
    CLAUDE_CODE_NATIVE_TOOL_NAMES,
    COMPANION_SHARED_MCP_TOOL_NAMES,
    build_capability_tools,
)

COMPANION_MODEL_KEYS = (
    "ANALYST_COMPANION_OPENROUTER_MODEL",
    "ANALYST_TELEGRAM_OPENROUTER_MODEL",
    "ANALYST_OPENROUTER_MODEL",
    "LLM_MODEL",
)
COMPANION_DEFAULT_MODEL = "google/gemini-3-flash-preview"
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
    return build_capability_tools("companion")


def _build_configured_companion_tools(
    *,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
) -> list[AgentTool]:
    return build_capability_tools("companion", store=store, provider=provider)


def build_chat_tools(
    engine: OpenRouterAnalystEngine | Any | None = None,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
    *,
    persona_mode: str | ChatPersonaMode | None = None,
) -> list[AgentTool]:
    del engine, persona_mode
    return build_capability_tools("companion", store=store, provider=provider)


# Backward-compatible alias.
build_user_chat_tools = build_chat_tools


def build_chat_services(
    *,
    db_path: Path | None = None,
    persona_mode: str | ChatPersonaMode | None = None,
    provider_factory: Callable[..., LLMProvider] = build_llm_provider_from_env,
) -> tuple[AgentExecutor, list[AgentTool], SQLiteEngineStore]:
    del persona_mode
    return build_companion_services(db_path=db_path, provider_factory=provider_factory)


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
        mcp_tool_names=COMPANION_SHARED_MCP_TOOL_NAMES,
        mcp_db_path=store.db_path,
    )
    tools = _build_configured_companion_tools(store=store, provider=provider)
    return executor, tools, store


def build_user_chat_services(
    *,
    db_path: Path | None = None,
) -> tuple[AgentExecutor, list[AgentTool], SQLiteEngineStore]:
    return build_companion_services(db_path=db_path)


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
    engine_context: str = "",
    group_autonomous: bool = False,
) -> str:
    del persona_mode
    resolved_executor = coerce_agent_executor(executor) if executor is not None else None
    capability_overlay = _build_capability_overlay(
        executor=resolved_executor,
        tools=tools or [],
        native_tool_names=native_tool_names,
        mcp_tool_names=mcp_tool_names,
    )
    local_context = companion_local_context
    if engine_context:
        local_context = f"{local_context}\n\n{engine_context}".strip() if local_context else engine_context
    base_prompt = get_role_spec("companion").build_system_prompt(
        RolePromptContext(
            memory_context=memory_context,
            user_text=user_text,
            user_lang=user_lang,
            group_context=group_context,
            proactive_kind=proactive_kind,
            companion_local_context=local_context,
            group_autonomous=group_autonomous,
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
            "Market context, regime state, and calendar are pre-loaded above. "
            "Use native Claude web tools for open-web lookup. Use shared analyst tools for live data queries."
        )
    elif tool_names:
        lines.append("For time-sensitive market or news questions, call the appropriate live tool before answering.")
    return "\n".join(lines)


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


def _extract_media_from_events(events: list[dict[str, Any]]) -> list[MediaItem]:
    """Extract media from stream-json events (MCP tool call results in native mode)."""
    media: list[MediaItem] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_name = str(block.get("tool_use_name", "") or "")
            # MCP tool names are prefixed with server name (e.g. "analyst__generate_image")
            bare_name = tool_name.split("__", 1)[-1] if "__" in tool_name else tool_name
            if bare_name not in {"generate_image", "generate_live_photo"}:
                continue
            raw_content = block.get("content")
            text = ""
            if isinstance(raw_content, str):
                text = raw_content
            elif isinstance(raw_content, list):
                text = "".join(
                    str(item.get("text", ""))
                    for item in raw_content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            if not text:
                continue
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict) or data.get("status") != "ok":
                continue
            cleanup_paths = tuple(
                str(path)
                for path in data.get("cleanup_paths", [])
                if isinstance(path, str) and path
            )
            if bare_name == "generate_live_photo" and data.get("fallback_kind") != "image":
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


def _build_engine_context(engine: OpenRouterAnalystEngine | Any) -> str:
    sections: list[str] = []
    try:
        regime = engine.get_regime_summary()
        if regime and getattr(regime, "body_markdown", ""):
            sections.append(f"## Macro Regime\n{regime.body_markdown}")
    except Exception:
        pass
    try:
        calendar_items = engine.get_calendar(limit=5)
        if calendar_items:
            lines = [
                f"- {item.indicator} ({item.country}) | "
                f"预期 {item.expected or '待定'} | 前值 {item.previous or '未知'} | {item.notes}"
                for item in calendar_items
            ]
            sections.append("## Upcoming Calendar\n" + "\n".join(lines))
    except Exception:
        pass
    try:
        briefing = engine.build_premarket_briefing()
        if briefing and getattr(briefing, "body_markdown", ""):
            sections.append(f"## Pre-Market Briefing\n{briefing.body_markdown}")
    except Exception:
        pass
    return "\n\n".join(sections)


SPLIT_MARKER = "[SPLIT]"
IMAGE_PLACEHOLDER = "[IMAGE]"
VIDEO_PLACEHOLDER = "[VIDEO]"


def _strip_trailing_punctuation(text: str) -> str:
    """Strip trailing Chinese/English sentence-ending punctuation for casual chat feel.

    Real people rarely end every chat message with punctuation.  We strip
    trailing 。！…  but preserve ？ (questions feel odd without it) and keep
    the mark if the message is very short (≤4 chars — a bare emoji or word
    plus punctuation looks intentional).
    """
    import random as _rng
    stripped = text.rstrip()
    if not stripped or len(stripped) <= 4:
        return stripped
    # Only strip ~80% of the time so it doesn't feel robotic the other way
    if _rng.random() < 0.2:
        return stripped
    if stripped.endswith(("。", "！", "…", "!", ".")):
        return stripped[:-1].rstrip()
    # Trailing ellipsis patterns
    if stripped.endswith("..."):
        return stripped[:-3].rstrip() or stripped
    if stripped.endswith("……"):
        return stripped[:-2].rstrip() or stripped
    return stripped


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


_MAX_BUBBLE_LENGTH = 4096


def _split_oversized(text: str, limit: int = _MAX_BUBBLE_LENGTH) -> list[str]:
    """Split text exceeding *limit* at paragraph, line, or word boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = -1
        for sep in ("\n\n", "\n", " "):
            pos = remaining[:limit].rfind(sep)
            if pos > limit // 4:
                cut = pos
                break
        if cut <= 0:
            cut = limit
        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    return chunks or [text]


def split_into_bubbles(text: str) -> list[str]:
    """Split a reply on [SPLIT] markers into separate chat bubbles.

    Each resulting bubble is guaranteed to fit within the Telegram
    message-length limit (4 096 chars).  Oversized segments are further
    split at paragraph / line / word boundaries.  Trailing sentence-ending
    punctuation is randomly stripped for a casual chat feel.
    """
    parts = text.split(SPLIT_MARKER)
    bubbles: list[str] = []
    for p in parts:
        stripped = p.strip()
        if stripped:
            bubbles.extend(_split_oversized(stripped))
    # Strip trailing punctuation for casual chat feel
    bubbles = [_strip_trailing_punctuation(b) for b in bubbles]
    bubbles = [b for b in bubbles if b]
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
    if executor.backend is ExecutorBackend.CLAUDE_CODE:
        return TurnExecutionPlan(
            user_lang=user_lang,
            use_native_execution=True,
            active_tools=[],
            native_tool_names=native_tool_names or CLAUDE_CODE_NATIVE_TOOL_NAMES,
            mcp_tool_names=executor.mcp_tool_names,
        )
    prefer_direct_reply = _should_prefer_direct_visual_reply(
        user_text=user_text,
        user_content=user_content,
    )
    return TurnExecutionPlan(
        user_lang=user_lang,
        use_native_execution=prefer_direct_reply,
        active_tools=[] if prefer_direct_reply else tools,
        native_tool_names=native_tool_names,
        mcp_tool_names=(),
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


def _ends_with_question(text: str) -> bool:
    """Check if text ends with a question mark (Chinese or English)."""
    stripped = text.rstrip()
    return stripped.endswith("？") or stripped.endswith("?")


def _starts_with_haha(text: str) -> bool:
    """Check if text starts with a '哈哈' variant."""
    stripped = text.lstrip()
    return stripped.startswith("哈哈") or stripped.startswith("haha") or stripped.startswith("哈 ")


def _build_style_hints(history: list[dict[str, str]] | None) -> str:
    """Analyze recent assistant messages and build dynamic style correction hints."""
    if not history:
        return ""
    # Collect last 3 assistant messages
    recent_assistant: list[str] = []
    for msg in reversed(history or []):
        if msg["role"] == "assistant":
            recent_assistant.append(msg["content"])
            if len(recent_assistant) >= 3:
                break
    if not recent_assistant:
        return ""

    hints: list[str] = []

    # Question-ending suppression
    question_count = sum(1 for text in recent_assistant if _ends_with_question(text))
    if question_count >= 2:
        hints.append("这轮不要用问句结尾，说完就停。")

    # 哈哈 opener dedup
    haha_count = sum(1 for text in recent_assistant if _starts_with_haha(text))
    if haha_count >= 1:
        hints.append("这轮开头不要用哈哈，换个方式。")

    if not hints:
        return ""
    return "[STYLE CORRECTION] " + " ".join(hints)


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
    engine: OpenRouterAnalystEngine | Any | None = None,
    injection_detected: bool = False,
    group_autonomous: bool = False,
) -> ChatReply:
    del persona_mode
    executor = coerce_agent_executor(agent_loop)
    history_messages = [
        ConversationMessage(role=message["role"], content=message["content"])
        for message in (history or [])
    ]
    # Build dynamic style hints from recent history
    style_hints = _build_style_hints(history)
    effective_local_context = companion_local_context
    if style_hints:
        effective_local_context = (
            f"{companion_local_context}\n{style_hints}" if companion_local_context
            else style_hints
        )
    plan = resolve_turn_execution_plan(
        executor=executor,
        tools=tools,
        user_text=user_text,
        user_content=user_content,
        preferred_language=preferred_language,
        native_tool_names=native_tool_names,
    )
    engine_context = ""
    if engine is not None and executor.backend is ExecutorBackend.CLAUDE_CODE:
        engine_context = _build_engine_context(engine)
    system_prompt = system_prompt_with_memory(
        memory_context,
        user_text=user_text,
        user_lang=plan.user_lang,
        group_context=group_context,
        companion_local_context=effective_local_context,
        executor=executor,
        tools=plan.active_tools,
        native_tool_names=plan.native_tool_names,
        mcp_tool_names=plan.mcp_tool_names,
        engine_context=engine_context,
        group_autonomous=group_autonomous,
    )
    if injection_detected:
        from analyst.delivery.injection_scanner import build_injection_defense_block
        import re as _re
        _stage_match = _re.search(r"relationship_stage:\s*(\w+)", memory_context)
        _stage = _stage_match.group(1) if _stage_match else "stranger"
        system_prompt = system_prompt + "\n\n" + build_injection_defense_block(_stage)
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
    if not media:
        raw_events = result.raw_response.get("events", []) if isinstance(result.raw_response, dict) else []
        media = _extract_media_from_events(raw_events)
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


def _proactive_image_hint(kind: str) -> str:
    """Return image guidance to append to proactive instruction when image tool is available."""
    normalized = str(kind).strip().lower()
    hints: dict[str, str] = {
        "warm_up_share": "可以拍一张你看到的有趣东西配合分享，用back_camera模式。",
        "streak_save": "可以顺手拍一张你在做什么的照片。",
        "stage_milestone": "可以发一张selfie，带点开心的感觉。",
        "morning": "可以拍一张你现在的场景。",
        "evening": "可以拍一张你现在的场景。",
        "weekend": "可以拍一张你现在的场景。",
    }
    return hints.get(normalized, "")


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
    if normalized == "streak_save":
        return (
            "Send a light message now. The user has been chatting with you regularly but hasn't shown up today yet. "
            "Write like you naturally thought of them, not like you're tracking attendance. No guilt. Keep it brief."
        )
    if normalized == "emotional_concern":
        return (
            "Send a gentle check-in now. The user's mood has been getting worse recently. "
            "Write like a warm companion who noticed something is off, not like a therapist. Brief and soft."
        )
    if normalized == "stage_milestone":
        return (
            "Send a warm message now. You and the user have gotten noticeably closer recently. "
            "Express this naturally — maybe note that chatting with them has become a highlight, "
            "or that you feel more comfortable now. Brief, genuine, no over-the-top declarations."
        )
    if normalized == "warm_up_share":
        return (
            "【触达类型：随手分享】\n"
            "这次不要关心对方、不要问\"你怎么了\"、不要表达想念。\n"
            "像一个朋友随手分享一个有趣的小事：\n"
            "- 分享一首歌、一个有趣的发现、一个段子\n"
            "- 如果记忆中有相关信息，自然关联（比如用户养猫→\"今天看到一只猫…\"）\n"
            "- 语气轻松，不施加任何回复压力\n"
            "- 结尾不要用问号，不要问\"你觉得呢\""
        )
    return (
        "Send a gentle inactivity check-in now. The user has been quiet for a while. "
        "Write like a warm companion casually checking in, with no guilt or pressure. Keep it brief."
    )


def generate_proactive_companion_reply(
    *,
    kind: str,
    agent_loop: AgentExecutor | Any,
    tools: list[AgentTool] | None = None,
    memory_context: str = "",
    preferred_language: str = "",
    companion_local_context: str = "",
) -> ChatReply:
    executor = coerce_agent_executor(agent_loop)
    user_lang = preferred_language if preferred_language in {"zh", "en"} else ""
    active_tools = list(tools or [])
    image_hint = ""
    if active_tools:
        image_hint = _proactive_image_hint(kind)
    instruction = _proactive_companion_instruction(kind)
    if image_hint:
        instruction = f"{instruction}\n\n{image_hint}"
    result = executor.run_turn(
        AgentRunRequest(
            system_prompt=system_prompt_with_memory(
                memory_context,
                user_text="",
                user_lang=user_lang,
                proactive_kind=kind,
                companion_local_context=companion_local_context,
                executor=executor,
                tools=active_tools,
            ),
            user_prompt=instruction,
            tools=active_tools,
            history=[],
        )
    )
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    reminder_update = extract_embedded_reminder_update(result.final_text)
    schedule_update = extract_embedded_schedule_update(result.final_text)
    response_text = normalize_user_reply(response_text)
    if not response_text:
        response_text = "在想你今天过得怎么样。"
    media = _extract_media(result.messages) if active_tools else []
    if not media and active_tools:
        raw_events = result.raw_response.get("events", []) if isinstance(result.raw_response, dict) else []
        media = _extract_media_from_events(raw_events)
    tool_audit = _extract_tool_audit(result.messages) if active_tools else []
    return ChatReply(
        text=response_text,
        profile_update=profile_update,
        reminder_update=reminder_update,
        schedule_update=schedule_update,
        media=media,
        tool_audit=tool_audit,
    )


# Backward-compatible alias.
generate_user_reply = generate_chat_reply
