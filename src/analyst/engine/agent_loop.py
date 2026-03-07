from __future__ import annotations

import json
from dataclasses import dataclass

from .live_types import AgentLoopResult, AgentTool, ConversationMessage, LLMProvider, LoopEvent


@dataclass(frozen=True)
class AgentLoopConfig:
    max_turns: int = 6
    max_tokens: int = 1800
    temperature: float = 0.2


class PythonAgentLoop:
    def __init__(self, provider: LLMProvider, config: AgentLoopConfig | None = None) -> None:
        self.provider = provider
        self.config = config or AgentLoopConfig()

    def run(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[AgentTool],
        history: list[ConversationMessage] | None = None,
    ) -> AgentLoopResult:
        events: list[LoopEvent] = [LoopEvent(event_type="agent_start", payload={})]
        messages: list[ConversationMessage] = list(history) if history else []
        messages.append(ConversationMessage(role="user", content=user_prompt))
        final_text = ""

        for turn in range(self.config.max_turns):
            completion = self.provider.complete(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            assistant_message = completion.message
            messages.append(assistant_message)
            events.append(
                LoopEvent(
                    event_type="assistant_message",
                    payload={
                        "turn": turn,
                        "content": assistant_message.content or "",
                        "tool_calls": [tool_call.name for tool_call in assistant_message.tool_calls],
                    },
                )
            )
            if not assistant_message.tool_calls:
                final_text = assistant_message.content or ""
                events.append(LoopEvent(event_type="agent_end", payload={"turns": turn + 1}))
                return AgentLoopResult(messages=messages, final_text=final_text, events=events)
            for tool_call in assistant_message.tool_calls:
                tool = self._find_tool(tool_call.name, tools)
                events.append(
                    LoopEvent(
                        event_type="tool_start",
                        payload={"tool_name": tool.name, "tool_call_id": tool_call.call_id, "arguments": tool_call.arguments},
                    )
                )
                result = tool.handler(tool_call.arguments)
                tool_content = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2)
                tool_message = ConversationMessage(
                    role="tool",
                    content=tool_content,
                    tool_call_id=tool_call.call_id,
                    tool_name=tool.name,
                )
                messages.append(tool_message)
                events.append(
                    LoopEvent(
                        event_type="tool_end",
                        payload={"tool_name": tool.name, "tool_call_id": tool_call.call_id},
                    )
                )

        raise RuntimeError("Agent loop reached max_turns without producing a final answer.")

    def _find_tool(self, name: str, tools: list[AgentTool]) -> AgentTool:
        for tool in tools:
            if tool.name == name:
                return tool
        raise RuntimeError(f"Tool {name} not found.")
