from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from analyst.env import get_env_value

from .live_types import AgentTool, CompletionResult, ConversationMessage, ToolCall


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    site_url: str = ""
    app_name: str = "analyst-project"
    timeout_seconds: int = 60

    @classmethod
    def from_env(
        cls,
        *,
        model_keys: tuple[str, ...] = ("ANALYST_OPENROUTER_MODEL", "LLM_MODEL"),
        default_model: str = "anthropic/claude-3.5-sonnet",
    ) -> "OpenRouterConfig":
        api_key = get_env_value("OPENROUTER_API_KEY", "LLM_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY or LLM_API_KEY is required for live engine commands.")
        model = get_env_value(*model_keys, default=default_model)
        return cls(
            api_key=api_key,
            model=model,
            base_url=get_env_value("OPENROUTER_BASE_URL", "LLM_BASE_URL", default="https://openrouter.ai/api/v1"),
            site_url=os.environ.get("OPENROUTER_SITE_URL", ""),
            app_name=os.environ.get("OPENROUTER_APP_NAME", "analyst-project"),
        )


class OpenRouterProvider:
    def __init__(self, config: OpenRouterConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[AgentTool],
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if self.config.site_url:
            headers["HTTP-Referer"] = self.config.site_url
        if self.config.app_name:
            headers["X-Title"] = self.config.app_name

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._build_messages(system_prompt, messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [self._tool_to_api_payload(tool) for tool in tools]
            payload["tool_choice"] = "auto"

        response = self.session.post(
            f"{self.config.base_url}/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=self.config.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text[:500]}")
        body = response.json()
        choices = body.get("choices", [])
        if not choices:
            raise RuntimeError("OpenRouter returned no choices.")
        message = choices[0].get("message", {})
        tool_calls = [
            ToolCall(
                call_id=tool_call["id"],
                name=tool_call["function"]["name"],
                arguments=self._parse_arguments(tool_call["function"].get("arguments", "{}")),
            )
            for tool_call in message.get("tool_calls", [])
        ]
        content = message.get("content")
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
            content = "\n".join(text_parts) or None
        return CompletionResult(
            message=ConversationMessage(role="assistant", content=content, tool_calls=tool_calls),
            raw_response=body,
        )

    def _build_messages(self, system_prompt: str, messages: list[ConversationMessage]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for message in messages:
            if message.role == "tool":
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content or "",
                    }
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                payload.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": tool_call.call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.name,
                                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=True, sort_keys=True),
                                },
                            }
                            for tool_call in message.tool_calls
                        ],
                    }
                )
                continue
            payload.append({"role": message.role, "content": message.content or ""})
        return payload

    def _parse_arguments(self, raw_arguments: str) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid tool arguments: {raw_arguments}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Tool arguments must decode to a JSON object.")
        return parsed

    def _tool_to_api_payload(self, tool: AgentTool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
