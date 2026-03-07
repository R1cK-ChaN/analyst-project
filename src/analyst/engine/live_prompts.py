from __future__ import annotations

from analyst.storage import StoredEventRecord


SYSTEM_PROMPT = """你是一位顶级投资银行的高级宏观研究策略师。

你的目标读者是中国证券公司的财富管理团队、客户经理和基金经理。
你的工作方式必须像机构宏观研究员，而不是聊天机器人。

规则:
- 先给核心结论，再解释数据。
- 回答必须是简体中文。
- 必须把宏观事件和市场叙事联系起来，而不是复述数据。
- 必须说明跨资产影响，至少覆盖利率、美元、股票和大类风险偏好。
- 可以也应该使用工具查询最新上下文。
- 不给出具体个股买卖建议。
- 最终输出必须包含结构化的宏观状态 JSON，放在单独的 ```json 代码块中。
- JSON 要反映当前宏观框架，而不是机械复制历史状态。
"""


JSON_FORMAT_INSTRUCTIONS = """JSON 必须包含这些字段:
{
  "risk_appetite": 0.0-1.0,
  "fed_hawkishness": 0.0-1.0,
  "growth_momentum": 0.0-1.0,
  "inflation_trend": "accelerating|stable|decelerating",
  "liquidity_conditions": "tightening|neutral|easing",
  "dominant_narrative": "string",
  "narrative_risk": "string",
  "regime_label": "risk_on|neutral|risk_off",
  "confidence": 0.0-1.0,
  "cross_asset_implications": {
    "rates": "string",
    "dollar": "string",
    "a_shares": "string",
    "hk_stocks": "string",
    "us_equities": "string",
    "commodities": "string",
    "crypto": "string"
  },
  "last_updated": "ISO datetime",
  "trigger": "string"
}
"""


def flash_prompt(trigger_event: StoredEventRecord, baseline_regime: dict[str, object]) -> str:
    return f"""任务: 生成一篇数据快评。

触发事件:
- 国家: {trigger_event.country}
- 指标: {trigger_event.indicator}
- 时间: {trigger_event.datetime_utc}
- 重要性: {trigger_event.importance}
- 实际值: {trigger_event.actual or "待公布"}
- 预期值: {trigger_event.forecast or "未知"}
- 前值: {trigger_event.previous or "未知"}
- 惊喜值: {trigger_event.surprise if trigger_event.surprise is not None else "未知"}

当前基线宏观状态:
{baseline_regime}

要求:
- 先使用工具补齐上下文，然后再给最终回答。
- 正文使用这些小节: 一句话总结 / 核心数据 / 为什么重要 / 跨资产影响 / 接下来关注。
- 正文之后必须输出 JSON。

{JSON_FORMAT_INSTRUCTIONS}
"""


def briefing_prompt(topline_events: str, baseline_regime: dict[str, object]) -> str:
    return f"""任务: 生成一篇早盘速递。

已知待关注事件:
{topline_events}

当前基线宏观状态:
{baseline_regime}

要求:
- 先使用工具检查隔夜市场、近期数据和联储沟通，再生成正文。
- 正文结构: 一句话总结 / 隔夜要点 / 今日关注 / 跨资产状态 / 体系评估。
- 输出必须简洁、像 sell-side morning note，不要写成长报告。
- 正文之后必须输出 JSON。

{JSON_FORMAT_INSTRUCTIONS}
"""


def wrap_prompt(recent_events: str, baseline_regime: dict[str, object]) -> str:
    return f"""任务: 生成一篇收盘点评。

最近已发生事件:
{recent_events}

当前基线宏观状态:
{baseline_regime}

要求:
- 先用工具确认日内关键驱动和市场表现，再生成正文。
- 正文结构: 一句话总结 / 盘面驱动 / 宏观含义 / 接下来要看。
- 控制在精炼的机构风格，不要堆砌背景。
- 正文之后必须输出 JSON。

{JSON_FORMAT_INSTRUCTIONS}
"""


def regime_prompt(baseline_regime: dict[str, object]) -> str:
    return f"""任务: 更新当前宏观体系状态。

当前基线宏观状态:
{baseline_regime}

要求:
- 必须先使用工具核对最新数据、市场和央行沟通。
- 先输出 2-3 段文字说明当前主线，再输出 JSON。
- 不要只写抽象判断，要说明触发因素和会打破叙事的风险点。

{JSON_FORMAT_INSTRUCTIONS}
"""
