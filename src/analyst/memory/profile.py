from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileFactUpdate:
    key: str
    value: object
    confidence: float


_WATCHLIST_PATTERNS = {
    "fed": re.compile(r"\b(fed|fomc|powell|美联储)\b", re.IGNORECASE),
    "cpi": re.compile(r"\b(cpi|inflation|通胀)\b", re.IGNORECASE),
    "jobs": re.compile(r"\b(nfp|payroll|employment|非农|就业)\b", re.IGNORECASE),
    "rates": re.compile(r"\b(rates?|yield|利率|美债)\b", re.IGNORECASE),
    "crypto": re.compile(r"\b(bitcoin|btc|eth|crypto|加密)\b", re.IGNORECASE),
    "gold": re.compile(r"\b(gold|黄金)\b", re.IGNORECASE),
    "oil": re.compile(r"\b(oil|原油)\b", re.IGNORECASE),
    "equities": re.compile(r"\b(a股|港股|美股|equity|stocks?|nasdaq|spx)\b", re.IGNORECASE),
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


def extract_profile_fact_updates(text: str) -> list[ProfileFactUpdate]:
    updates: list[ProfileFactUpdate] = []
    stripped = text.strip()
    if not stripped:
        return updates

    language = "zh" if re.search(r"[\u4e00-\u9fff]", stripped) else "en"
    updates.append(ProfileFactUpdate(key="preferred_language", value=language, confidence=0.9))

    watchlist = [name for name, pattern in _WATCHLIST_PATTERNS.items() if pattern.search(stripped)]
    if watchlist:
        updates.append(ProfileFactUpdate(key="watchlist_topics", value=watchlist, confidence=0.78))

    for value, pattern in _STYLE_PATTERNS.items():
        if pattern.search(stripped):
            updates.append(ProfileFactUpdate(key="response_style", value=value, confidence=0.74))
            break

    for value, pattern in _RISK_PATTERNS.items():
        if pattern.search(stripped):
            updates.append(ProfileFactUpdate(key="risk_style", value=value, confidence=0.72))
            break

    for value, pattern in _HORIZON_PATTERNS.items():
        if pattern.search(stripped):
            updates.append(ProfileFactUpdate(key="investment_horizon", value=value, confidence=0.68))
            break

    return updates
