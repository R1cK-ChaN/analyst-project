from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
from analyst.engine.live_provider import OpenRouterConfig
from analyst.engine.live_types import CompletionResult, ConversationMessage
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
