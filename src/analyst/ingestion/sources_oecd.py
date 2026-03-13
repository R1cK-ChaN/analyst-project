from __future__ import annotations

import dataclasses
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import feedparser
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from analyst.contracts import format_epoch_iso, normalize_utc_iso, to_epoch_ms
from analyst.env import get_env_value
from analyst.ingestion.news_classify import Deduplicator
from analyst.ingestion.news_extract import extract_news_metadata
from analyst.ingestion.news_feeds import get_feeds
from analyst.ingestion.news_fetcher import ArticleFetcher
from analyst.ingestion.url_canon import canonicalize_url, content_hash
from analyst.ingestion.scrapers import (
    ForexFactoryCalendarClient,
    InvestingCalendarClient,
    TradingEconomicsCalendarClient,
)
from analyst.ingestion.scrapers.gov_report import GovReportClient, GovReportItem
from analyst.ingestion.scrapers.bis import BISClient
from analyst.ingestion.scrapers.ecb import ECBClient
from analyst.ingestion.scrapers.eia import EIAClient
from analyst.ingestion.scrapers.eurostat import EurostatClient
from analyst.ingestion.scrapers.fred import FredClient
from analyst.ingestion.scrapers.imf import IMFClient
from analyst.ingestion.scrapers.oecd import OECDClient
from analyst.ingestion.scrapers.worldbank import WorldBankClient
from analyst.ingestion.scrapers.nyfed import NYFedRatesClient
from analyst.ingestion.scrapers.rateprobability import RateProbabilityClient
from analyst.ingestion.scrapers.treasury_fiscal import TreasuryFiscalClient
from analyst.storage import (
    CentralBankCommunicationRecord,
    DocumentBlobRecord,
    DocumentExtraRecord,
    DocumentRecord,
    IndicatorObservationRecord,
    IndicatorVintageRecord,
    MarketPriceRecord,
    NewsArticleRecord,
    SQLiteEngineStore,
    StoredEventRecord,
)

logger = logging.getLogger(__name__)

from .sources_catalog import OECD_SERIES
from .sources_shared import (
    OECDSeriesConfig,
    RefreshStats,
    _generated_oecd_config_key,
    _generated_oecd_series_id,
)

