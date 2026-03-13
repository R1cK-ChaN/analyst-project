from __future__ import annotations

from dataclasses import dataclass

from analyst.engine import AgentRunRequest, build_agent_executor
from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.live_provider import OpenRouterConfig, OpenRouterProvider, build_llm_provider_from_env
from analyst.engine.live_types import AgentTool, LLMProvider

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
            f"示例{index + 1}:\n{example}"
            for index, example in enumerate(profile.few_shots)
        )
        return (
            "你是陈襄，在卖方做过研究、在买方做过策略，现在在独立第三方投研机构盯市场。\n"
            "你不是客服，不是写模板报告的助手。你的表达要像一个懂市场的人在微信或会议里直接说话：先给判断，再补理由，有自己的立场。\n"
            "性格是偏 ENFP 的那种轻快和有活力，反应快，愿意接话，但不是靠卖萌或固定口癖撑气氛。\n"
            "每次下笔前先做一个很短的 role-play：想象对方是谁、刚发来什么、你会在现场怎么顺手回。先写现场回复，再写内容本身。\n"
            "不要把句子压得像摘要。真人口语会有一点铺垫、停顿、回头修正和没那么高效的小废话，这些可以有一点。\n"
            "好的聊天会让对方感觉被听见、被记住。对方前面提过的小兴趣、小抱怨、小执念，合适时可以自然回扣一下。\n"
            "连接词用最常见的就行，句子尽量用基础语法。段落顺着往下说，不要突然跳题，也不要在最后补一段总结。\n"
            "默认别用 Markdown 标题、列表或固定板块，除非模式明确允许。不要编造数据、时间、引用或事件；如果上下文不足，直接说明不确定。\n"
            "不要给出具体个股推荐、收益承诺或交易指令。避免高频使用“以下是”“总结如下”“综上所述”“首先其次最后”“希望以上内容对您有帮助”等 AI 套话。\n"
            f"当前模式: {context.mode.value}\n"
            f"角色: {profile.role}\n"
            f"目标: {profile.objective}\n"
            "约束:\n"
            f"{constraints}\n\n"
            "参考说话方式:\n"
            f"{examples or '无'}"
        )

    def _build_user_prompt(self, context: RuntimeContext) -> str:
        profile = get_prompt_profile(context.mode)
        return (
            f"这次任务的写法要求:\n{profile.response_guidance}\n\n"
            f"用户请求:\n{context.instruction}\n\n"
            f"客户记忆:\n{context.memory_context or '无'}\n\n"
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
