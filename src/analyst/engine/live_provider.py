from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests

from analyst.env import get_env_value

from .live_types import AgentTool, CompletionResult, ConversationMessage, MessageContent, ToolCall

OPENROUTER_PLATFORM = "openrouter"
ANTHROPIC_PLATFORM = "anthropic"
CLAUDE_CODE_PLATFORM = "claude_code"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
DEFAULT_CLAUDE_CODE_MODEL = "sonnet"


def resolve_llm_platform() -> str:
    raw = get_env_value(
        "ANALYST_LLM_PLATFORM",
        "ANALYST_LLM_PROVIDER",
        default=OPENROUTER_PLATFORM,
    )
    normalized = raw.strip().lower().replace("-", "_")
    aliases = {
        "openrouter": OPENROUTER_PLATFORM,
        "anthropic": ANTHROPIC_PLATFORM,
        "claude": ANTHROPIC_PLATFORM,
        "anthropic_compat": ANTHROPIC_PLATFORM,
        "claude_code": CLAUDE_CODE_PLATFORM,
        "claude-code": CLAUDE_CODE_PLATFORM,
        "claude_code_cli": CLAUDE_CODE_PLATFORM,
    }
    return aliases.get(normalized, OPENROUTER_PLATFORM)


def _unique_keys(*keys: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for key in keys:
        if key and key not in ordered:
            ordered.append(key)
    return tuple(ordered)


def _anthropic_model_keys(model_keys: tuple[str, ...]) -> tuple[str, ...]:
    derived: list[str] = []
    for key in model_keys:
        if key.endswith("_OPENROUTER_MODEL"):
            derived.append(key.replace("_OPENROUTER_MODEL", "_ANTHROPIC_MODEL"))
            continue
        if key.startswith("ANALYST_") and key.endswith("_MODEL") and "_ANTHROPIC_" not in key:
            derived.append(f"{key[:-6]}_ANTHROPIC_MODEL")
    return _unique_keys(
        *derived,
        "ANALYST_ANTHROPIC_MODEL",
        "ANTHROPIC_MODEL",
        "CLAUDE_CODE_MODEL",
        "LLM_MODEL",
    )


def _claude_code_model_keys(model_keys: tuple[str, ...]) -> tuple[str, ...]:
    derived: list[str] = []
    for key in model_keys:
        if key.endswith("_OPENROUTER_MODEL"):
            derived.append(key.replace("_OPENROUTER_MODEL", "_CLAUDE_CODE_MODEL"))
            continue
        if key.startswith("ANALYST_") and key.endswith("_MODEL") and "_CLAUDE_CODE_" not in key:
            derived.append(f"{key[:-6]}_CLAUDE_CODE_MODEL")
    return _unique_keys(
        *derived,
        "ANALYST_CLAUDE_CODE_MODEL",
        "CLAUDE_CODE_MODEL",
        "LLM_MODEL",
    )


def _default_model_for_platform(platform: str, default_model: str) -> str:
    if platform == CLAUDE_CODE_PLATFORM:
        if default_model and "/" not in default_model:
            return default_model
        return DEFAULT_CLAUDE_CODE_MODEL
    if platform != ANTHROPIC_PLATFORM:
        return default_model
    if default_model and "/" not in default_model:
        return default_model
    return DEFAULT_ANTHROPIC_MODEL


def _normalize_model(platform: str, model: str, default_model: str) -> str:
    value = model.strip()
    if platform == CLAUDE_CODE_PLATFORM:
        if not value:
            return _default_model_for_platform(platform, default_model)
        if value.startswith("anthropic/"):
            return value.split("/", 1)[1]
        if "/" in value:
            return _default_model_for_platform(platform, default_model)
        return value
    if platform != ANTHROPIC_PLATFORM:
        return value or default_model
    if not value:
        return _default_model_for_platform(platform, default_model)
    if value.startswith("anthropic/"):
        return value.split("/", 1)[1]
    if "/" in value:
        return _default_model_for_platform(platform, default_model)
    return value


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    site_url: str = ""
    app_name: str = "analyst-project"
    timeout_seconds: int = 60
    provider_name: str = OPENROUTER_PLATFORM

    @classmethod
    def from_env(
        cls,
        *,
        model_keys: tuple[str, ...] = ("ANALYST_OPENROUTER_MODEL", "LLM_MODEL"),
        default_model: str = "anthropic/claude-3.5-sonnet",
    ) -> "OpenRouterConfig":
        platform = resolve_llm_platform()
        if platform == CLAUDE_CODE_PLATFORM:
            raise RuntimeError("Claude Code uses build_llm_provider_from_env(), not OpenRouterConfig.from_env().")
        if platform == ANTHROPIC_PLATFORM:
            api_key = get_env_value("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is required for Anthropic chat completions."
                )
            raw_model = get_env_value(
                *_anthropic_model_keys(model_keys),
                default="",
            )
            return cls(
                api_key=api_key,
                model=_normalize_model(platform, raw_model, default_model),
                base_url=get_env_value("ANTHROPIC_BASE_URL", default=DEFAULT_ANTHROPIC_BASE_URL),
                site_url="",
                app_name="",
                provider_name=platform,
            )

        api_key = get_env_value("OPENROUTER_API_KEY", "LLM_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY or LLM_API_KEY is required for live engine commands.")
        model = get_env_value(*model_keys, default=default_model)
        return cls(
            api_key=api_key,
            model=model,
            base_url=get_env_value("OPENROUTER_BASE_URL", "LLM_BASE_URL", default=DEFAULT_OPENROUTER_BASE_URL),
            site_url=os.environ.get("OPENROUTER_SITE_URL", ""),
            app_name=os.environ.get("OPENROUTER_APP_NAME", "analyst-project"),
            provider_name=platform,
        )


@dataclass(frozen=True)
class ClaudeCodeConfig:
    oauth_token: str
    model: str = DEFAULT_CLAUDE_CODE_MODEL
    cli_path: str = "claude"
    timeout_seconds: int = 180

    @classmethod
    def from_env(
        cls,
        *,
        model_keys: tuple[str, ...] = ("ANALYST_OPENROUTER_MODEL", "LLM_MODEL"),
        default_model: str = DEFAULT_CLAUDE_CODE_MODEL,
    ) -> "ClaudeCodeConfig":
        oauth_token = get_env_value("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_KEY")
        if not oauth_token:
            raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN is required for the Claude Code provider.")
        raw_model = get_env_value(*_claude_code_model_keys(model_keys), default="")
        return cls(
            oauth_token=oauth_token,
            model=_normalize_model(CLAUDE_CODE_PLATFORM, raw_model, default_model),
            cli_path=get_env_value("CLAUDE_CODE_CLI_PATH", default="claude"),
            timeout_seconds=_safe_int(
                get_env_value("ANALYST_CLAUDE_CODE_TIMEOUT_SECONDS", default="180"),
                default=180,
            ),
        )


def _safe_int(raw_value: str, *, default: int) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def build_llm_provider_from_env(
    *,
    model_keys: tuple[str, ...] = ("ANALYST_OPENROUTER_MODEL", "LLM_MODEL"),
    default_model: str = "anthropic/claude-3.5-sonnet",
):
    platform = resolve_llm_platform()
    if platform == CLAUDE_CODE_PLATFORM:
        return ClaudeCodeProvider(ClaudeCodeConfig.from_env(model_keys=model_keys, default_model=default_model))
    return OpenRouterProvider(OpenRouterConfig.from_env(model_keys=model_keys, default_model=default_model))


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
            raise RuntimeError(
                f"{self.config.provider_name} chat completions error {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        choices = body.get("choices", [])
        if not choices:
            raise RuntimeError(f"{self.config.provider_name} returned no choices.")
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
            payload.append({"role": message.role, "content": self._normalize_content(message.content)})
        return payload

    def _normalize_content(self, content: MessageContent | None) -> MessageContent:
        if content is None:
            return ""
        return content

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


class ClaudeCodeProvider:
    def __init__(
        self,
        config: ClaudeCodeConfig,
        *,
        runner: Any | None = None,
    ) -> None:
        self.config = config
        self._runner = runner or subprocess.run

    def complete(
        self,
        *,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[AgentTool],
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        del max_tokens, temperature
        schema = self._response_schema(tools)
        command = [
            self.config.cli_path,
            "-p",
            "--model",
            self.config.model,
            "--tools",
            "",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            "--system-prompt",
            self._build_system_prompt(system_prompt, tools),
            "--no-session-persistence",
            self._build_prompt(messages, tools),
        ]
        env = os.environ.copy()
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self.config.oauth_token
        completed = self._runner(
            command,
            capture_output=True,
            text=True,
            env=env,
            timeout=self.config.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"Claude Code error {completed.returncode}: {stderr[:500]}")
        body = self._parse_cli_payload(completed.stdout)
        return self._decode_completion(body, tools)

    def _build_system_prompt(self, system_prompt: str, tools: list[AgentTool]) -> str:
        loop_contract = (
            "You are the reasoning engine inside an external Python agent loop.\n"
            "You cannot execute tools yourself. The host application will execute any tool calls you request.\n"
            "Do not mention the host application, JSON schema, or hidden coordination protocol in the final answer.\n"
            "When tool results appear in the conversation transcript, treat them as authoritative.\n"
        )
        if tools:
            loop_contract += (
                "If you need external information or actions, set action to tool_call and request at most one tool per turn.\n"
                "When requesting a tool, return only a valid tool name and a compact JSON object encoded as tool_arguments_json.\n"
                "If you already have enough information, set action to final and place the user-visible reply in final_text.\n"
            )
        else:
            loop_contract += "No tools are available in this turn. Return a final answer directly.\n"
        return f"{system_prompt}\n\n{loop_contract}".strip()

    def _build_prompt(self, messages: list[ConversationMessage], tools: list[AgentTool]) -> str:
        parts = [
            "Conversation transcript:",
            self._render_messages(messages),
        ]
        if tools:
            tool_lines = ["Available tools:"]
            for tool in tools:
                params = json.dumps(tool.parameters, ensure_ascii=True, sort_keys=True)
                tool_lines.append(f"- {tool.name}: {tool.description}")
                tool_lines.append(f"  parameters={params}")
            parts.append("\n".join(tool_lines))
            parts.append(
                "Choose the next step. Either return a final answer or request tool calls. "
                "Prefer the minimum number of tool calls needed."
            )
        else:
            parts.append("Return the best possible final answer.")
        return "\n\n".join(part for part in parts if part.strip())

    def _render_messages(self, messages: list[ConversationMessage]) -> str:
        rendered: list[str] = []
        for message in messages:
            if message.role == "assistant" and message.tool_calls:
                if message.content:
                    rendered.append(f"Assistant:\n{self._render_content(message.content)}")
                tool_lines = ["Assistant requested tool calls:"]
                for tool_call in message.tool_calls:
                    args = json.dumps(tool_call.arguments, ensure_ascii=True, sort_keys=True)
                    tool_lines.append(
                        f"- id={tool_call.call_id} name={tool_call.name} arguments={args}"
                    )
                rendered.append("\n".join(tool_lines))
                continue
            if message.role == "tool":
                tool_name = message.tool_name or "tool"
                call_id = message.tool_call_id or "unknown"
                rendered.append(
                    f"Tool result ({tool_name}, call_id={call_id}):\n{self._render_content(message.content)}"
                )
                continue
            rendered.append(f"{message.role.capitalize()}:\n{self._render_content(message.content)}")
        return "\n\n".join(rendered)

    def _render_content(self, content: MessageContent | None) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        parts: list[str] = []
        for item in content:
            item_type = str(item.get("type", ""))
            if item_type == "text":
                parts.append(str(item.get("text", "")))
                continue
            if item_type == "image_url":
                url = ""
                image_url = item.get("image_url")
                if isinstance(image_url, dict):
                    url = str(image_url.get("url", ""))
                elif isinstance(image_url, str):
                    url = image_url
                if url.startswith("data:"):
                    parts.append("[Image attachment omitted: inline data URL]")
                elif url:
                    parts.append(f"[Image attachment: {url}]")
                else:
                    parts.append("[Image attachment]")
                continue
            parts.append(f"[Unsupported content block type: {item_type or 'unknown'}]")
        return "\n".join(part for part in parts if part)

    def _response_schema(self, tools: list[AgentTool]) -> dict[str, Any]:
        if not tools:
            return {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "final_text": {"type": "string"},
                },
                "required": ["final_text"],
            }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["final", "tool_call"]},
                "final_text": {"type": "string"},
                "tool_name": {"type": "string", "enum": ["", *[tool.name for tool in tools]]},
                "tool_arguments_json": {"type": "string"},
            },
            "required": ["action", "final_text", "tool_name", "tool_arguments_json"],
        }

    def _parse_cli_payload(self, raw_stdout: str) -> dict[str, Any]:
        text = raw_stdout.strip()
        if not text:
            raise RuntimeError("Claude Code returned empty stdout.")
        for candidate in reversed([line for line in text.splitlines() if line.strip()]):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise RuntimeError(f"Claude Code returned non-JSON output: {text[:500]}")

    def _decode_completion(self, body: dict[str, Any], tools: list[AgentTool]) -> CompletionResult:
        structured = body.get("structured_output")
        if tools:
            if not isinstance(structured, dict):
                raise RuntimeError(f"Claude Code returned no structured_output: {json.dumps(body)[:500]}")
            action = str(structured.get("action", "")).strip()
            final_text = str(structured.get("final_text", "") or "")
            if action == "final":
                return CompletionResult(
                    message=ConversationMessage(role="assistant", content=final_text),
                    raw_response=body,
                )
            if action != "tool_call":
                raise RuntimeError(f"Claude Code returned invalid action: {action or '<empty>'}")
            tool_name = str(structured.get("tool_name", "")).strip()
            if not tool_name:
                raise RuntimeError("Claude Code requested tool_call but returned no tool_name.")
            raw_arguments = str(structured.get("tool_arguments_json", "") or "").strip()
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Claude Code returned invalid tool_arguments_json: {raw_arguments}") from exc
            if not isinstance(arguments, dict):
                raise RuntimeError("Claude Code tool_arguments_json must decode to a JSON object.")
            tool_calls = [
                ToolCall(
                    call_id=f"claude_code_call_{uuid4().hex[:12]}",
                    name=tool_name,
                    arguments=arguments,
                )
            ]
            content = final_text or None
            return CompletionResult(
                message=ConversationMessage(role="assistant", content=content, tool_calls=tool_calls),
                raw_response=body,
            )
        final_text = ""
        if isinstance(structured, dict):
            final_text = str(structured.get("final_text", "") or "")
        if not final_text:
            final_text = str(body.get("result", "") or "")
        return CompletionResult(
            message=ConversationMessage(role="assistant", content=final_text),
            raw_response=body,
        )
