from __future__ import annotations

from dataclasses import dataclass

from analyst.delivery.soul import USER_IDENTITY_MODULE, get_prompt_profile
from analyst.engine import AgentRunRequest, build_agent_executor
from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.backends.factory import build_llm_provider_from_env
from analyst.engine.backends.openrouter import OpenRouterConfig, OpenRouterProvider
from analyst.engine.live_types import AgentTool, LLMProvider

from .service import AgentRuntime, RuntimeContext, RuntimeResult


@dataclass(frozen=True)
class OpenRouterRuntimeConfig:
    max_tokens: int = 1200
    temperature: float = 0.2
    model_keys: tuple[str, ...] = ("ANALYST_OPENROUTER_MODEL", "LLM_MODEL")
    default_model: str = "anthropic/claude-3.5-sonnet"


class OpenRouterAgentRuntime(AgentRuntime):
    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        provider_config: OpenRouterConfig | None = None,
        config: OpenRouterRuntimeConfig | None = None,
        tools: list[AgentTool] | None = None,
    ) -> None:
        self._provider = provider
        self._provider_config = provider_config
        self.config = config or OpenRouterRuntimeConfig()
        self._tools = tools or []

    def generate(self, context: RuntimeContext) -> RuntimeResult:
        system_prompt = self._build_system_prompt(context)
        user_prompt = self._build_user_prompt(context)
        executor = build_agent_executor(
            self._get_provider(),
            config=AgentLoopConfig(
                max_turns=4,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            ),
        )
        result = executor.run_turn(
            AgentRunRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tools=self._tools,
                prefer_direct_response=not self._tools,
            )
        )
        markdown = result.final_text.strip()
        if not markdown:
            raise RuntimeError("LLM provider returned empty content.")
        plain_text = self._strip_markdown(markdown)
        return RuntimeResult(markdown=markdown, plain_text=plain_text, citations=context.citations)

    def _get_provider(self) -> LLMProvider:
        if self._provider is None:
            if self._provider_config is not None:
                self._provider = OpenRouterProvider(self._provider_config)
            else:
                self._provider = build_llm_provider_from_env(
                    model_keys=self.config.model_keys,
                    default_model=self.config.default_model,
                )
        return self._provider

    def _build_system_prompt(self, context: RuntimeContext) -> str:
        profile = get_prompt_profile(context.mode)
        constraints = "\n".join(f"- {constraint}" for constraint in profile.constraints)
        examples = "\n\n".join(
            f"\u793a\u4f8b{index + 1}:\n{example}"
            for index, example in enumerate(profile.few_shots)
        )
        return (
            f"{USER_IDENTITY_MODULE.body.strip()}\n\n"
            f"\u5f53\u524d\u6a21\u5f0f: {context.mode.value}\n"
            f"\u89d2\u8272: {profile.role}\n"
            f"\u76ee\u6807: {profile.objective}\n"
            "\u7ea6\u675f:\n"
            f"{constraints}\n\n"
            "\u53c2\u8003\u8bf4\u8bdd\u65b9\u5f0f:\n"
            f"{examples or '\u65e0'}"
        )

    def _build_user_prompt(self, context: RuntimeContext) -> str:
        profile = get_prompt_profile(context.mode)
        return (
            f"\u8fd9\u6b21\u4efb\u52a1\u7684\u5199\u6cd5\u8981\u6c42:\n{profile.response_guidance}\n\n"
            f"\u7528\u6237\u8bf7\u6c42:\n{context.instruction}\n\n"
            f"\u5ba2\u6237\u8bb0\u5fc6:\n{context.memory_context or '\u65e0'}\n\n"
            f"\u5173\u6ce8\u8303\u56f4: {context.focus}\n"
            f"\u53d7\u4f17: {context.audience}\n\n"
            f"\u5e02\u573a\u5934\u6761:\n{self._render_headlines(context)}\n\n"
            f"\u5173\u952e\u4e8b\u4ef6:\n{self._render_events(context)}\n\n"
            f"\u5b8f\u89c2\u72b6\u6001\u6458\u8981:\n{context.regime_state.summary}\n\n"
            f"\u5206\u9879\u8bc4\u5206:\n{self._render_scores(context)}\n\n"
            f"\u8865\u5145\u8981\u70b9:\n{self._render_supporting_points(context)}\n\n"
            f"\u5e02\u573a\u4ef7\u683c:\n{self._render_market_prices(context)}\n\n"
            f"\u53c2\u8003\u6765\u6e90:\n{self._render_citations(context)}"
        )

    def _render_headlines(self, context: RuntimeContext) -> str:
        if not context.market_snapshot.headline_summary:
            return "- \u65e0"
        return "\n".join(f"- {headline}" for headline in context.market_snapshot.headline_summary[:6])

    def _render_events(self, context: RuntimeContext) -> str:
        if not context.market_snapshot.key_events:
            return "- \u65e0"
        return "\n".join(
            f"- {event.title}: {event.summary}"
            for event in context.market_snapshot.key_events[:6]
        )

    def _render_scores(self, context: RuntimeContext) -> str:
        return "\n".join(
            f"- {score.axis}: {score.label} ({score.score:.0f})\uff0c{score.rationale}"
            for score in context.regime_state.scores
        )

    def _render_supporting_points(self, context: RuntimeContext) -> str:
        if not context.supporting_points:
            return "- \u65e0"
        return "\n".join(f"- {point}" for point in context.supporting_points[:8])

    def _render_market_prices(self, context: RuntimeContext) -> str:
        if not context.market_snapshot.market_prices:
            return "- \u65e0"
        return "\n".join(
            f"- {name}: {value}"
            for name, value in list(context.market_snapshot.market_prices.items())[:12]
        )

    def _render_citations(self, context: RuntimeContext) -> str:
        if not context.citations:
            return "- \u65e0"
        return "\n".join(
            f"- {citation.title} | {citation.source} | {citation.url}"
            for citation in context.citations[:8]
        )

    def _strip_markdown(self, text: str) -> str:
        return (
            text.replace("#", "")
            .replace("*", "")
            .replace("`", "")
            .replace("-", "")
            .strip()
        )
