from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class GovReportItem:
    source: str            # "gov_bls", "gov_nbs", etc.
    source_id: str         # "us_bls_cpi", "cn_stats_gdp", etc.
    title: str
    url: str
    published_at: str      # ISO 8601 UTC when available, otherwise ISO date
    institution: str       # "BLS", "国家统计局", etc.
    country: str           # "US", "CN", "JP", "EU"
    language: str          # "en", "zh"
    data_category: str     # "inflation", "gdp", etc.
    importance: str = ""   # "high", "medium", "low"
    description: str = ""
    content_markdown: str = ""
    raw_json: dict = field(default_factory=dict)
    published_precision: str = ""

