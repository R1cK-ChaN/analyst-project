from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from analyst.contracts import InteractionMode, MarketSnapshot, RegimeState, SourceReference
from .prompts import get_prompt_profile


@dataclass(frozen=True)
class RuntimeContext:
    mode: InteractionMode
    user_id: str
    instruction: str
    memory_context: str
    focus: str
    audience: str
    market_snapshot: MarketSnapshot
    regime_state: RegimeState
    supporting_points: list[str] = field(default_factory=list)
    citations: list[SourceReference] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeResult:
    markdown: str
    plain_text: str
    citations: list[SourceReference] = field(default_factory=list)


class AgentRuntime(Protocol):
    def generate(self, context: RuntimeContext) -> RuntimeResult:
        ...


class TemplateAgentRuntime:
    def generate(self, context: RuntimeContext) -> RuntimeResult:
        if context.mode == InteractionMode.DRAFT:
            markdown = self._build_draft(context)
        elif context.mode == InteractionMode.FOLLOW_UP:
            markdown = self._build_follow_up(context)
        elif context.mode == InteractionMode.MEETING_PREP:
            markdown = self._build_meeting_prep(context)
        elif context.mode == InteractionMode.REGIME:
            markdown = self._build_regime(context)
        else:
            markdown = self._build_qa(context)

        plain_text = (
            markdown.replace("#", "")
            .replace("*", "")
            .replace("`", "")
            .replace("-", "")
            .strip()
        )
        return RuntimeResult(markdown=markdown, plain_text=plain_text, citations=context.citations)

    def _build_qa(self, context: RuntimeContext) -> str:
        profile = get_prompt_profile(context.mode)
        bullets = "\n".join(f"- {point}" for point in context.supporting_points[:3])
        score_lines = "\n".join(
            f"- {score.axis}: {score.label} ({score.score:.0f})"
            for score in context.regime_state.scores[:5]
        )
        memory_block = f"\n\n### 已知记忆\n{context.memory_context}" if context.memory_context else ""
        return (
            f"### 直接回答\n"
            f"围绕“{context.instruction}”，当前更合理的解释是："
            f"{context.regime_state.summary}\n\n"
            f"### 依据\n{bullets}\n\n"
            f"### 当前宏观状态\n{score_lines}\n\n"
            f"{memory_block}"
            f"{'' if not memory_block else '\n\n'}"
            f"### 使用边界\n"
            f"- 角色: {profile.role}\n"
            f"- 目标: {profile.objective}\n"
            f"- 约束: {'；'.join(profile.constraints)}"
        )

    def _build_draft(self, context: RuntimeContext) -> str:
        lead = context.supporting_points[0] if context.supporting_points else context.regime_state.summary
        watch = context.supporting_points[1] if len(context.supporting_points) > 1 else "继续观察今晚数据和利率预期变化。"
        memory_block = f"\n\n### 客户上下文\n{context.memory_context}" if context.memory_context else ""
        return (
            "### 客户消息初稿\n"
            f"今晚这组宏观信息，市场大概率还是围绕“{lead}”来交易。"
            "如果数据继续偏强，降息预期可能继续后移，权益资产短线会先交易估值压缩；"
            "如果数据回落，风险偏好会得到一定修复。\n\n"
            "### 可对客户这样解释\n"
            f"1. 先讲变化：{context.regime_state.summary}\n"
            f"2. 再讲含义：{watch}\n"
            "3. 最后讲行动：建议先用宏观框架解释波动，不急着把短线波动上升为趋势判断。"
            f"{memory_block}\n\n"
            "### 风险提示\n"
            "以上是供客户经理编辑的内部初稿，正式发送前请结合客户持仓和合规要求人工复核。"
        )

    def _build_follow_up(self, context: RuntimeContext) -> str:
        anchor = context.supporting_points[0] if context.supporting_points else context.regime_state.summary
        return (
            "### 跟进消息\n"
            f"想到你前面聊过这条线，今天新的变化主要还是 {anchor}。"
            "短线情绪有些波动，但我觉得更值得看的是节奏有没有真变。"
            "如果你要，我把今天的快评顺手发你。"
        )

    def _build_meeting_prep(self, context: RuntimeContext) -> str:
        bullets = "\n".join(f"- {point}" for point in context.supporting_points[:4])
        memory_block = f"\n\n### 客户历史偏好\n{context.memory_context}" if context.memory_context else ""
        return (
            "### 客户沟通要点\n"
            f"- 核心判断: {context.regime_state.summary}\n"
            f"{bullets}{memory_block}\n\n"
            "### 客户可能会问\n"
            "- 这是不是趋势反转信号？\n"
            "- 对权益和利率的影响哪个更快？\n"
            "- 现在要不要立刻调整仓位？\n\n"
            "### 建议回应口径\n"
            "- 先说明驱动因素，再说明时间维度，最后提醒仍需结合客户风险偏好。"
        )

    def _build_regime(self, context: RuntimeContext) -> str:
        lines = "\n".join(
            f"- {score.axis}: {score.label} ({score.score:.0f})，{score.rationale}"
            for score in context.regime_state.scores
        )
        memory_block = f"\n\n### 已知上下文\n{context.memory_context}" if context.memory_context else ""
        return (
            "### 当前宏观状态\n"
            f"{context.regime_state.summary}\n\n"
            "### 分项评分\n"
            f"{lines}\n\n"
            "### 最近驱动因素\n"
            + "\n".join(f"- {point}" for point in context.supporting_points[:3])
            + memory_block
        )
