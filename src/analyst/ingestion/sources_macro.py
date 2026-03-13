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

from .sources_catalog import BIS_SERIES, ECB_SERIES, EIA_SERIES, EUROSTAT_SERIES, IMF_SERIES, IMF_VINTAGE_SERIES, TREASURY_DATASETS, VINTAGE_SERIES, WORLDBANK_SERIES
from .sources_shared import RefreshStats

class FREDIngestionClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.client = FredClient(api_key=api_key)

    @property
    def api_key(self) -> str:
        return self.client.api_key

    def refresh_daily_series(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        daily_series = {sid: meta for sid, meta in MACRO_SERIES.items() if meta["freq"] == "daily"}
        count = 0
        start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
        for series_id, meta in daily_series.items():
            count += self._store_series(store, series_id, meta, start_date=start_date, limit=5, family_lookup=family_lookup)
            time.sleep(0.2)
        return RefreshStats(source="fred_daily", count=count)

    def refresh_all_series(
        self,
        store: SQLiteEngineStore,
        *,
        lookback_days: int = 365,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        start_date = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        for series_id, meta in MACRO_SERIES.items():
            count += self._store_series(store, series_id, meta, start_date=start_date, limit=100, family_lookup=family_lookup)
            time.sleep(0.2)
        return RefreshStats(source="fred_all", count=count)

    def refresh_vintages(
        self,
        store: SQLiteEngineStore,
        vintage_series: list[str] | None = None,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        series_list = vintage_series or VINTAGE_SERIES
        count = 0
        start_date = (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%d")
        for series_id in series_list:
            try:
                vintages = self.client.get_vintages(series_id, start_date=start_date)
                fam_id = family_lookup.get(("fred", series_id)) if family_lookup else None
                for v in vintages:
                    store.upsert_indicator_vintage(
                        IndicatorVintageRecord(
                            series_id=v.series_id,
                            source="fred",
                            observation_date=v.date,
                            vintage_date=v.vintage_date,
                            value=v.value,
                            metadata={"name": MACRO_SERIES.get(series_id, {}).get("name", series_id)},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("FRED vintage refresh failed for %s", series_id, exc_info=True)
            time.sleep(0.3)
        return RefreshStats(source="fred_vintages", count=count)

    def _store_series(
        self,
        store: SQLiteEngineStore,
        series_id: str,
        meta: dict[str, str],
        *,
        start_date: str,
        limit: int,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> int:
        stored = 0
        fam_id = family_lookup.get(("fred", series_id)) if family_lookup else None
        for obs in self.client.get_series(series_id, start_date=start_date, limit=limit):
            store.upsert_indicator_observation(
                IndicatorObservationRecord(
                    series_id=series_id,
                    source="fred",
                    date=obs.date,
                    value=obs.value,
                    metadata={"name": meta["name"], "category": meta["category"]},
                    obs_family_id=fam_id,
                )
            )
            stored += 1
        return stored


class EIAIngestionClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.client = EIAClient(api_key=api_key)

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in EIA_SERIES.items():
            try:
                observations = self.client.get_series(
                    cfg["route"],
                    params=dict(cfg["params"]),
                    series_id=cfg["series_id"],
                    limit=30,
                )
                fam_id = family_lookup.get(("eia", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="eia",
                            date=obs.date,
                            value=obs.value,
                            metadata={"category": cfg["category"], "unit": obs.unit},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("EIA refresh failed for %s", key, exc_info=True)
            time.sleep(0.5)
        return RefreshStats(source="eia", count=count)


class TreasuryFiscalIngestionClient:
    def __init__(self) -> None:
        self.client = TreasuryFiscalClient()

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        fetchers = {
            "debt_outstanding": self.client.fetch_debt_outstanding,
            "dts_operating_cash": self.client.fetch_tga_balance,
            "avg_interest_rates": self.client.fetch_avg_interest_rates,
        }
        for key, fetch_fn in fetchers.items():
            cfg = TREASURY_DATASETS[key]
            try:
                observations = fetch_fn(limit=30)
                fam_id = family_lookup.get(("treasury_fiscal", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="treasury_fiscal",
                            date=obs.date,
                            value=obs.value,
                            metadata={**obs.metadata, "category": cfg["category"]},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("Treasury fiscal refresh failed for %s", key, exc_info=True)
            time.sleep(0.5)
        return RefreshStats(source="treasury_fiscal", count=count)


class IMFIngestionClient:
    def __init__(self) -> None:
        self.client = IMFClient()

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in IMF_SERIES.items():
            try:
                observations = self.client.get_data(
                    cfg["dataflow"],
                    cfg["key"],
                    series_id=cfg["series_id"],
                    version=cfg["version"],
                    limit=30,
                )
                fam_id = family_lookup.get(("imf", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="imf",
                            date=obs.date,
                            value=obs.value,
                            metadata={"category": cfg["category"], "dataflow": obs.dataflow},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("IMF refresh failed for %s", key, exc_info=True)
            time.sleep(1.0)
        return RefreshStats(source="imf", count=count)

    def refresh_vintages(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        now = datetime.now(UTC)
        as_of_dates = [
            (now - timedelta(days=30 * i)).strftime("%Y-%m-%d")
            for i in range(12)
        ]
        for series_key in IMF_VINTAGE_SERIES:
            cfg = IMF_SERIES[series_key]
            try:
                vintages = self.client.get_vintages(
                    cfg["dataflow"],
                    cfg["key"],
                    series_id=cfg["series_id"],
                    version=cfg["version"],
                    as_of_dates=as_of_dates,
                    start_period=str(now.year - 2),
                    limit=30,
                )
                fam_id = family_lookup.get(("imf", cfg["series_id"])) if family_lookup else None
                for v in vintages:
                    store.upsert_indicator_vintage(
                        IndicatorVintageRecord(
                            series_id=v.series_id,
                            source="imf",
                            observation_date=v.date,
                            vintage_date=v.vintage_date,
                            value=v.value,
                            metadata={"category": cfg["category"], "dataflow": v.dataflow},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("IMF vintage refresh failed for %s", series_key, exc_info=True)
        return RefreshStats(source="imf_vintages", count=count)


class EurostatIngestionClient:
    def __init__(self) -> None:
        self.client = EurostatClient()

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in EUROSTAT_SERIES.items():
            try:
                observations = self.client.get_dataset(
                    cfg["dataset"],
                    params=dict(cfg["params"]),
                    series_id=cfg["series_id"],
                    limit=30,
                )
                fam_id = family_lookup.get(("eurostat", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="eurostat",
                            date=obs.date,
                            value=obs.value,
                            metadata={"category": cfg["category"], "dataset": obs.dataset},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("Eurostat refresh failed for %s", key, exc_info=True)
            time.sleep(0.5)
        return RefreshStats(source="eurostat", count=count)


class BISIngestionClient:
    def __init__(self) -> None:
        self.client = BISClient()

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in BIS_SERIES.items():
            try:
                observations = self.client.get_data(
                    cfg["dataflow"],
                    cfg["key"],
                    series_id=cfg["series_id"],
                    limit=30,
                )
                fam_id = family_lookup.get(("bis", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="bis",
                            date=obs.date,
                            value=obs.value,
                            metadata={"category": cfg["category"], "dataflow": obs.dataflow},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("BIS refresh failed for %s", key, exc_info=True)
            time.sleep(0.5)
        return RefreshStats(source="bis", count=count)


class ECBIngestionClient:
    def __init__(self) -> None:
        self.client = ECBClient()

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in ECB_SERIES.items():
            try:
                observations = self.client.get_data(
                    cfg["dataflow"],
                    cfg["key"],
                    series_id=cfg["series_id"],
                    limit=30,
                )
                fam_id = family_lookup.get(("ecb", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="ecb",
                            date=obs.date,
                            value=obs.value,
                            metadata={"category": cfg["category"], "dataflow": obs.dataflow},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("ECB refresh failed for %s", key, exc_info=True)
            time.sleep(0.5)
        return RefreshStats(source="ecb", count=count)


class WorldBankIngestionClient:
    def __init__(self) -> None:
        self.client = WorldBankClient()

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        family_lookup: dict[tuple[str, str], str] | None = None,
    ) -> RefreshStats:
        count = 0
        for key, cfg in WORLDBANK_SERIES.items():
            try:
                observations = self.client.get_indicator(
                    cfg["indicator"],
                    cfg["country"],
                    series_id=cfg["series_id"],
                    limit=30,
                )
                fam_id = family_lookup.get(("worldbank", cfg["series_id"])) if family_lookup else None
                for obs in observations:
                    store.upsert_indicator_observation(
                        IndicatorObservationRecord(
                            series_id=obs.series_id,
                            source="worldbank",
                            date=obs.date,
                            value=obs.value,
                            metadata={"category": cfg["category"], "indicator": obs.indicator},
                            obs_family_id=fam_id,
                        )
                    )
                    count += 1
            except Exception:
                logger.warning("World Bank refresh failed for %s", key, exc_info=True)
            time.sleep(0.5)
        return RefreshStats(source="worldbank", count=count)


