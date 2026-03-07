from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClientProfileUpdate:
    preferred_language: str | None = None
    watchlist_topics: list[str] = field(default_factory=list)
    response_style: str | None = None
    risk_appetite: str | None = None
    investment_horizon: str | None = None


_WATCHLIST_PATTERNS = {
    "fed": re.compile(r"(?:\b(?:fed|fomc|powell)\b|美联储)", re.IGNORECASE),
    "cpi": re.compile(r"(?:\b(?:cpi|inflation)\b|通胀)", re.IGNORECASE),
    "jobs": re.compile(r"(?:\b(?:nfp|payroll|employment)\b|非农|就业)", re.IGNORECASE),
    "rates": re.compile(r"(?:\b(?:rates?|yield)\b|利率|美债)", re.IGNORECASE),
    "crypto": re.compile(r"(?:\b(?:bitcoin|btc|eth|crypto)\b|加密)", re.IGNORECASE),
    "gold": re.compile(r"(?:\b(?:gold)\b|黄金)", re.IGNORECASE),
    "oil": re.compile(r"(?:\b(?:oil)\b|原油)", re.IGNORECASE),
    "equities": re.compile(r"(?:\b(?:equity|stocks?|nasdaq|spx)\b|A股|港股|美股)", re.IGNORECASE),
}

_STYLE_PATTERNS = {
    "concise": re.compile(r"(简短|简洁|一句话|短一点|concise|brief)", re.IGNORECASE),
    "detailed": re.compile(r"(详细|展开|多写一点|详细点|detailed)", re.IGNORECASE),
}

_RISK_PATTERNS = {
    "conservative": re.compile(r"(稳健|保守|低风险|conservative)", re.IGNORECASE),
    "aggressive": re.compile(r"(进取|激进|高弹性|aggressive)", re.IGNORECASE),
}

_HORIZON_PATTERNS = {
    "short_term": re.compile(r"(短线|今天|本周|short[- ]?term)", re.IGNORECASE),
    "long_term": re.compile(r"(长线|中长期|季度|long[- ]?term)", re.IGNORECASE),
}


def extract_client_profile_update(text: str) -> ClientProfileUpdate:
    stripped = text.strip()
    if not stripped:
        return ClientProfileUpdate()

    preferred_language = "zh" if re.search(r"[\u4e00-\u9fff]", stripped) else "en"
    watchlist_topics = [name for name, pattern in _WATCHLIST_PATTERNS.items() if pattern.search(stripped)]

    response_style = None
    for value, pattern in _STYLE_PATTERNS.items():
        if pattern.search(stripped):
            response_style = value
            break

    risk_appetite = None
    for value, pattern in _RISK_PATTERNS.items():
        if pattern.search(stripped):
            risk_appetite = value
            break

    investment_horizon = None
    for value, pattern in _HORIZON_PATTERNS.items():
        if pattern.search(stripped):
            investment_horizon = value
            break

    return ClientProfileUpdate(
        preferred_language=preferred_language,
        watchlist_topics=watchlist_topics,
        response_style=response_style,
        risk_appetite=risk_appetite,
        investment_horizon=investment_horizon,
    )