class OECDIngestionClient:
    def __init__(
        self,
        client: OECDClient | None = None,
        *,
        series_configs: dict[str, OECDSeriesConfig] | None = None,
    ) -> None:
        self.client = client or OECDClient()
        self.series_configs = series_configs or OECD_SERIES
        self._resolved_configs: dict[str, tuple[str, str]] = {}

    def _resolve_request(self, cfg: OECDSeriesConfig) -> tuple[str, str]:
        cached = self._resolved_configs.get(cfg.series_id)
        if cached is not None:
            return cached

        dataflow = self.client.get_dataflow(
            cfg.dataflow,
            agency_id=cfg.agency_id,
            version=cfg.version,
        )
        if cfg.key:
            resolved = (dataflow.version, cfg.key)
        else:
            resolved = (
                dataflow.version,
                self.client.build_key(
                    cfg.dataflow,
                    cfg.filters,
                    agency_id=cfg.agency_id,
                    version=dataflow.version,
                ),
            )
        self._resolved_configs[cfg.series_id] = resolved
        return resolved

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in self.series_configs.items():
            try:
                resolved_version, resolved_key = self._resolve_request(cfg)
                observations = self.client.fetch_data(
                    cfg.dataflow,
                    agency_id=cfg.agency_id,
                    version=resolved_version,
                    key=resolved_key,
                    series_id=cfg.series_id,
                    limit=30,
                )
                fam_id = family_lookup.get(("oecd", cfg.series_id)) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="oecd",
                            date=obs.date,
                            value=obs.value,
                            metadata={
                                "category": cfg.category,
                                "dataflow": obs.dataflow,
                                "agency_id": obs.agency_id,
                                "series_key": obs.series_key or resolved_key,
                                "dimensions": obs.dimensions,
                            },
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("OECD refresh failed for %s", key, exc_info=True)
            time.sleep(1.0)
        return RefreshStats(source="oecd", count=count)

    def list_catalog_dataflows(
        self,
        *,
        query: str | None = None,
        agency_prefix: str = "OECD",
        limit: int | None = None,
    ) -> list[Any]:
        dataflows = self.client.list_dataflows(agency_id="all")
        if agency_prefix:
            dataflows = [dataflow for dataflow in dataflows if dataflow.agency_id.startswith(agency_prefix)]
        if query:
            needle = query.lower().strip()
            dataflows = [
                dataflow for dataflow in dataflows
                if needle in dataflow.id.lower()
                or needle in dataflow.name.lower()
                or needle in dataflow.description.lower()
            ]
        dataflows.sort(key=lambda item: (item.agency_id, item.id, item.version))
        if limit is not None:
            return dataflows[:limit]
        return dataflows

    def resolve_catalog_dataflows(
        self,
        *,
        dataflow_ids: list[str] | None = None,
        agency_id: str | None = None,
        query: str | None = None,
        agency_prefix: str = "OECD",
        limit: int | None = None,
    ) -> list[Any]:
        if dataflow_ids:
            if agency_id:
                return [
                    self.client.get_dataflow(dataflow_id, agency_id=agency_id, version="latest")
                    for dataflow_id in dataflow_ids
                ]
            allowed = set(dataflow_ids)
            matches = [
                dataflow for dataflow in self.list_catalog_dataflows(
                    agency_prefix=agency_prefix,
                    limit=None,
                )
                if dataflow.id in allowed
            ]
            ordered: list[Any] = []
            seen: set[tuple[str, str]] = set()
            for dataflow_id in dataflow_ids:
                for dataflow in matches:
                    marker = (dataflow.agency_id, dataflow.id)
                    if dataflow.id == dataflow_id and marker not in seen:
                        ordered.append(dataflow)
                        seen.add(marker)
            return ordered[:limit] if limit is not None else ordered
        return self.list_catalog_dataflows(query=query, agency_prefix=agency_prefix, limit=limit)

    def get_structure_summary(
        self,
        dataflow_id: str,
        *,
        agency_id: str = OECDClient.DEFAULT_AGENCY_ID,
        version: str = "latest",
    ) -> Any:
        return self.client.summarize_structure(dataflow_id, agency_id=agency_id, version=version)

    def generate_catalog_series_configs(
        self,
        *,
        dataflow_ids: list[str] | None = None,
        agency_id: str | None = None,
        query: str | None = None,
        agency_prefix: str = "OECD",
        dataflow_limit: int | None = 5,
        series_per_dataflow: int = 3,
        category: str = "catalog",
    ) -> dict[str, OECDSeriesConfig]:
        generated: dict[str, OECDSeriesConfig] = {}
        for dataflow in self.resolve_catalog_dataflows(
            dataflow_ids=dataflow_ids,
            agency_id=agency_id,
            query=query,
            agency_prefix=agency_prefix,
            limit=dataflow_limit,
        ):
            series_list = self.client.enumerate_series(
                dataflow.id,
                agency_id=dataflow.agency_id,
                version=dataflow.version,
                key="all",
                observation_limit=1,
                max_series=series_per_dataflow,
            )
            for series in series_list:
                filters = self.client.series_to_filters(
                    dataflow.id,
                    series,
                    agency_id=dataflow.agency_id,
                    version=dataflow.version,
                )
                if not filters:
                    continue
                series_key = self.client.build_key(
                    dataflow.id,
                    filters,
                    agency_id=dataflow.agency_id,
                    version=dataflow.version,
                )
                config = OECDSeriesConfig(
                    dataflow=dataflow.id,
                    series_id=_generated_oecd_series_id(dataflow.agency_id, dataflow.id, series_key),
                    category=category,
                    agency_id=dataflow.agency_id,
                    version=dataflow.version,
                    filters=filters,
                )
                generated[_generated_oecd_config_key(dataflow.id, series_key)] = config
        return generated

    def refresh_catalog(
        self,
        store: SQLiteEngineStore,
        *,
        dataflow_ids: list[str] | None = None,
        agency_id: str | None = None,
        query: str | None = None,
        agency_prefix: str = "OECD",
        dataflow_limit: int | None = 5,
        latest_observations: int = 1,
        sleep_seconds: float = 1.2,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for dataflow in self.resolve_catalog_dataflows(
            dataflow_ids=dataflow_ids,
            agency_id=agency_id,
            query=query,
            agency_prefix=agency_prefix,
            limit=dataflow_limit,
        ):
            try:
                observations = self.client.fetch_data(
                    dataflow.id,
                    agency_id=dataflow.agency_id,
                    version=dataflow.version,
                    key="all",
                    series_id=None,
                    limit=latest_observations,
                )
                for obs in observations:
                    fam_id = family_lookup.get(("oecd", obs.series_id)) if family_lookup else None
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="oecd",
                            date=obs.date,
                            value=obs.value,
                            metadata={
                                "category": "catalog",
                                "dataflow": obs.dataflow,
                                "dataflow_name": dataflow.name,
                                "dataflow_description": dataflow.description,
                                "agency_id": obs.agency_id or dataflow.agency_id,
                                "series_key": obs.series_key,
                                "raw_series_key": obs.raw_series_key,
                                "dimensions": obs.dimensions,
                            },
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("OECD catalog refresh failed for %s/%s", dataflow.agency_id, dataflow.id, exc_info=True)
            time.sleep(max(sleep_seconds, 0.0))
        return RefreshStats(source="oecd_catalog", count=count)

