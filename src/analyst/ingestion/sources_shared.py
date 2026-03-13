from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from analyst.ingestion.scrapers.oecd import OECDClient


def _infer_publish_precision(value: str | None) -> str:
    if not value:
        return "estimated"
    if re.search(r"[T ]\d{1,2}:\d{2}", value):
        return "exact"
    return "date_only"


@dataclass(frozen=True)
class RefreshStats:
    source: str
    count: int


@dataclass(frozen=True)
class OECDSeriesConfig:
    dataflow: str
    series_id: str
    category: str
    agency_id: str = OECDClient.DEFAULT_AGENCY_ID
    version: str = "latest"
    key: str | None = None
    filters: dict[str, str] = field(default_factory=dict)


def _slugify_oecd_token(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "oecd"


def _generated_oecd_series_id(agency_id: str, dataflow_id: str, key: str) -> str:
    slug = _slugify_oecd_token(dataflow_id)[:48]
    digest = hashlib.sha1(f"{agency_id}|{dataflow_id}|{key}".encode("utf-8")).hexdigest()[:12].upper()
    return f"OECD_AUTO_{slug.upper()}_{digest}"


def _generated_oecd_config_key(dataflow_id: str, key: str) -> str:
    slug = _slugify_oecd_token(dataflow_id)[:48]
    digest = hashlib.sha1(f"{dataflow_id}|{key}".encode("utf-8")).hexdigest()[:10]
    return f"auto_{slug}_{digest}"


def render_oecd_series_configs(series_configs: dict[str, OECDSeriesConfig]) -> str:
    lines = ["generated_oecd_series = {"]
    for config_key, cfg in sorted(series_configs.items()):
        lines.append(f'    "{config_key}": OECDSeriesConfig(')
        lines.append(f'        dataflow="{cfg.dataflow}",')
        lines.append(f'        series_id="{cfg.series_id}",')
        lines.append(f'        category="{cfg.category}",')
        lines.append(f'        agency_id="{cfg.agency_id}",')
        lines.append(f'        version="{cfg.version}",')
        if cfg.key is not None:
            lines.append(f'        key="{cfg.key}",')
        if cfg.filters:
            lines.append("        filters={")
            for dim_id, dim_value in sorted(cfg.filters.items()):
                lines.append(f'            "{dim_id}": "{dim_value}",')
            lines.append("        },")
        lines.append("    ),")
    lines.append("}")
    return "\n".join(lines)
