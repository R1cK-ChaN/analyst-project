from __future__ import annotations

from dataclasses import dataclass

from analyst.contracts import InteractionMode
from analyst.engine.live_provider import OpenRouterConfig, OpenRouterProvider
from analyst.engine.live_types import ConversationMessage, LLMProvider

from .prompts import get_prompt_profile
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
    ) -> None:
        self._provider = provider
        self._provider_config = provider_config
        self.config = config or OpenRouterRuntimeConfig()

    def generate(self, context: RuntimeContext) -> RuntimeResult:
        completion = self._get_provider().complete(
            system_prompt=self._build_system_prompt(context),
            messages=[ConversationMessage(role="user", content=self._build_user_prompt(context))],
            tools=[],
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )
        markdown = (completion.message.content or "").strip()
        if not markdown:
            raise RuntimeError("OpenRouter returned empty content.")
        plain_text = self._strip_markdown(markdown)
        return RuntimeResult(markdown=markdown, plain_text=plain_text, citations=context.citations)

    def _get_provider(self) -> LLMProvider:
        if self._provider is None:
            provider_config = self._provider_config or OpenRouterConfig.from_env(
                model_keys=self.config.model_keys,
                default_model=self.config.default_model,
            )
            self._provider = OpenRouterProvider(provider_config)
        return self._provider

    def _build_system_prompt(self, context: RuntimeContext) -> str:
        profile = get_prompt_profile(context.mode)
        constraints = "\n".join(f"- {constraint}" for constraint in profile.constraints)
        return (
            "你是 Analyst，一名服务于客户经理的中文宏观研究助手。\n"
            "你的任务是根据给定上下文输出高质量、可复核、结构清晰的中文 Markdown。\n"
            "不要编造数据、时间、引用或事件；如果上下文不足，明确说明不确定性。\n"
            "不要给出具体个股推荐、收益承诺或交易指令。\n"
            f"当前模式: {context.mode.value}\n"
            f"角色: {profile.role}\n"
            f"目标: {profile.objective}\n"
            "约束:\n"
            f"{constraints}"
        )

    def _build_user_prompt(self, context: RuntimeContext) -> str:
        instruction_lines = {
            InteractionMode.QA: (
                "请直接回答用户问题，并按以下结构输出：\n"
                "### 直接回答\n"
                "### 依据\n"
                "### 当前宏观状态\n"
                "### 风险提示"
            ),
            InteractionMode.DRAFT: (
                "请起草一份客户经理可编辑的外发初稿，并按以下结构输出：\n"
                "### 客户消息初稿\n"
                "### 可对客户这样解释\n"
                "### 风险提示"
            ),
            InteractionMode.MEETING_PREP: (
                "请整理成客户沟通准备材料，并按以下结构输出：\n"
                "### 客户沟通要点\n"
                "### 客户可能会问\n"
                "### 建议回应口径"
            ),
            InteractionMode.REGIME: (
                "请总结当前宏观状态，并按以下结构输出：\n"
                "### 状态总结\n"
                "### 关键驱动\n"
                "### 分项评分\n"
                "### 市场快照\n"
                "### 需要跟踪"
            ),
            InteractionMode.PREMARKET: (
                "请生成一份早盘速递，并按以下结构输出：\n"
                "### 隔夜重点\n"
                "### 今日要看\n"
                "### 当前框架\n"
                "### 风险提示"
            ),
        }
        prompt = instruction_lines.get(context.mode, instruction_lines[InteractionMode.QA])
        return (
            f"{prompt}\n\n"
            f"用户请求: {context.instruction}\n"
            f"已知记忆:\n{context.memory_context or '- 无'}\n\n"
            f"关注范围: {context.focus}\n"
            f"受众: {context.audience}\n\n"
            f"市场头条:\n{self._render_headlines(context)}\n\n"
            f"关键事件:\n{self._render_events(context)}\n\n"
            f"宏观状态摘要:\n{context.regime_state.summary}\n\n"
            f"分项评分:\n{self._render_scores(context)}\n\n"
            f"补充要点:\n{self._render_supporting_points(context)}\n\n"
            f"市场价格:\n{self._render_market_prices(context)}\n\n"
            f"参考来源:\n{self._render_citations(context)}"
        )

    def _render_headlines(self, context: RuntimeContext) -> str:
        if not context.market_snapshot.headline_summary:
            return "- 无"
        return "\n".join(f"- {headline}" for headline in context.market_snapshot.headline_summary[:6])

    def _render_events(self, context: RuntimeContext) -> str:
        if not context.market_snapshot.key_events:
            return "- 无"
        return "\n".join(
            f"- {event.title}: {event.summary}"
            for event in context.market_snapshot.key_events[:6]
        )

    def _render_scores(self, context: RuntimeContext) -> str:
        return "\n".join(
            f"- {score.axis}: {score.label} ({score.score:.0f})，{score.rationale}"
            for score in context.regime_state.scores
        )

    def _render_supporting_points(self, context: RuntimeContext) -> str:
        if not context.supporting_points:
            return "- 无"
        return "\n".join(f"- {point}" for point in context.supporting_points[:8])

    def _render_market_prices(self, context: RuntimeContext) -> str:
        if not context.market_snapshot.market_prices:
            return "- 无"
        return "\n".join(
            f"- {name}: {value}"
            for name, value in list(context.market_snapshot.market_prices.items())[:12]
        )

    def _render_citations(self, context: RuntimeContext) -> str:
        if not context.citations:
            return "- 无"
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
