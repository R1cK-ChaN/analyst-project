from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

MessageContent = str | list[dict[str, Any]]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: MessageContent | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class CompletionResult:
    message: ConversationMessage
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class LoopEvent:
    event_type: str
    payload: dict[str, Any]


class ToolHandler(Protocol):
    def __call__(self, arguments: dict[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


class LLMProvider(Protocol):
    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[AgentTool],
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        ...


@dataclass(frozen=True)
class AgentLoopResult:
    messages: list[ConversationMessage]
    final_text: str
    events: list[LoopEvent]
