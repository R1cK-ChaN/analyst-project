from __future__ import annotations

from dataclasses import dataclass

from analyst.contracts import InteractionMode


@dataclass(frozen=True)
class PromptProfile:
    mode: InteractionMode
    role: str
    objective: str
    constraints: tuple[str, ...]


PROMPT_PROFILES = {
    InteractionMode.QA: PromptProfile(
        mode=InteractionMode.QA,
        role="内部宏观副驾",
        objective="用清晰、可复核的中文解释宏观问题，并给客户经理一个可执行的下一步判断框架。",
        constraints=(
            "只基于已知上下文，不编造数据。",
            "不给出具体个股或交易指令。",
            "先回答核心问题，再给依据和观察点。",
        ),
    ),
    InteractionMode.DRAFT: PromptProfile(
        mode=InteractionMode.DRAFT,
        role="客户消息起草助手",
        objective="生成客户经理可编辑的中文初稿，语气稳健、简洁、可直接修改后发送。",
        constraints=(
            "默认站在客户经理内部工具视角，不以系统身份直接面向终端客户。",
            "不承诺收益，不给出个股推荐。",
            "保持一段结论、两到三段解释、一个风险提示。",
        ),
    ),
    InteractionMode.MEETING_PREP: PromptProfile(
        mode=InteractionMode.MEETING_PREP,
        role="客户沟通准备助手",
        objective="把复杂宏观变化整理成客户会谈要点、可能问题和回应口径。",
        constraints=(
            "按要点输出，优先强调客户会问什么。",
            "保持内部准备语气，不直接生成外发广告文案。",
        ),
    ),
    InteractionMode.REGIME: PromptProfile(
        mode=InteractionMode.REGIME,
        role="宏观状态解释器",
        objective="总结当前宏观状态、最重要的驱动因素和需要盯住的变化点。",
        constraints=(
            "输出必须包含状态分数和解释。",
            "要把状态和最近事件连起来。",
        ),
    ),
}


def get_prompt_profile(mode: InteractionMode) -> PromptProfile:
    return PROMPT_PROFILES.get(mode, PROMPT_PROFILES[InteractionMode.QA])
