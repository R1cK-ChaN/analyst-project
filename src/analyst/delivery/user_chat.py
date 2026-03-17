from __future__ import annotations

from pathlib import Path

from analyst.engine.backends.factory import build_llm_provider_from_env
from analyst.runtime import chat as _chat_runtime
from analyst.runtime.chat import (
    CLAUDE_CODE_NATIVE_TOOL_NAMES,
    COMPANION_DEFAULT_MODEL,
    COMPANION_MODEL_KEYS,
    SPLIT_MARKER,
    ChatPersonaMode,
    ChatReply,
    MediaItem,
    COMPANION_SHARED_MCP_TOOL_NAMES,
    UserChatReply,
    _extract_media,
    _extract_tool_audit,
    build_chat_tools,
    build_companion_tools,
    build_user_chat_tools,
    generate_chat_reply,
    generate_proactive_companion_reply,
    generate_user_reply,
    resolve_chat_persona_mode,
    split_into_bubbles,
    system_prompt_with_memory,
)


def build_chat_services(
    *,
    db_path: Path | None = None,
    persona_mode: str | ChatPersonaMode | None = None,
):
    del persona_mode
    return _chat_runtime.build_companion_services(
        db_path=db_path,
        provider_factory=build_llm_provider_from_env,
    )


def build_companion_services(
    *,
    db_path: Path | None = None,
):
    return _chat_runtime.build_companion_services(
        db_path=db_path,
        provider_factory=build_llm_provider_from_env,
    )


def build_user_chat_services(
    *,
    db_path: Path | None = None,
):
    return build_companion_services(db_path=db_path)
