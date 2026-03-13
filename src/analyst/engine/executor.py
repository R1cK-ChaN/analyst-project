from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .agent_loop import AgentLoopConfig, PythonAgentLoop
from .backends import ClaudeCodeProvider, build_llm_provider_from_env
from .live_types import (
    AgentLoopResult,
    AgentTool,
    CompletionResult,
    ConversationMessage,
    LLMProvider,
    LoopEvent,
    MessageContent,
)
from analyst.mcp.bridge import ClaudeCodeMcpConfig


class ExecutorBackend(str, Enum):
    HOST_LOOP = "host_loop"
    CLAUDE_CODE = "claude_code"


@dataclass(frozen=True)
class AgentRunRequest:
    system_prompt: str
    user_prompt: MessageContent
    tools: list[AgentTool]
    history: list[ConversationMessage] = field(default_factory=list)
    prefer_direct_response: bool = False
    native_tool_names: tuple[str, ...] = ()
    mcp_tool_names: tuple[str, ...] | None = None


class AgentExecutor(Protocol):
    backend: ExecutorBackend
    provider: LLMProvider | None
    config: AgentLoopConfig
    mcp_tool_names: tuple[str, ...]

    def run_turn(self, request: AgentRunRequest) -> AgentLoopResult:
        ...


def _completion_to_result(
    *,
    request: AgentRunRequest,
    completion: CompletionResult,
) -> AgentLoopResult:
    messages = [
        *list(request.history),
        ConversationMessage(role="user", content=request.user_prompt),
        completion.message,
    ]
    events = [
        LoopEvent(event_type="agent_start", payload={}),
        LoopEvent(
            event_type="assistant_message",
            payload={
                "turn": 0,
                "content": completion.message.content or "",
                "tool_calls": [tool_call.name for tool_call in completion.message.tool_calls],
            },
        ),
    ]
    if not completion.message.tool_calls:
        events.append(LoopEvent(event_type="agent_end", payload={"turns": 1}))
    return AgentLoopResult(
        messages=messages,
        final_text=str(completion.message.content or ""),
        events=events,
    )


@dataclass
class HostLoopExecutor:
    provider: LLMProvider
    config: AgentLoopConfig = field(default_factory=AgentLoopConfig)
    mcp_tool_names: tuple[str, ...] = field(default_factory=tuple)
    backend: ExecutorBackend = field(default=ExecutorBackend.HOST_LOOP, init=False)

    def run_turn(self, request: AgentRunRequest) -> AgentLoopResult:
        if request.prefer_direct_response or not request.tools:
            completion = self.provider.complete(
                system_prompt=request.system_prompt,
                messages=[*list(request.history), ConversationMessage(role="user", content=request.user_prompt)],
                tools=[],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            return _completion_to_result(request=request, completion=completion)
        loop = PythonAgentLoop(self.provider, self.config)
        return loop.run(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            tools=request.tools,
            history=request.history,
        )


@dataclass
class ClaudeCodeExecutor:
    provider: ClaudeCodeProvider
    config: AgentLoopConfig = field(default_factory=AgentLoopConfig)
    mcp_tool_names: tuple[str, ...] = field(default_factory=tuple)
    mcp_db_path: str | None = None
    backend: ExecutorBackend = field(default=ExecutorBackend.CLAUDE_CODE, init=False)

    def run_turn(self, request: AgentRunRequest) -> AgentLoopResult:
        if request.prefer_direct_response or not request.tools:
            tool_names = self.mcp_tool_names if request.mcp_tool_names is None else request.mcp_tool_names
            mcp_config = None
            if tool_names:
                mcp_config = ClaudeCodeMcpConfig(
                    tool_names=tool_names,
                    db_path=self.mcp_db_path,
                )
            completion = self.provider.complete_native(
                system_prompt=request.system_prompt,
                messages=[*list(request.history), ConversationMessage(role="user", content=request.user_prompt)],
                allowed_tools=request.native_tool_names,
                mcp_config=mcp_config,
            )
            return _completion_to_result(request=request, completion=completion)
        loop = PythonAgentLoop(self.provider, self.config)
        return loop.run(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            tools=request.tools,
            history=request.history,
        )


@dataclass
class LegacyLoopExecutor:
    loop: Any
    config: AgentLoopConfig = field(default_factory=AgentLoopConfig)
    mcp_tool_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def provider(self) -> LLMProvider | None:
        return getattr(self.loop, "provider", None)

    @property
    def backend(self) -> ExecutorBackend:
        if isinstance(self.provider, ClaudeCodeProvider):
            return ExecutorBackend.CLAUDE_CODE
        return ExecutorBackend.HOST_LOOP

    def run_turn(self, request: AgentRunRequest) -> AgentLoopResult:
        provider = self.provider
        if request.prefer_direct_response and isinstance(provider, ClaudeCodeProvider):
            completion = provider.complete_native(
                system_prompt=request.system_prompt,
                messages=[*list(request.history), ConversationMessage(role="user", content=request.user_prompt)],
                allowed_tools=request.native_tool_names,
            )
            return _completion_to_result(request=request, completion=completion)
        if request.prefer_direct_response and provider is not None:
            completion = provider.complete(
                system_prompt=request.system_prompt,
                messages=[*list(request.history), ConversationMessage(role="user", content=request.user_prompt)],
                tools=[],
                max_tokens=getattr(self.loop.config, "max_tokens", self.config.max_tokens),
                temperature=getattr(self.loop.config, "temperature", self.config.temperature),
            )
            return _completion_to_result(request=request, completion=completion)
        return self.loop.run(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            tools=request.tools,
            history=request.history,
        )


def build_agent_executor(
    provider: LLMProvider,
    *,
    config: AgentLoopConfig | None = None,
    mcp_tool_names: tuple[str, ...] = (),
    mcp_db_path: str | Path | None = None,
) -> AgentExecutor:
    resolved_config = config or AgentLoopConfig()
    if isinstance(provider, ClaudeCodeProvider):
        return ClaudeCodeExecutor(
            provider=provider,
            config=resolved_config,
            mcp_tool_names=tuple(mcp_tool_names),
            mcp_db_path=str(mcp_db_path) if mcp_db_path else None,
        )
    return HostLoopExecutor(provider=provider, config=resolved_config, mcp_tool_names=tuple(mcp_tool_names))


def build_agent_executor_from_env(
    *,
    model_keys: tuple[str, ...],
    default_model: str,
    config: AgentLoopConfig | None = None,
    mcp_tool_names: tuple[str, ...] = (),
    mcp_db_path: str | Path | None = None,
) -> AgentExecutor:
    provider = build_llm_provider_from_env(
        model_keys=model_keys,
        default_model=default_model,
    )
    return build_agent_executor(
        provider,
        config=config,
        mcp_tool_names=mcp_tool_names,
        mcp_db_path=mcp_db_path,
    )


def coerce_agent_executor(
    candidate: AgentExecutor | Any,
    *,
    config: AgentLoopConfig | None = None,
) -> AgentExecutor:
    if isinstance(candidate, (HostLoopExecutor, ClaudeCodeExecutor, LegacyLoopExecutor)):
        return candidate
    if hasattr(candidate, "run"):
        return LegacyLoopExecutor(loop=candidate, config=config or AgentLoopConfig())
    if hasattr(candidate, "run_turn") and hasattr(candidate, "backend"):
        return candidate
    return LegacyLoopExecutor(loop=candidate, config=config or AgentLoopConfig())
