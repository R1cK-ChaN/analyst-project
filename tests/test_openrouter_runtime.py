from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.contracts import (
    InteractionMode,
    MarketSnapshot,
    RegimeScore,
    RegimeState,
    SourceReference,
    utc_now,
)
from analyst.engine.live_provider import (
    ClaudeCodeConfig,
    ClaudeCodeProvider,
    OpenRouterConfig,
    OpenRouterProvider,
    build_llm_provider_from_env,
)
from analyst.engine.live_types import AgentTool, CompletionResult, ConversationMessage
from analyst.mcp.bridge import ClaudeCodeMcpConfig
from analyst.engine.service import OpenRouterAnalystEngine
from analyst.env import clear_env_cache
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.runtime import OpenRouterAgentRuntime, OpenRouterRuntimeConfig, RuntimeContext


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("No more fake responses configured.")
        return CompletionResult(
            message=ConversationMessage(role="assistant", content=self.responses.pop(0)),
            raw_response={},
        )


def make_context(mode: InteractionMode = InteractionMode.QA) -> RuntimeContext:
    regime_state = RegimeState(
        as_of=utc_now(),
        summary="当前风险偏好偏谨慎，通胀交易仍压制降息预期。",
        scores=[
            RegimeScore(axis="risk_sentiment", score=42.0, label="偏弱风险偏好", rationale="长端利率偏高。"),
            RegimeScore(axis="inflation_pressure", score=66.0, label="偏热通胀", rationale="核心通胀黏性。"),
        ],
        evidence=[],
        confidence=0.7,
    )
    snapshot = MarketSnapshot(
        as_of=utc_now(),
        focus="global",
        headline_summary=["美国CPI高于预期", "美债收益率上行"],
        key_events=[],
        market_prices={"US10Y": 4.35, "DXY": 104.2},
        citations=[
            SourceReference(title="CPI release", url="https://example.com/cpi", source="BLS"),
        ],
    )
    return RuntimeContext(
        mode=mode,
        user_id="test-user",
        instruction="请给我一份宏观解释。",
        memory_context="",
        focus="global",
        audience="internal_rm",
        market_snapshot=snapshot,
        regime_state=regime_state,
        supporting_points=["今晚关键看美国CPI和利率路径。"],
        citations=snapshot.citations,
    )


class OpenRouterConfigTest(unittest.TestCase):
    def test_from_env_supports_telegram_specific_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")
            with patch("analyst.env.DEFAULT_ENV_FILES", (env_file,)):
                with patch.dict("os.environ", {}, clear=True):
                    clear_env_cache()
                    config = OpenRouterConfig.from_env(
                        model_keys=("ANALYST_TELEGRAM_OPENROUTER_MODEL", "ANALYST_OPENROUTER_MODEL"),
                        default_model="google/gemini-3.1-flash-lite-preview",
                    )
            self.assertEqual(config.model, "google/gemini-3.1-flash-lite-preview")

    def test_from_env_supports_anthropic_compat_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "ANALYST_LLM_PLATFORM=anthropic",
                        "ANTHROPIC_API_KEY=test-anthropic-key",
                        "ANALYST_TELEGRAM_OPENROUTER_MODEL=google/gemini-3.1-flash-lite-preview",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("analyst.env.DEFAULT_ENV_FILES", (env_file,)):
                with patch.dict("os.environ", {}, clear=True):
                    clear_env_cache()
                    config = OpenRouterConfig.from_env(
                        model_keys=("ANALYST_TELEGRAM_OPENROUTER_MODEL", "ANALYST_OPENROUTER_MODEL"),
                        default_model="google/gemini-3.1-flash-lite-preview",
                    )
            self.assertEqual(config.api_key, "test-anthropic-key")
            self.assertEqual(config.base_url, "https://api.anthropic.com/v1")
            self.assertEqual(config.model, "claude-sonnet-4-20250514")
            self.assertEqual(config.provider_name, "anthropic")

    def test_provider_factory_supports_claude_code_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "ANALYST_LLM_PLATFORM=claude_code",
                        "CLAUDE_CODE_OAUTH_TOKEN=test-claude-code-token",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("analyst.env.DEFAULT_ENV_FILES", (env_file,)):
                with patch.dict("os.environ", {}, clear=True):
                    clear_env_cache()
                    provider = build_llm_provider_from_env(
                        model_keys=("ANALYST_TELEGRAM_OPENROUTER_MODEL", "ANALYST_OPENROUTER_MODEL"),
                        default_model="google/gemini-3.1-flash-lite-preview",
                    )
        self.assertIsInstance(provider, ClaudeCodeProvider)
        self.assertEqual(provider.config.model, "sonnet")


