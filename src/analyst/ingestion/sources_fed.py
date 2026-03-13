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

from .sources_catalog import FED_FEEDS, FED_SPEAKERS
from .sources_shared import RefreshStats, _infer_publish_precision


def extract_speaker(title: str) -> str:
    for speaker in FED_SPEAKERS:
        if speaker.lower() in title.lower():
            return speaker
    return ""

class FedIngestionClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AnalystEngine/1.0"})

    def refresh(self, store: SQLiteEngineStore, *, fetch_full_text: bool = False) -> RefreshStats:
        count = 0
        for feed in FED_FEEDS.values():
            for communication in self._parse_feed(feed["url"], feed["content_type"], fetch_full_text=fetch_full_text):
                store.upsert_central_bank_comm(communication)
                count += 1
            time.sleep(0.5)
        return RefreshStats(source="fed", count=count)

    def _parse_feed(
        self,
        feed_url: str,
        content_type: str,
        *,
        fetch_full_text: bool,
    ) -> list[CentralBankCommunicationRecord]:
        communications: list[CentralBankCommunicationRecord] = []
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries:
            ts = 0
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                ts = int(datetime(*entry.published_parsed[:6], tzinfo=UTC).timestamp())
            title = entry.get("title", "")
            url = entry.get("link", "")
            summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)
            full_text = summary
            if fetch_full_text and url:
                full_text = self.fetch_full_text(url) or summary
            communications.append(
                CentralBankCommunicationRecord(
                    source="fed",
                    title=title,
                    url=url,
                    timestamp=ts or int(datetime.now(UTC).timestamp()),
                    content_type=self._detect_content_type(title, content_type),
                    speaker=extract_speaker(title),
                    summary=summary,
                    full_text=full_text,
                )
            )
        return communications

    def fetch_full_text(self, url: str) -> str:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        content_div = (
            soup.find("div", {"id": "article"})
            or soup.find("div", {"class": "col-xs-12 col-sm-8 col-md-8"})
            or soup.find("div", {"class": "row"})
        )
        if content_div is None:
            return ""
        for tag in content_div.find_all(["script", "style", "nav"]):
            tag.decompose()
        text = content_div.get_text(separator="\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)[:50_000]

    def _detect_content_type(self, title: str, fallback: str) -> str:
        lowered = title.lower()
        if "minutes" in lowered:
            return "minutes"
        if "statement" in lowered or "fomc" in lowered:
            return "statement"
        if "beige book" in lowered:
            return "beige_book"
        if "testimony" in lowered:
            return "testimony"
        return fallback
