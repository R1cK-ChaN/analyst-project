from __future__ import annotations

from dataclasses import dataclass, field

from analyst.engine.live_types import MessageContent
from analyst.tools._request_context import RequestImageInput


@dataclass(frozen=True)
class ConversationInput:
    user_id: str
    channel: str
    channel_id: str
    thread_id: str
    message: str
    current_user_text: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    group_context: str = ""
    group_id: str = ""
    user_content: MessageContent | None = None
    companion_local_context: str = ""
    attached_image: RequestImageInput | None = None
    persona_mode: str = "companion"


@dataclass(frozen=True)
class ProactiveConversationInput:
    user_id: str
    channel: str
    channel_id: str
    thread_id: str
    kind: str
    companion_local_context: str = ""
    persona_mode: str = "companion"


def build_cli_conversation_input(
    *,
    user_id: str,
    channel_id: str,
    thread_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    current_user_text: str = "",
    companion_local_context: str = "",
    persona_mode: str = "companion",
) -> ConversationInput:
    return ConversationInput(
        user_id=user_id,
        channel="cli",
        channel_id=channel_id,
        thread_id=thread_id,
        message=message,
        current_user_text=current_user_text or message,
        history=list(history or []),
        companion_local_context=companion_local_context,
        persona_mode=persona_mode,
    )


def build_telegram_conversation_input(
    *,
    user_id: str,
    channel_id: str,
    thread_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    current_user_text: str = "",
    group_context: str = "",
    group_id: str = "",
    user_content: MessageContent | None = None,
    companion_local_context: str = "",
    attached_image: RequestImageInput | None = None,
    persona_mode: str = "companion",
) -> ConversationInput:
    return ConversationInput(
        user_id=user_id,
        channel="telegram",
        channel_id=channel_id,
        thread_id=thread_id,
        message=message,
        current_user_text=current_user_text or message,
        history=list(history or []),
        group_context=group_context,
        group_id=group_id,
        user_content=user_content,
        companion_local_context=companion_local_context,
        attached_image=attached_image,
        persona_mode=persona_mode,
    )


def build_proactive_conversation_input(
    *,
    user_id: str,
    channel: str,
    channel_id: str,
    thread_id: str,
    kind: str,
    companion_local_context: str = "",
    persona_mode: str = "companion",
) -> ProactiveConversationInput:
    return ProactiveConversationInput(
        user_id=user_id,
        channel=channel,
        channel_id=channel_id,
        thread_id=thread_id,
        kind=kind,
        companion_local_context=companion_local_context,
        persona_mode=persona_mode,
    )