class OpenRouterRuntimeTest(unittest.TestCase):
    def test_generate_uses_provider_and_builds_plain_text(self) -> None:
        provider = FakeProvider(["### 直接回答\n- 市场仍在交易更久维持高利率。"])
        runtime = OpenRouterAgentRuntime(
            provider=provider,
            config=OpenRouterRuntimeConfig(
                max_tokens=333,
                temperature=0.1,
                default_model="google/gemini-3.1-flash-lite-preview",
            ),
        )

        result = runtime.generate(make_context())

        self.assertIn("市场仍在交易更久维持高利率。", result.markdown)
        self.assertIn("市场仍在交易更久维持高利率。", result.plain_text)
        self.assertEqual(provider.calls[0]["max_tokens"], 333)
        self.assertEqual(provider.calls[0]["temperature"], 0.1)
        self.assertEqual(provider.calls[0]["tools"], [])


class OpenRouterProviderTest(unittest.TestCase):
    def test_complete_preserves_multimodal_user_content(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "ok",
                        "tool_calls": [],
                    }
                }
            ]
        }
        session = Mock()
        session.post.return_value = response
        provider = OpenRouterProvider(
            OpenRouterConfig(api_key="test-key", model="google/gemini-3.1-flash-lite-preview"),
            session=session,
        )

        provider.complete(
            system_prompt="system",
            messages=[
                ConversationMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "look at this"},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
                    ],
                )
            ],
            tools=[],
            max_tokens=100,
            temperature=0.2,
        )

        request_payload = session.post.call_args.kwargs["data"]
        self.assertIn('"type": "image_url"', request_payload)
        self.assertIn("data:image/jpeg;base64,abc", request_payload)


