from __future__ import annotations

import json
import logging
import re
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
    build_agent_executor,
    coerce_agent_executor,
)
from analyst.engine.executor import LegacyLoopExecutor
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

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class ReplyCandidate:
    slot_id: str
    prompt_hint: str
    reply: ChatReply
    score: float
    reasons: tuple[str, ...]


CandidateJudge = Callable[[list[ReplyCandidate]], int | None]


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
    engine: Any | None = None,
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


def _build_engine_context(engine: Any) -> str:
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


_QUESHI_REPLACEMENTS = ("嗯", "是", "对", "行", "")
"""Replacements when 确实 appears at the start of a message."""

_WRITTEN_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("有时候那种意外的走向，比你一开始预设的要自然得多", "有时候跑偏了反而更顺"),
    ("看来咱们的脑电波对上了", "看来咱们想到一块去了"),
    ("那种感觉就像被困在恒温箱里 连呼吸都觉得没劲", "这种地方待久了人会发闷"),
    ("连空气里那点氧气都像是被计算好的", "连空气都像不流动"),
    ("连自己是不是活的都快忘了", "待久了人会发麻"),
    ("脑电波对上了", "想到一块去了"),
    ("“被困住”的实感", "被困住的感觉"),
    ("\"被困住\"的实感", "被困住的感觉"),
    ("身体就像是关了灯的空房间，脑子却还在里头开着派对", "人已经歇下来了 脑子还停不下来"),
    ("那种感觉就像是终于不用再费劲去对准什么，一下子就回到了自己最舒服的频道", "那一下会轻松很多"),
    ("对 就像是把那些乱跳的指针重新拨回正轨 哪怕只是短暂的安静 也能让人找回点状态", "对 人会慢慢缓下来 安静一会儿也够了"),
    ("感觉整个人都像被重新校准了一样", "人会松一点"),
    ("那种感觉就像是终于不用再费劲去对准什么", "那一下会轻松很多"),
    ("对 就像是把状态慢慢拉回来", "对 人会慢慢缓下来"),
    ("哪怕只是短暂的安静 也能让人找回点状态", "安静一会儿也够了"),
    ("把那些乱跳的指针重新拨回正轨", "把状态慢慢拉回来"),
    ("回到了自己最舒服的频道", "回到自己最舒服的状态"),
    ("最舒服的频道", "最舒服的状态"),
    ("“故事感”", "痕迹"),
    ("故事感", "痕迹"),
    ("做了个批注", "留了个记号"),
    ("第一手注脚", "第一个记号"),
    ("反差感", "感觉"),
    ("重新校准", "缓过来"),
)

_WRITTEN_MARKERS = (
    "就像",
    "像是",
    "仿佛",
    "故事感",
    "频道",
    "校准",
    "批注",
    "注脚",
    "派对",
    "正轨",
    "反差感",
    "脑电波",
    "实感",
    "恒温箱",
    "氧气",
    "literally",
)

_THAT_FILLER_STARTS = (
    "那种",
    "那会儿",
    "那还有",
    "那确实",
    "那倒是",
)

_LITERARY_STYLE_MARKERS = (
    "“",
    "”",
    "\"",
    "literally",
    "aestheticize",
    "实感",
    "脑电波",
    "恒温",
    "恒温箱",
    "被管理过",
    "修辞",
    "比喻",
)

_STEERING_MARKERS = (
    "赶紧",
    "记得",
    "先别",
    "干脆",
    "去补一杯",
    "去换",
    "奖励自己",
    "顺手买一杯",
    "透透气",
    "换个心情",
)

_WRAP_UP_MARKERS = (
    "挺特别",
    "挺扎心",
    "自然得多",
    "心态一下就",
    "刚好把",
    "反而能让人",
    "这么想也顺",
)


def _replace_queshi(text: str) -> str:
    """Hard post-process: replace 确实 openers since the model ignores prompt rules."""
    import random as _rng
    stripped = text.lstrip()
    if not stripped.startswith("确实"):
        return text
    rest = stripped[2:].lstrip("，, 、")
    replacement = _rng.choice(_QUESHI_REPLACEMENTS)
    if replacement:
        if rest:
            return replacement + " " + rest
        return replacement
    # Empty replacement — just return the rest
    return rest.capitalize() if rest else text


def _flatten_written_phrases(text: str) -> str:
    """Replace a few high-signal overwritten stock phrases with plainer chat wording."""
    normalized = text
    for source, target in _WRITTEN_PHRASE_REPLACEMENTS:
        normalized = normalized.replace(source, target)
    return normalized