class ClaudeCodeProviderTest(unittest.TestCase):
    def test_complete_without_tools_uses_structured_output(self) -> None:
        completed = Mock(returncode=0, stdout=json.dumps({"structured_output": {"final_text": "ok"}}), stderr="")
        runner = Mock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )

        result = provider.complete(
            system_prompt="system",
            messages=[ConversationMessage(role="user", content="hi")],
            tools=[],
            max_tokens=100,
            temperature=0.2,
        )

        self.assertEqual(result.message.content, "ok")
        command = runner.call_args.args[0]
        self.assertIn("--tools", command)
        self.assertIn("", command)

    def test_complete_with_tools_returns_tool_calls(self) -> None:
        completed = Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "structured_output": {
                        "action": "tool_call",
                        "final_text": "",
                        "tool_name": "web_search",
                        "tool_arguments_json": "{\"query\":\"rates today\"}",
                    }
                }
            ),
            stderr="",
        )
        runner = Mock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )
        tool = AgentTool(
            name="web_search",
            description="Search the web",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda _: {},
        )

        result = provider.complete(
            system_prompt="system",
            messages=[ConversationMessage(role="user", content="hi")],
            tools=[tool],
            max_tokens=100,
            temperature=0.2,
        )

        self.assertEqual(len(result.message.tool_calls), 1)
        self.assertEqual(result.message.tool_calls[0].name, "web_search")
        self.assertEqual(result.message.tool_calls[0].arguments, {"query": "rates today"})

    def test_complete_materializes_image_blocks_for_claude_code(self) -> None:
        completed = Mock(returncode=0, stdout="red\n", stderr="")
        runner = Mock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )

        result = provider.complete(
            system_prompt="system",
            messages=[
                ConversationMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "What color is this image? Answer one word."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jkO8AAAAASUVORK5CYII="
                            },
                        },
                    ],
                )
            ],
            tools=[],
            max_tokens=100,
            temperature=0.2,
        )

        self.assertEqual(result.message.content, "red")
        command = runner.call_args.args[0]
        self.assertIn("--add-dir", command)
        prompt = command[-1]
        marker = "Attached local image file: "
        self.assertIn(marker, prompt)
        image_line = next(line for line in prompt.splitlines() if line.startswith(marker))
        image_path = Path(image_line.split(marker, 1)[1].split(". Inspect it directly", 1)[0].strip())
        self.assertFalse(image_path.exists())

    def test_complete_native_wires_mcp_config_for_claude_code(self) -> None:
        completed = Mock(returncode=0, stdout="ok\n", stderr="")
        runner = Mock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )

        result = provider.complete_native(
            system_prompt="system",
            messages=[ConversationMessage(role="user", content="hi")],
            allowed_tools=("WebSearch", "WebFetch"),
            mcp_config=ClaudeCodeMcpConfig(tool_names=("fetch_live_news",), db_path="/tmp/test.db"),
        )

        self.assertEqual(result.message.content, "ok")
        command = runner.call_args.args[0]
        self.assertIn("--mcp-config", command)
        self.assertIn("--strict-mcp-config", command)
        self.assertIn("WebSearch,WebFetch", command)

    def test_complete_native_uses_stream_json_for_image_blocks(self) -> None:
        completed = Mock(
            returncode=0,
            stdout="\n".join(
                [
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "red"}],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "result",
                            "subtype": "success",
                            "is_error": False,
                            "result": "red",
                        }
                    ),
                ]
            ),
            stderr="",
        )
        runner = Mock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )

        result = provider.complete_native(
            system_prompt="system",
            messages=[
                ConversationMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "What color is this image? Answer one word."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jkO8AAAAASUVORK5CYII="
                            },
                        },
                    ],
                )
            ],
        )

        self.assertEqual(result.message.content, "red")
        command = runner.call_args.args[0]
        self.assertIn("--input-format", command)
        self.assertIn("--output-format", command)
        self.assertIn("--verbose", command)
        self.assertNotIn("--", command)
        stream_input = runner.call_args.kwargs["input"]
        self.assertIn('"type":"image"', stream_input)
        self.assertIn('"media_type":"image/png"', stream_input)


class OpenRouterAnalystEngineTest(unittest.TestCase):
    def test_regime_and_premarket_notes_use_runtime_output(self) -> None:
        provider = FakeProvider(
            [
                "### 状态总结\n模型版宏观状态摘要。\n\n### 关键驱动\n- 通胀继续偏黏。",
                "### 隔夜重点\n- 美债收益率继续上行。\n\n### 今日要看\n- 美国非农就业。",
            ]
        )
        runtime = OpenRouterAgentRuntime(provider=provider)
        repository = FileBackedInformationRepository()
        info_service = AnalystInformationService(repository)
        engine = OpenRouterAnalystEngine(info_service=info_service, runtime=runtime)

        regime_note = engine.get_regime_summary()
        premarket_note = engine.build_premarket_briefing()

        self.assertIn("模型版宏观状态摘要。", regime_note.body_markdown)
        self.assertEqual(regime_note.note_type, "regime_summary")
        self.assertIn("美债收益率继续上行。", premarket_note.body_markdown)
        self.assertEqual(premarket_note.note_type, "pre_market")


if __name__ == "__main__":
    unittest.main()