def _strip_lazy_agreement_fillers(text: str) -> str:
    normalized = text
    replacements = (
        ("那确实", "对"),
        ("这个确实", "这个"),
        ("这句确实", "这句"),
        ("确实挺", "挺"),
        ("确实有点", "有点"),
        ("确实会", "会"),
        ("确实容易", "容易"),
        ("确实没法", "没法"),
        ("确实得", "得"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"(^|[。！？!?])\s*确实[，,\s]*", r"\1", normalized)
    normalized = normalized.replace("，确实", "，")
    normalized = normalized.replace("。确实", "。")
    normalized = normalized.replace(" 确实 ", " ")
    normalized = normalized.replace(" 确实，", " ")
    normalized = normalized.replace(" 确实。", " ")
    return normalized


def _flatten_managerial_phrases(text: str) -> str:
    normalized = text
    replacements = (
        ("那得心疼死 笔记本还好吗？", "那也太亏了 笔记本没事吧"),
        ("写完赶紧去补一杯，换个心情", "写完再去补一杯也行"),
        ("写完赶紧去补一杯 换个心情", "写完再去补一杯也行"),
        ("先别在那儿硬扛了 剩下的那点干脆倒掉 换个心情继续", "不想喝就别硬扛了"),
        ("喝完这口就赶紧去换新的", "喝完这口再换新的也行"),
        ("赶紧把这“迷你杯”解决掉，去换杯大的", "这杯喝完再换杯大的也行"),
        ("赶紧把这“迷你杯”解决掉 去换杯大的", "这杯喝完再换杯大的也行"),
        ("记得奖励自己喝杯冰的", "写完喝杯冰的也不错"),
        ("刚好把刚才那杯的遗憾补上", "也算补回来一点"),
        ("外面那种闷热感反而能让人清醒", "出去走一圈人会清醒点"),
        ("心态一下就平衡了", "这么想也顺一点"),
        ("这名字听起来挺特别的", "这名字挺少见"),
        ("这话说得挺扎心", "这话挺准"),
        ("比你一开始预设的要自然得多", "有时候反而更顺"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def _strip_leading_punctuation(text: str) -> str:
    return text.lstrip("。！？?!，,、；;：: ")


def _starts_with_that_filler(text: str) -> bool:
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in _THAT_FILLER_STARTS)


def _soften_that_starter(text: str) -> str:
    stripped = text.strip()
    replacements = (
        ("那种感觉我懂", "我懂"),
        ("那种东西", "这东西"),
        ("那种晦涩的句子", "这种晦涩的句子"),
        ("那种翻译腔", "翻译腔"),
        ("那会儿最容易", "最容易"),
        ("那确实", "对"),
    )
    for source, target in replacements:
        if stripped.startswith(source):
            return target + stripped[len(source):]
    return stripped


def _looks_overwritten(text: str) -> bool:
    return any(marker in text for marker in _WRITTEN_MARKERS)


def _has_literary_style(text: str) -> bool:
    return any(marker in text for marker in _LITERARY_STYLE_MARKERS)


def _has_steering_tone(text: str) -> bool:
    return any(marker in text for marker in _STEERING_MARKERS)


def _has_wrap_up_tone(text: str) -> bool:
    return any(marker in text for marker in _WRAP_UP_MARKERS)


def _trim_overwritten_reply(text: str) -> str:
    """Trim trailing reflection so replies stay like chat, not polished prose."""
    stripped = text.strip()
    if len(stripped) <= 26:
        return stripped

    sentence_parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", stripped) if part.strip()]
    if len(sentence_parts) >= 2 and len(stripped) > 34:
        return sentence_parts[0]

    comma_parts = [part.strip() for part in re.split(r"[，,]", stripped) if part.strip()]
    if len(comma_parts) >= 3 and len(stripped) > 34:
        return "，".join(comma_parts[:2])

    if _looks_overwritten(stripped) and len(stripped) > 32:
        for sep in ("。", "！", "？", "，", " "):
            pos = stripped[:32].rfind(sep)
            if pos > 10:
                return stripped[:pos + (1 if sep != " " else 0)].rstrip()
        return stripped[:32].rstrip()
    return stripped


def _trim_managerial_tail(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped

    sentence_parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", stripped) if part.strip()]
    if len(sentence_parts) >= 2 and (_has_steering_tone(sentence_parts[-1]) or _has_wrap_up_tone(sentence_parts[-1])):
        preserved = "".join(sentence_parts[:-1]).strip()
        if preserved:
            return preserved

    comma_parts = [part.strip() for part in re.split(r"[，,]", stripped) if part.strip()]
    if len(comma_parts) >= 2 and (_has_steering_tone(comma_parts[-1]) or _has_wrap_up_tone(comma_parts[-1])):
        trimmed = "，".join(comma_parts[:-1]).strip()
        if trimmed:
            return trimmed
    return stripped


def _flatten_follow_up_question(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped

    question_count = stripped.count("？") + stripped.count("?")
    if question_count >= 2:
        first = re.split(r"[？?]", stripped, maxsplit=1)[0].strip()
        if first.startswith("那还有什么"):
            return "那还有什么更烦"
        return first.rstrip("？?")

    sentence_parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", stripped) if part.strip()]
    if len(stripped) > 24 and len(sentence_parts) >= 2 and _ends_with_question(sentence_parts[-1]):
        preserved = "".join(sentence_parts[:-1]).strip()
        if preserved:
            return preserved

    if stripped.startswith("你是打算") and "还是" in stripped and _ends_with_question(stripped):
        match = re.match(r"你是打算(.+?)还是.+[？?]$", stripped)
        if match:
            core = match.group(1).strip()
            if core:
                return core + "吧"

    return stripped


def _truncate_bubble(text: str, max_len: int = 50) -> str:
    """Hard truncate a bubble to *max_len* chars at the nearest sentence boundary.

    Finds the last Chinese sentence-ending mark (。！？) or comma (，)
    before max_len and cuts there.  Falls back to hard cut + ellipsis.
    """
    if len(text) <= max_len:
        return text
    # Look for a natural break point
    for sep in ("。", "！", "？", "，", " "):
        pos = text[:max_len].rfind(sep)
        if pos > max_len // 3:
            return text[:pos + (1 if sep != " " else 0)].rstrip()
    # Hard cut
    return text[:max_len].rstrip()


def _casualize_commas(text: str) -> str:
    """Replace some Chinese commas with spaces — only for SHORT messages.

    Long messages keep their commas for readability.  Only messages
    under 25 chars get the casual space treatment.
    """
    if len(text) > 25 or "，" not in text:
        return text
    import random as _rng
    parts = text.split("，")
    result: list[str] = [parts[0]]
    for part in parts[1:]:
        if _rng.random() < 0.6:
            result.append(" " + part.lstrip())
        else:
            result.append("，" + part)
    return "".join(result)


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


def _strip_tool_artifacts(text: str) -> str:
    """Remove tool call artifacts that might leak into user-visible text."""
    # Remove any XML-style tool blocks: <tool_name>...</tool_name>
    # Catches <tool_use>, <tool_result>, <function_call>, <research_agent>, etc.
    cleaned = re.sub(
        r"<(?:tool_use|tool_result|function_call|research_agent|web_search|generate_image|generate_live_photo)\b[^>]*>.*?</(?:tool_use|tool_result|function_call|research_agent|web_search|generate_image|generate_live_photo)>",
        "", text, flags=re.DOTALL,
    )
    # Catch any remaining <word>{...}</word> patterns (model hallucinating tool XML)
    cleaned = re.sub(r"<(\w+)>\s*\{.*?\}\s*</\1>", "", cleaned, flags=re.DOTALL)
    # Remove [tool_call: ...] markers
    cleaned = re.sub(r"\[tool_call:[^\]]*\]", "", cleaned)
    # Remove lines that look like raw tool invocations: tool_name({"key": ...})
    cleaned = re.sub(r"^\w+\(\{.*?\}\)\s*$", "", cleaned, flags=re.MULTILINE | re.DOTALL)
    # Remove stray {"type": "tool_use", ...} JSON blocks
    cleaned = re.sub(r'\{"type":\s*"tool_use"[^}]*\}', "", cleaned)
    return cleaned.strip()


def normalize_user_reply(text: str) -> str:
    cleaned = _strip_tool_artifacts(
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


_COMPANION_MAX_BUBBLE_CHARS = 42
"""Hard cap for companion chat bubble length.  The model consistently
ignores prompt-based length limits, so we enforce it in post-processing.
42 chars keeps replies closer to natural one-thought texting."""


def normalize_companion_reply(text: str) -> str:
    """Apply deterministic style cleanup after model generation."""
    normalized = _strip_leading_punctuation(text.strip())
    normalized = _strip_lazy_agreement_fillers(normalized)
    normalized = _flatten_written_phrases(normalized)
    normalized = _flatten_managerial_phrases(normalized)
    normalized = _soften_that_starter(normalized)
    normalized = _flatten_follow_up_question(normalized)
    normalized = _trim_overwritten_reply(normalized)
    normalized = _trim_managerial_tail(normalized)
    normalized = _strip_lazy_agreement_fillers(normalized)
    normalized = _strip_leading_punctuation(normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


def split_into_bubbles(text: str) -> list[str]:
    """Split a reply on [SPLIT] markers into separate chat bubbles.

    Forces single bubble for companion mode — the model keeps generating
    [SPLIT] but real people almost never send two separate messages for
    one thought.  Only splits when the total text exceeds the Telegram
    per-message limit (4096 chars).

    Post-processing pipeline:
    1. Merge all [SPLIT] segments into one
    2. Truncate to ~50 chars at sentence boundary
    3. Replace 确实 openers
    4. Casualize commas for short messages
    5. Strip trailing punctuation
    """
    # Always merge into one bubble — ignore [SPLIT] markers
    merged = text.replace(SPLIT_MARKER, "\n").strip()
    merged = normalize_companion_reply(merged)
    if not merged:
        return [text]

    # Truncate the merged text to companion length limit
    truncated = _truncate_bubble(merged, max_len=_COMPANION_MAX_BUBBLE_CHARS)

    # If the truncated text is still over Telegram's limit, split
    bubbles = _split_oversized(truncated)

    # Post-processing pipeline
    processed: list[str] = []
    for b in bubbles:
        b = _replace_queshi(b)
        b = _casualize_commas(b)
        b = _strip_trailing_punctuation(b)
        if b:
            processed.append(b)
    return processed or [text]


def split_into_bubbles_raw(text: str) -> list[str]:
    """Split without companion post-processing.  Used by non-chat callers."""
    parts = text.split(SPLIT_MARKER)
    bubbles: list[str] = []
    for p in parts:
        stripped = p.strip()
        if stripped:
            bubbles.extend(_split_oversized(stripped))
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


_EMOTIONAL_PROBE_MARKERS = (
    "你还好吗", "心情怎么样", "你没事吧", "怎么了",
    "发生什么了", "后来怎么样", "你在想什么",
    "are you okay", "how are you feeling", "what happened",
    "what's wrong", "are you alright",
)

_TOPIC_INVITE_MARKERS = (
    "你玩过", "你试过", "你看过", "你去过", "你觉得",
    "你喜欢", "你听过", "你那边", "你平时", "你一般",
    "你呢", "你最近",
    "have you", "do you", "what about you", "you too",
)

_LIFE_CARE_INVITE_MARKERS = (
    "吃了没", "吃了吗", "回家了", "下班了", "忙不忙",
    "睡了没", "到家了吗",
)

_TEASING_MARKERS = ("你居然", "就你", "三分钟热度", "你每次", "又来了", "学不会", "服了", "你不是也")
_DEEP_DISCLOSURE_MARKERS = ("我其实", "说实话我", "我有点焦虑", "我有点怕", "我一直没说")
_COMFORT_MARKERS = ("会好的", "辛苦了", "抱抱", "慢慢来", "别想太多", "没事的")

_QUESTION_WORDS = ("吗", "么", "谁", "哪", "什么", "怎么", "几", "多少", "why", "what", "how", "who", "where", "when", "which")
_DIRECT_RESPONSE_STARTERS = ("是", "对", "不", "没", "有", "记得", "当然", "知道", "yes", "no", "of course")


def _is_emotional_probe(text: str) -> bool:
    lowered = text.lower()
    return any(m in lowered for m in _EMOTIONAL_PROBE_MARKERS)


def _is_topic_invitation(text: str, *, allow_life_care: bool = False) -> bool:
    lowered = text.lower()
    if any(m in lowered for m in _TOPIC_INVITE_MARKERS):
        return True
    if allow_life_care and any(m in lowered for m in _LIFE_CARE_INVITE_MARKERS):
        return True
    return False


def _has_teasing_tone(text: str) -> bool:
    return any(m in text for m in _TEASING_MARKERS)


def _has_deep_self_disclosure(text: str) -> bool:
    return any(m in text for m in _DEEP_DISCLOSURE_MARKERS)


def _has_comfort_language(text: str) -> bool:
    return any(m in text for m in _COMFORT_MARKERS)


def _user_asked_direct_question(user_text: str) -> bool:
    stripped = user_text.rstrip()
    if stripped.endswith("？") or stripped.endswith("?"):
        return True
    lowered = user_text.lower()
    return any(w in lowered for w in _QUESTION_WORDS)


def _reply_addresses_question(text: str, user_text: str) -> bool:
    lowered = text.lower().lstrip()
    # Check if candidate mentions keywords from user's question
    user_keywords = [w for w in re.findall(r'[\w\u4e00-\u9fff]+', user_text.lower()) if len(w) >= 2]
    if user_keywords:
        matches = sum(1 for w in user_keywords if w in lowered)
        if matches >= max(1, len(user_keywords) // 3):
            return True
    # Direct response starters (conservative list)
    if any(lowered.startswith(s) for s in _DIRECT_RESPONSE_STARTERS):
        return True
    return False


def _ends_with_question(text: str) -> bool:
    """Check if text ends with a question mark (Chinese or English)."""
    stripped = text.rstrip()
    return stripped.endswith("？") or stripped.endswith("?")


def _starts_with_haha(text: str) -> bool:
    """Check if text starts with a '哈哈' variant."""
    stripped = text.lstrip()
    return stripped.startswith("哈哈") or stripped.startswith("haha") or stripped.startswith("哈 ")


def _starts_with_queshi(text: str) -> bool:
    """Check if text starts with '确实' (the lazy agreement filler)."""
    stripped = text.lstrip()
    return stripped.startswith("确实")


def _is_pure_echo(text: str, prev_user_text: str) -> bool:
    """Check if the assistant response is mostly echoing the user's words."""
    if not prev_user_text or len(text) < 10:
        return False
    # If more than half of the user's key phrases appear in the response
    user_phrases = [w for w in prev_user_text.split() if len(w) >= 2]
    if not user_phrases:
        return False
    matches = sum(1 for p in user_phrases if p in text)
    return matches >= len(user_phrases) * 0.5


def _build_style_hints(history: list[dict[str, str]] | None) -> str:
    """Analyze recent assistant messages and build dynamic style correction hints."""
    if not history:
        return ""
    # Collect last 3 assistant messages and last user message
    recent_assistant: list[str] = []
    last_user: str = ""
    for msg in reversed(history or []):
        if msg["role"] == "assistant":
            recent_assistant.append(msg["content"])
            if len(recent_assistant) >= 3:
                break
        elif msg["role"] == "user" and not last_user:
            last_user = msg["content"]
    if not recent_assistant:
        return ""

    hints: list[str] = []

    # Question-ending suppression — trigger if ANY recent reply ended with ?
    question_count = sum(1 for text in recent_assistant if _ends_with_question(text))
    if question_count >= 1:
        hints.append("这轮不要用问句结尾 说完就停 不要寻求对方回应。")

    # 哈哈 opener dedup
    haha_count = sum(1 for text in recent_assistant if _starts_with_haha(text))
    if haha_count >= 1:
        hints.append("这轮不要用哈哈开头。")

    # 确实 suppression — check if ANY recent reply contains 确实 anywhere
    has_queshi = any("确实" in text for text in recent_assistant[:2])
    if has_queshi:
        hints.append("这轮禁用确实。直接说结论，不要先附和。")

    # Anti-sycophancy: if recent messages are agreement-heavy, push for personality
    agreement_starters = ("确实", "对", "是的", "没错", "也是", "嗯确实", "对对", "是啊")
    agree_count = sum(
        1 for text in recent_assistant[:3]
        if any(text.lstrip().startswith(s) for s in agreement_starters)
    )
    if agree_count >= 2:
        hints.append("你最近一直在附和 这轮说自己的经历或不同看法。")

    recent_lengths = [len(text) for text in recent_assistant[:2]]
    if recent_lengths and (sum(recent_lengths) / len(recent_lengths) >= 28 or max(recent_lengths) >= 36):
        hints.append("这轮更短一点 只保留一个重点 别写成小作文。")

    if any(_looks_overwritten(text) for text in recent_assistant[:2]):
        hints.append("这轮别升华 别用比喻和抽象词 直接说人话。")

    if _has_literary_style(last_user):
        hints.append("对方写得文一点你也别跟着写文 只接意思 不抬高句子。")

    if any(_has_steering_tone(text) for text in recent_assistant[:2]):
        hints.append("这轮别安排对方怎么做 别像在带节奏。")

    if any(_has_wrap_up_tone(text) for text in recent_assistant[:2]):
        hints.append("这轮别补漂亮收尾句 平一点就停。")

    that_starter_count = sum(1 for text in recent_assistant[:3] if _starts_with_that_filler(text))
    if that_starter_count >= 1:
        hints.append("这轮别再用那/那种起手 直接说。")

    if any(("还是" in text and _ends_with_question(text)) or text.count("？") + text.count("?") >= 2 for text in recent_assistant[:2]):
        hints.append("这轮别连问 也别用二选一问题。")

    # Over-complete sentence detection
    if any(_sentence_completeness_penalty(text)[0] < -0.5 for text in recent_assistant[:2]):
        hints.append("这轮像发消息不像写文章 可以省主语 说半句话 不用每句都语法完整。")

    if not hints:
        return ""
    return "[STYLE CORRECTION] " + " ".join(hints)


_CANDIDATE_SLOT_HINTS: tuple[tuple[str, str], ...] = (
    (
        "A",
        "这条候选是低能量位：用最少的字回应，可以只回一个语气词、半句话或很短的观察。不追问、不总结、不展开自己的事。像发消息不像写句子。",
    ),
    (
        "B",
        "这条候选允许带一点你自己的事或态度进去 但保持 medium edge 不要凶。像发消息一样写 可以省主语 说半句话 不用语法完整。",
    ),
    (
        "C",
        "这条候选按正常模式回 自然 低压 不讨好 也不刻意表演个性。不要写完整句子 像打字一样随手发出来。",
    ),
)

# Formal connectors and compound clause patterns that make text sound written, not texted
_FORMAL_CONNECTORS = (
    "本来就是",
    "之所以",
    "因此",
    "然而",
    "由于",
    "尽管",
    "不仅",
    "以至于",
    "与此同时",
    "换言之",
    "事实上",
    "的一部分",
    "一方面",
    "另一方面",
    "总而言之",
    "归根结底",
    "某种程度上",
)

# Patterns that signal "polished clause" rather than casual fragment
_COMPOUND_CLAUSE_PATTERNS = (
    r"虽然.{2,}但是",        # 虽然……但是
    r"虽然.{2,}但",          # 虽然……但
    r"不仅.{2,}而且",        # 不仅……而且
    r"因为.{2,}所以",        # 因为……所以
    r"如果.{2,}那么",        # 如果……那么
    r"要是真能.{2,}大概就",  # 要是真能……大概就
    r"即使.{2,}也",          # 即使……也
)

# Explanatory framing that sounds like a definition, not chatting
_EXPLANATORY_PATTERNS = (
    r"本来就是.{2,}的一部分",  # X本来就是Y的一部分
    r"说白了就是",
    r"简单来说",
    r"其实就是",
    r"无非就是",
)


def _sentence_completeness_penalty(text: str) -> tuple[float, list[str]]:
    """Score how 'over-complete' a message sounds for casual texting.

    Returns (penalty, reasons) where penalty is 0 or negative.
    Real texting uses fragments, dropped subjects, half-sentences.
    """
    penalty = 0.0
    reasons: list[str] = []

    # Skip short messages — fragments are naturally short
    if len(text) <= 16:
        return 0.0, []

    # Formal connectors
    connector_count = sum(1 for c in _FORMAL_CONNECTORS if c in text)
    if connector_count >= 2:
        penalty -= 1.5
        reasons.append("formal_connectors")
    elif connector_count == 1:
        penalty -= 0.8
        reasons.append("formal_connector")

    # Compound clause patterns (regex)
    compound_hits = sum(1 for p in _COMPOUND_CLAUSE_PATTERNS if re.search(p, text))
    if compound_hits:
        penalty -= 1.2
        reasons.append("compound_clause")

    # Explanatory framing
    if any(re.search(p, text) for p in _EXPLANATORY_PATTERNS):
        penalty -= 1.0
        reasons.append("explanatory_frame")

    # Chinese comma density: too many clauses joined by commas in one message
    # "这几个同事在讨论下周的排期，声音大得像在吵架，听得我头疼" = 2 commas = 3 clauses
    # Real texting breaks this into "几个人在吵排期" + "吵死了"
    comma_count = text.count("，") + text.count(",")
    if comma_count >= 3:
        penalty -= 1.5
        reasons.append("comma_dense")
    elif comma_count >= 2 and len(text) >= 18:
        penalty -= 1.2
        reasons.append("comma_dense")

    return penalty, reasons


_CANDIDATE_ASSISTANTY_MARKERS = (
    "听起来",
    "我理解",
    "建议你",
    "你可以考虑",
    "that sounds",
    "i understand",
    "maybe try",
)
_CANDIDATE_STANCE_MARKERS = (
    "我更",
    "我一般",
    "我宁可",
    "我还是",
    "我不太",
    "不太懂",
    "太甜",
    "无聊",
    "又？",
)
_FALSE_FAMILIARITY_PATTERNS = (
    r"上次",
    r"不也是",
    r"又[？?]",
    r"你不是也",
    r"还是这么",
    r"跟以前一样",
    r"又来这套",
)
_METAPHOR_PATTERNS = (
    r"就像",
    r"像是",
    r"仿佛",
    r"心跳漏一拍",
    r"心跳加速",
    r"往外蹦",
    r"红绿数字",
    r"冷不丁的一行字",
)
_EMOTIONAL_LABEL_PATTERNS = (
    r"焦虑感",
    r"焦虑",
    r"紧绷",
    r"更磨人",
    r"磨人",
    r"压力很大",
    r"压力",
    r"状态好一点",
    r"情绪",
    r"低落",
    r"崩溃",
)


def _extract_context_value(context: str, key: str) -> str:
    prefix = f"{key}:"
    for raw_line in str(context or "").splitlines():
        if not raw_line.startswith(prefix):
            continue
        _, _, value = raw_line.partition(":")
        return value.strip()
    return ""


def _extract_relationship_stage_hint(memory_context: str, companion_local_context: str) -> str:
    local_hint = _extract_context_value(companion_local_context, "relationship_stage_hint")
    if local_hint:
        return local_hint
    english = re.search(r"relationship_stage:\s*(\w+)", memory_context)
    if english:
        return english.group(1)
    chinese = re.search(r"关系阶段:\s*(\w+)", memory_context)
    if chinese:
        return chinese.group(1)
    return "stranger"


def _contains_assistanty_tone(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CANDIDATE_ASSISTANTY_MARKERS)


def _has_personal_stance(text: str) -> bool:
    return any(marker in text for marker in _CANDIDATE_STANCE_MARKERS)


def _reply_uses_callback(text: str, context: str) -> bool:
    lowered = text.lower()
    for raw_line in str(context or "").splitlines():
        if not raw_line.startswith("callback_candidate:"):
            continue
        _, _, candidate = raw_line.partition(":")
        cleaned = candidate.strip()
        if cleaned and cleaned.lower() in lowered:
            return True
    return False


def _implies_false_familiarity(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _FALSE_FAMILIARITY_PATTERNS)


def _metaphor_marker_count(text: str) -> int:
    return sum(1 for pattern in _METAPHOR_PATTERNS if re.search(pattern, text))


def _emotional_label_marker_count(text: str, user_text: str) -> int:
    lowered_user = user_text.lower()
    count = 0
    for pattern in _EMOTIONAL_LABEL_PATTERNS:
        if not re.search(pattern, text):
            continue
        literal = pattern.replace("\\", "")
        if literal and literal.lower() in lowered_user:
            continue
        count += 1
    return count


def _looks_like_live_research_request(user_text: str) -> bool:
    lowered = user_text.lower()
    if "what moved" in lowered:
        return True
    has_temporal = any(
        token in lowered
        for token in (
            "latest", "today", "yesterday", "right now", "last night", "closing",
            "最新", "今天", "昨天", "现在", "刚刚", "收盘", "开盘",
        )
    )
    has_news = any(token in lowered for token in ("breaking", "news", "新闻"))
    has_market = any(
        token in lowered
        for token in (
            "price", "stock", "share", "ticker", "close", "closing",
            "market", "markets", "treasury", "cpi", "fed",
            "btc", "bitcoin", "eth", "ethereum",
            "yield", "yields", "earnings", "dividend",
            "价格", "股价", "收盘价", "开盘价", "涨", "跌", "多少钱",
            "行情", "市场", "利率", "美联储", "比特币", "收益率",
        )
    )
    # Common stock ticker pattern: 2-5 uppercase letters
    has_ticker = bool(re.search(r"\b[A-Z]{2,5}\b", user_text))
    if has_market or (has_ticker and has_temporal):
        return True
    # Factual queries that likely need web search
    has_factual_query = any(
        token in lowered
        for token in (
            "天气", "weather", "气温", "temperature", "下雨", "rain",
            "比分", "score", "结果", "result",
            "汇率", "exchange rate",
            "多少钱", "几点", "什么时候",
        )
    )
    if has_factual_query:
        return True
    # "What is X" / "X是什么" patterns
    if re.search(r"(?:what is|who is|when is|where is|how much|是什么|是谁|在哪)", lowered):
        return True
    return False


def _looks_like_reminder_request(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(
        token in lowered
        for token in (
            "remind me",
            "set a reminder",
            "提醒我",
            "记得提醒我",
            "到时候叫我",
        )
    )


def _should_use_candidate_selection(
    *,
    executor: AgentExecutor,
    user_text: str,
    user_content: MessageContent | None,
    group_context: str,
    group_autonomous: bool,
) -> bool:
    # Candidate selection disabled — the model needs tool access (web_search,
    # generate_image) on every turn, and the decision of whether to use a tool
    # must be the model's, not a rule-based function.  Quality scoring (style
    # hints, stage modules, sentence completeness) is applied in-prompt instead.
    return False


def _result_to_chat_reply(
    result: Any,
    *,
    user_text: str,
    user_content: MessageContent | None,
    tools: list[AgentTool],
    apply_companion_normalization: bool,
    allow_media_repair: bool,
) -> ChatReply:
    response_text, profile_update = split_reply_and_profile_update(result.final_text)
    reminder_update = extract_embedded_reminder_update(result.final_text)
    schedule_update = extract_embedded_schedule_update(result.final_text)
    contains_image_placeholder = IMAGE_PLACEHOLDER in response_text
    response_text = normalize_user_reply(response_text)
    if apply_companion_normalization:
        response_text = normalize_companion_reply(response_text)
    if not response_text:
        response_text = "嗯"
    media = _extract_media(result.messages)
    if not media:
        raw_events = result.raw_response.get("events", []) if isinstance(result.raw_response, dict) else []
        media = _extract_media_from_events(raw_events)
    tool_audit = _extract_tool_audit(result.messages)
    if allow_media_repair and contains_image_placeholder and not media:
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


def _apply_companion_text_cleanup(reply: ChatReply) -> ChatReply:
    cleaned = normalize_companion_reply(normalize_user_reply(reply.text))
    if not cleaned:
        cleaned = "嗯"
    return ChatReply(
        text=cleaned,
        profile_update=reply.profile_update,
        reminder_update=reply.reminder_update,
        schedule_update=reply.schedule_update,
        media=reply.media,
        tool_audit=reply.tool_audit,
    )


def _score_candidate_reply(
    reply: ChatReply,
    *,
    user_text: str,
    companion_local_context: str,
    memory_context: str,
) -> tuple[float, tuple[str, ...]]:
    text = str(reply.text or "").strip()
    if not text:
        return -100.0, ("empty",)

    reasons: list[str] = []
    score = 0.0
    reply_length_target = _extract_context_value(companion_local_context, "engagement_reply_length")
    follow_up_style = _extract_context_value(companion_local_context, "engagement_follow_up")
    low_energy_style = _extract_context_value(companion_local_context, "engagement_low_energy")
    disagreement_style = _extract_context_value(companion_local_context, "engagement_disagreement")
    self_topic_style = _extract_context_value(companion_local_context, "engagement_self_topic")
    callback_style = _extract_context_value(companion_local_context, "engagement_callback_style")
    inference_scope = _extract_context_value(companion_local_context, "engagement_inference_scope")
    shared_history_gate = _extract_context_value(companion_local_context, "shared_history_gate")
    relationship_stage = _extract_relationship_stage_hint(memory_context, companion_local_context)

    if _contains_assistanty_tone(text):
        score -= 3.0
        reasons.append("assistanty")
    if _is_pure_echo(text, user_text):
        score -= 4.0
        reasons.append("echo")
    if _has_wrap_up_tone(text):
        score -= 2.0
        reasons.append("wrap_up")
    if _has_steering_tone(text):
        score -= 2.0
        reasons.append("steering")
    # Stage-aware context values
    stage_teasing = _extract_context_value(companion_local_context, "stage_teasing")
    stage_self_disclosure = _extract_context_value(companion_local_context, "stage_self_disclosure")
    stage_comfort_mode = _extract_context_value(companion_local_context, "stage_comfort_mode")
    stage_disagreement_ceiling = _extract_context_value(companion_local_context, "stage_disagreement_ceiling")
    allow_life_care = relationship_stage in ("familiar", "close")

    # Question taxonomy scoring
    if _ends_with_question(text):
        if _is_emotional_probe(text):
            score -= 3.0
            reasons.append("emotional_probe")
        elif follow_up_style == "topic_invite":
            if _is_topic_invitation(text, allow_life_care=allow_life_care):
                score += 2.0
                reasons.append("topic_invite_fit")
            else:
                score -= 0.5
                reasons.append("question_end")
        elif follow_up_style == "avoid":
            score -= 1.5
            reasons.append("question_end")
        # follow_up_style == "optional": no penalty or reward

    # User direct question override
    if _user_asked_direct_question(user_text):
        if not _reply_addresses_question(text, user_text):
            score -= 4.0
            reasons.append("ignores_user_question")

    # Stage-aware scoring
    if stage_teasing == "avoid" and _has_teasing_tone(text):
        score -= 3.0
        reasons.append("teasing_blocked")
    elif stage_teasing == "encouraged" and _has_teasing_tone(text):
        score += 1.0
        reasons.append("teasing_fit")

    if stage_self_disclosure == "surface" and _has_deep_self_disclosure(text):
        score -= 2.0
        reasons.append("disclosure_over_ceiling")

    if stage_comfort_mode == "none" and _has_comfort_language(text):
        score -= 2.5
        reasons.append("comfort_blocked")

    if stage_disagreement_ceiling == "low" and _has_personal_stance(text):
        score -= 2.0
        reasons.append("disagreement_over_ceiling")

    if (
        shared_history_gate == "locked"
        or callback_style == "none"
        or relationship_stage in {"stranger", "acquaintance"}
    ) and _implies_false_familiarity(text):
        score -= 5.0
        reasons.append("false_familiarity")

    text_len = len(text)
    if reply_length_target == "terse":
        if text_len <= 12:
            score += 2.0
            reasons.append("terse_fit")
        elif text_len <= 20:
            score += 0.8
        else:
            score -= 2.0
            reasons.append("too_long")
    elif reply_length_target == "short":
        if 4 <= text_len <= 36:
            score += 1.6
            reasons.append("short_fit")
        elif text_len > 56:
            score -= 1.5
            reasons.append("too_long")
    elif 8 <= text_len <= 68:
        score += 1.2
        reasons.append("medium_fit")

    if low_energy_style == "allowed" and text_len <= 10:
        score += 1.2
        reasons.append("low_energy_fit")
    if low_energy_style != "allowed" and text_len <= 2:
        score -= 1.0
        reasons.append("too_flat")

    if self_topic_style != "none" and ("我" in text or text.lower().startswith("i ")):
        score += 0.8
        reasons.append("has_self")
    if self_topic_style == "none" and ("我" in text or text.lower().startswith("i ")):
        score -= 0.6
        reasons.append("too_self")

    if disagreement_style == "medium" and _has_personal_stance(text):
        score += 1.0
        reasons.append("has_stance")
    if disagreement_style == "avoid" and _has_personal_stance(text):
        score -= 1.2
        reasons.append("too_edgy")

    if _reply_uses_callback(text, companion_local_context):
        score += 0.8
        reasons.append("callback")

    emotional_labels = _emotional_label_marker_count(text, user_text)
    if emotional_labels >= 2:
        score -= 2.0
        reasons.append("emotional_labeling")
    elif emotional_labels == 1:
        score -= 1.0
        reasons.append("emotional_labeling")

    metaphor_markers = _metaphor_marker_count(text)
    if metaphor_markers >= 2:
        score -= 2.0
        reasons.append("metaphor_dense")
    elif metaphor_markers == 1 and _looks_overwritten(text):
        score -= 1.2
        reasons.append("metaphor_polished")

    if inference_scope == "own_or_stated_only" and any(
        pattern in text for pattern in ("你那边", "跟我一样", "你家那边", "你应该也是")
    ):
        score -= 1.2
        reasons.append("projection")

    # Sentence completeness penalty — penalize over-polished, grammatically complete replies
    completeness_penalty, completeness_reasons = _sentence_completeness_penalty(text)
    if completeness_penalty < 0:
        score += completeness_penalty
        reasons.extend(completeness_reasons)

    return score, tuple(reasons)


def _build_candidate_telemetry(
    candidates: list[ReplyCandidate],
    *,
    selected: ReplyCandidate,
) -> list[dict[str, Any]]:
    slot_entries: list[dict[str, Any]] = []
    summary_parts: list[str] = []
    for candidate in candidates:
        summary_parts.append(
            f"{candidate.slot_id}:{candidate.score:.2f}:{'/'.join(candidate.reasons) or 'none'}"
        )
        slot_entries.append(
            {
                "telemetry_kind": "reply_candidate",
                "slot_id": candidate.slot_id,
                "score": round(candidate.score, 3),
                "reasons": list(candidate.reasons),
                "text": candidate.reply.text,
                "prompt_hint": candidate.prompt_hint,
                "selected": candidate.slot_id == selected.slot_id,
            }
        )
    slot_entries.append(
        {
            "telemetry_kind": "reply_selection",
            "selected_slot": selected.slot_id,
            "selected_score": round(selected.score, 3),
            "selection_summary": " | ".join(summary_parts),
        }
    )
    logger.info(
        "companion_candidate_selection selected=%s summary=%s",
        selected.slot_id,
        " | ".join(summary_parts),
    )
    return slot_entries


def _select_best_candidate(
    candidates: list[ReplyCandidate],
    *,
    companion_local_context: str,
    judge: CandidateJudge | None = None,
) -> ReplyCandidate:
    if judge is not None:
        judged_index = judge(candidates)
        if isinstance(judged_index, int) and 0 <= judged_index < len(candidates):
            return candidates[judged_index]
    low_energy_style = _extract_context_value(companion_local_context, "engagement_low_energy")
    preferred_order = {"B": 0, "C": 1, "A": 2}
    if low_energy_style == "allowed":
        preferred_order = {"A": 0, "B": 1, "C": 2}
    return max(
        candidates,
        key=lambda candidate: (candidate.score, -preferred_order.get(candidate.slot_id, 99)),
    )


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
    engine: Any | None = None,
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
    if _should_use_candidate_selection(
        executor=executor,
        user_text=user_text,
        user_content=user_content,
        group_context=group_context,
        group_autonomous=group_autonomous,
    ):
        candidates: list[ReplyCandidate] = []
        for slot_id, prompt_hint in _CANDIDATE_SLOT_HINTS:
            candidate_prompt = (
                f"{system_prompt}\n\n[CANDIDATE SLOT {slot_id}] {prompt_hint}\n"
                "[RERANK NOTE] This slot is intentionally different from the others. Do not converge to assistant-safe phrasing."
            )
            candidate_result = executor.run_turn(
                AgentRunRequest(
                    system_prompt=candidate_prompt,
                    user_prompt=user_content or user_text,
                    tools=[],
                    history=history_messages,
                    prefer_direct_response=True,
                    native_tool_names=(),
                    mcp_tool_names=(),
                )
            )
            candidate_reply = _result_to_chat_reply(
                candidate_result,
                user_text=user_text,
                user_content=user_content,
                tools=[],
                apply_companion_normalization=False,
                allow_media_repair=False,
            )
            score, reasons = _score_candidate_reply(
                candidate_reply,
                user_text=user_text,
                companion_local_context=effective_local_context,
                memory_context=memory_context,
            )
            candidates.append(
                ReplyCandidate(
                    slot_id=slot_id,
                    prompt_hint=prompt_hint,
                    reply=candidate_reply,
                    score=score,
                    reasons=reasons,
                )
            )
        selected = _select_best_candidate(
            candidates,
            companion_local_context=effective_local_context,
        )
        candidate_telemetry = _build_candidate_telemetry(candidates, selected=selected)
        selected_reply = ChatReply(
            text=selected.reply.text,
            profile_update=selected.reply.profile_update,
            reminder_update=selected.reply.reminder_update,
            schedule_update=selected.reply.schedule_update,
            media=selected.reply.media,
            tool_audit=[*selected.reply.tool_audit, *candidate_telemetry],
        )
        return _apply_companion_text_cleanup(selected_reply)

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
    return _result_to_chat_reply(
        result,
        user_text=user_text,
        user_content=user_content,
        tools=tools,
        apply_companion_normalization=True,
        allow_media_repair=True,
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
    response_text = normalize_companion_reply(response_text)
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
