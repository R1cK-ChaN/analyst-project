from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import feedparser
import logging
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from analyst.contracts import format_epoch_iso
from analyst.env import get_env_value
from analyst.ingestion.news_extract import extract_news_metadata
from analyst.ingestion.news_feeds import get_feeds
from analyst.ingestion.news_fetcher import ArticleFetcher
from analyst.ingestion.scrapers import (
    ForexFactoryCalendarClient,
    InvestingCalendarClient,
    TradingEconomicsCalendarClient,
)
from analyst.ingestion.scrapers.gov_report import GovReportClient, GovReportItem
from analyst.ingestion.scrapers.eia import EIAClient
from analyst.ingestion.scrapers.fred import FredClient
from analyst.ingestion.scrapers.nyfed import NYFedRatesClient
from analyst.ingestion.scrapers.rateprobability import RateProbabilityClient
from analyst.ingestion.scrapers.treasury_fiscal import TreasuryFiscalClient

logger = logging.getLogger(__name__)
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
)

FED_FEEDS = {
    "press_releases": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "content_type": "statement",
    },
    "speeches": {
        "url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "content_type": "speech",
    },
    "testimony": {
        "url": "https://www.federalreserve.gov/feeds/testimony.xml",
        "content_type": "testimony",
    },
}

FED_SPEAKERS = [
    "Powell",
    "Waller",
    "Bowman",
    "Williams",
    "Barr",
    "Cook",
    "Jefferson",
    "Kugler",
    "Musalem",
    "Goolsbee",
    "Bostic",
    "Daly",
    "Collins",
    "Harker",
    "Kashkari",
    "Logan",
    "Barkin",
    "Hammack",
    "Schmid",
]

MACRO_SERIES = {
    "CPIAUCSL": {"name": "CPI All Urban", "category": "inflation", "freq": "monthly"},
    "CPILFESL": {"name": "Core CPI", "category": "inflation", "freq": "monthly"},
    "PCEPILFE": {"name": "Core PCE Price Index", "category": "inflation", "freq": "monthly"},
    "T5YIE": {"name": "5Y Breakeven Inflation", "category": "inflation", "freq": "daily"},
    "T10YIE": {"name": "10Y Breakeven Inflation", "category": "inflation", "freq": "daily"},
    "UNRATE": {"name": "Unemployment Rate", "category": "employment", "freq": "monthly"},
    "PAYEMS": {"name": "Total Nonfarm Payrolls", "category": "employment", "freq": "monthly"},
    "ICSA": {"name": "Initial Jobless Claims", "category": "employment", "freq": "weekly"},
    "CCSA": {"name": "Continuing Jobless Claims", "category": "employment", "freq": "weekly"},
    "GDP": {"name": "GDP", "category": "growth", "freq": "quarterly"},
    "GDPC1": {"name": "Real GDP", "category": "growth", "freq": "quarterly"},
    "RSAFS": {"name": "Retail Sales", "category": "growth", "freq": "monthly"},
    "INDPRO": {"name": "Industrial Production", "category": "growth", "freq": "monthly"},
    "DFF": {"name": "Fed Funds Rate", "category": "rates", "freq": "daily"},
    "DGS2": {"name": "2Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS10": {"name": "10Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS30": {"name": "30Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DFII10": {"name": "10Y Real Yield", "category": "rates", "freq": "daily"},
    "T10Y2Y": {"name": "10Y-2Y Spread", "category": "rates", "freq": "daily"},
    "WALCL": {"name": "Fed Balance Sheet", "category": "liquidity", "freq": "weekly"},
    "M2SL": {"name": "M2 Money Supply", "category": "liquidity", "freq": "monthly"},
    "RRPONTSYD": {"name": "Reverse Repo", "category": "liquidity", "freq": "daily"},
    "WTREGEN": {"name": "Treasury General Account", "category": "liquidity", "freq": "weekly"},
    "DTWEXBGS": {"name": "Broad Dollar Index", "category": "fx", "freq": "daily"},
    "DEXCHUS": {"name": "CNY/USD Exchange Rate", "category": "fx", "freq": "daily"},
    "BAMLH0A0HYM2": {"name": "High Yield OAS", "category": "credit", "freq": "daily"},
}

MACRO_WATCHLIST = {
    "equity": {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^DJI": "Dow Jones",
        "^VIX": "VIX",
    },
    "global_equity": {
        "^STOXX50E": "Euro Stoxx 50",
        "^N225": "Nikkei 225",
        "^HSI": "Hang Seng",
        "000001.SS": "Shanghai Composite",
    },
    "fx": {
        "DX-Y.NYB": "Dollar Index",
        "USDJPY=X": "USD/JPY",
        "USDCNY=X": "USD/CNY",
    },
    "bond": {
        "^TNX": "10Y Treasury Yield",
        "^TYX": "30Y Treasury Yield",
        "^FVX": "5Y Treasury Yield",
    },
    "commodity": {
        "GC=F": "Gold",
        "CL=F": "WTI Crude Oil",
        "HG=F": "Copper",
    },
    "crypto": {
        "BTC-USD": "Bitcoin",
        "ETH-USD": "Ethereum",
    },
}


def extract_speaker(title: str) -> str:
    for speaker in FED_SPEAKERS:
        if speaker.lower() in title.lower():
            return speaker
    return ""


@dataclass(frozen=True)
class RefreshStats:
    source: str
    count: int


VINTAGE_SERIES = ["GDP", "GDPC1", "CPIAUCSL", "PAYEMS", "UNRATE", "INDPRO", "RSAFS"]

EIA_SERIES = {
    "petroleum_brent": {
        "route": "petroleum/pri/spt/data",
        "params": {"data[]": "value", "facets[product][]": "EPCBRENT", "frequency": "daily"},
        "series_id": "EIA_BRENT",
        "category": "energy",
    },
    "petroleum_wti": {
        "route": "petroleum/pri/spt/data",
        "params": {"data[]": "value", "facets[product][]": "EPCWTI", "frequency": "daily"},
        "series_id": "EIA_WTI",
        "category": "energy",
    },
    "petroleum_stocks": {
        "route": "petroleum/stoc/wstk/data",
        "params": {"data[]": "value", "facets[product][]": "EPC0", "frequency": "weekly"},
        "series_id": "EIA_CRUDE_STOCKS",
        "category": "energy",
    },
    "natgas_futures": {
        "route": "natural-gas/pri/fut/data",
        "params": {"data[]": "value", "frequency": "daily"},
        "series_id": "EIA_NATGAS",
        "category": "energy",
    },
    "petroleum_supply": {
        "route": "petroleum/sum/snd/data",
        "params": {"data[]": "value", "frequency": "weekly"},
        "series_id": "EIA_PETROL_SUPPLY",
        "category": "energy",
    },
}

TREASURY_DATASETS = {
    "debt_outstanding": {
        "endpoint": "v2/accounting/od/debt_to_penny",
        "series_id": "TREAS_DEBT_TOTAL",
        "category": "fiscal",
    },
    "dts_operating_cash": {
        "endpoint": "v1/accounting/dts/deposits_withdrawals_operating_cash",
        "series_id": "TREAS_TGA_BALANCE",
        "category": "fiscal",
    },
    "avg_interest_rates": {
        "endpoint": "v2/accounting/od/avg_interest_rates",
        "series_id": "TREAS_AVG_RATE",
        "category": "fiscal",
    },
}


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


class MarketPriceClient:
    def refresh(self, store: SQLiteEngineStore) -> RefreshStats:
        count = 0
        now_epoch = int(datetime.now(UTC).timestamp())
        for asset_class, symbols in MACRO_WATCHLIST.items():
            for symbol, name in symbols.items():
                try:
                    ticker = yf.Ticker(symbol)
                    info = ticker.fast_info
                    price = info.get("lastPrice", info.get("previousClose"))
                    previous_close = info.get("previousClose")
                    if price is None:
                        history = ticker.history(period="2d")
                        if history.empty:
                            continue
                        price = float(history["Close"].iloc[-1])
                        previous_close = float(history["Close"].iloc[-2]) if len(history) > 1 else None
                    change_pct = None
                    if previous_close not in {None, 0}:
                        change_pct = round((float(price) - float(previous_close)) / float(previous_close) * 100, 2)
                    store.insert_market_price(
                        MarketPriceRecord(
                            symbol=symbol,
                            asset_class=asset_class,
                            name=name,
                            price=float(price),
                            change_pct=change_pct,
                            timestamp=now_epoch,
                        )
                    )
                    count += 1
                except Exception:
                    continue
                time.sleep(0.1)
        return RefreshStats(source="market", count=count)


class NewsIngestionClient:
    def __init__(
        self,
        *,
        timeout: int = 15,
        max_items_per_feed: int = 10,
        article_timeout: int = 20,
        max_content_chars: int = 15_000,
    ) -> None:
        self._timeout = timeout
        self._max_items_per_feed = max_items_per_feed
        self._article_fetcher = ArticleFetcher(
            timeout=article_timeout,
            max_content_chars=max_content_chars,
        )
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        })

    def refresh(
        self,
        store: SQLiteEngineStore,
        *,
        category: str | None = None,
    ) -> RefreshStats:
        """Fetch -> extract articles -> LLM/keyword metadata -> store."""
        feeds = get_feeds(category)

        stored_count = 0
        for feed in feeds:
            try:
                resp = self._session.get(feed.url, timeout=self._timeout)
                resp.raise_for_status()
                parsed = feedparser.parse(resp.text)
            except Exception:
                continue

            entries = parsed.entries[: self._max_items_per_feed]
            for entry in entries:
                try:
                    title = entry.get("title", "").strip()
                    if not title:
                        continue

                    link = entry.get("link", "")
                    if not link:
                        continue

                    url_hash = hashlib.sha256(link.encode("utf-8")).hexdigest()
                    if store.news_article_exists(url_hash):
                        continue

                    raw_desc = entry.get("summary", "") or entry.get("description", "")
                    from bs4 import BeautifulSoup as _BS
                    description = _BS(raw_desc, "html.parser").get_text(" ", strip=True)

                    ts = 0
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        ts = int(datetime(
                            *entry.published_parsed[:6], tzinfo=timezone.utc
                        ).timestamp())
                    if not ts:
                        ts = int(datetime.now(timezone.utc).timestamp())

                    article = self._article_fetcher.fetch_article(link, description)
                    extraction = extract_news_metadata(
                        title=title,
                        description=description,
                        content_markdown=article.content,
                        source_feed=feed.name,
                        feed_category=feed.category,
                        published_at=format_epoch_iso(ts),
                    )

                    record = NewsArticleRecord(
                        url_hash=url_hash,
                        source_feed=feed.name,
                        feed_category=feed.category,
                        title=extraction.title,
                        url=link,
                        timestamp=ts,
                        description=description,
                        content_markdown=article.content,
                        impact_level=extraction.impact_level,
                        finance_category=extraction.finance_category,
                        confidence=extraction.confidence,
                        content_fetched=article.fetched,
                        institution=extraction.institution,
                        country=extraction.country,
                        market=extraction.market,
                        asset_class=extraction.asset_class,
                        sector=extraction.sector,
                        document_type=extraction.document_type,
                        event_type=extraction.event_type,
                        subject=extraction.subject,
                        subject_id=extraction.subject_id,
                        data_period=extraction.data_period,
                        contains_commentary=extraction.contains_commentary,
                        language=extraction.language,
                        authors=extraction.authors,
                        extraction_provider=extraction.extraction_provider,
                    )
                    store.upsert_news_article(record)
                    stored_count += 1

                    time.sleep(0.5)
                except Exception:
                    continue

            time.sleep(0.3)

        return RefreshStats(source="news", count=stored_count)

    def close(self) -> None:
        self._article_fetcher.close()


class GovReportIngestionClient:
    """Fetches government reports and stores them into the normalized
    document tables (doc_source / doc_release_family / document /
    document_blob / document_extra) **and** the legacy news_articles
    table so existing consumers keep working."""

    def __init__(self) -> None:
        self._client = GovReportClient()
        self._seeded = False

    def _ensure_seed(self, store: SQLiteEngineStore) -> None:
        if self._seeded:
            return
        from analyst.ingestion.scrapers.gov_report import (
            _US_SOURCES,
            _CN_SOURCES,
            _JP_SOURCES,
            _EU_SOURCES,
        )
        store.seed_doc_sources_and_families({
            "us": _US_SOURCES,
            "cn": _CN_SOURCES,
            "jp": _JP_SOURCES,
            "eu": _EU_SOURCES,
        })
        self._seeded = True

    @staticmethod
    def _gov_document_type(data_category: str) -> str:
        """Map data_category to a valid document.document_type value."""
        mapping = {
            "monetary_policy": "statement",
            "economic_conditions": "bulletin",
            "speeches": "speech",
            "press_releases": "press_release",
        }
        return mapping.get(data_category, "release")

    def refresh(self, store: SQLiteEngineStore) -> RefreshStats:
        self._ensure_seed(store)
        items = self._client.fetch_all()
        count = 0
        now_iso = datetime.now(UTC).isoformat()
        for item in items:
            try:
                url_hash = hashlib.sha256(item.url.encode("utf-8")).hexdigest()

                # --- Normalized document storage ---
                if not store.document_exists(item.url):
                    doc_id = url_hash[:16]
                    release_family_id = item.source_id.replace("_", ".")
                    parts = item.source_id.split("_")
                    source_key = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else item.source_id
                    published_date = item.published_at or datetime.now(UTC).strftime("%Y-%m-%d")

                    doc = DocumentRecord(
                        document_id=doc_id,
                        release_family_id=release_family_id,
                        source_id=source_key,
                        canonical_url=item.url,
                        title=item.title,
                        subtitle="",
                        document_type=self._gov_document_type(item.data_category),
                        mime_type="text/html",
                        language_code=item.language,
                        country_code=item.country,
                        topic_code=item.data_category,
                        published_date=published_date,
                        published_at=now_iso,
                        status="published",
                        version_no=1,
                        parent_document_id="",
                        hash_sha256=url_hash,
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
                    store.upsert_document(doc)

                    if item.content_markdown:
                        blob = DocumentBlobRecord(
                            document_blob_id=f"{doc_id}_md",
                            document_id=doc_id,
                            blob_role="markdown",
                            storage_path="",
                            content_text=item.content_markdown,
                            content_bytes=None,
                            byte_size=len(item.content_markdown.encode("utf-8")),
                            encoding="utf-8",
                            parser_name="markdownify",
                            parser_version="",
                            extracted_at=now_iso,
                        )
                        store.upsert_document_blob(blob)

                    if item.raw_json or item.importance:
                        extra_data = dict(item.raw_json) if item.raw_json else {}
                        extra_data["importance"] = item.importance
                        extra_data["institution"] = item.institution
                        extra_data["description"] = item.description
                        store.upsert_document_extra(DocumentExtraRecord(
                            document_id=doc_id,
                            extra_json=extra_data,
                        ))

                # --- Legacy news_articles storage ---
                if store.news_article_exists(url_hash):
                    continue
                ts = 0
                if item.published_at:
                    try:
                        dt = datetime.strptime(item.published_at, "%Y-%m-%d")
                        ts = int(dt.replace(tzinfo=UTC).timestamp())
                    except ValueError:
                        ts = int(datetime.now(UTC).timestamp())
                else:
                    ts = int(datetime.now(UTC).timestamp())
                record = NewsArticleRecord(
                    url_hash=url_hash,
                    source_feed=f"gov_{item.source_id}",
                    feed_category="government",
                    title=item.title,
                    url=item.url,
                    timestamp=ts,
                    description=item.description,
                    content_markdown=item.content_markdown,
                    impact_level=item.importance or "medium",
                    finance_category=item.data_category,
                    confidence=0.8,
                    content_fetched=bool(item.content_markdown),
                    institution=item.institution,
                    country=item.country,
                    document_type="government_report",
                    language=item.language,
                )
                store.upsert_news_article(record)
                count += 1
            except Exception:
                logger.warning("Gov report storage failed: %s", item.source_id, exc_info=True)
                continue
        return RefreshStats(source="gov_reports", count=count)


class IngestionOrchestrator:
    def __init__(
        self,
        store: SQLiteEngineStore,
        *,
        fred: FREDIngestionClient | None = None,
        investing: InvestingCalendarClient | None = None,
        forexfactory: ForexFactoryCalendarClient | None = None,
        tradingeconomics: TradingEconomicsCalendarClient | None = None,
        fed: FedIngestionClient | None = None,
        market: MarketPriceClient | None = None,
        news: NewsIngestionClient | None = None,
        rate_probability: RateProbabilityClient | None = None,
        nyfed: NYFedRatesClient | None = None,
        gov_report: GovReportIngestionClient | None = None,
        eia: EIAIngestionClient | None = None,
        treasury_fiscal: TreasuryFiscalIngestionClient | None = None,
    ) -> None:
        self.store = store
        self.fred = fred or FREDIngestionClient()
        self.investing = investing or InvestingCalendarClient()
        self.forexfactory = forexfactory or ForexFactoryCalendarClient()
        self.tradingeconomics = tradingeconomics or TradingEconomicsCalendarClient()
        self.fed = fed or FedIngestionClient()
        self.market = market or MarketPriceClient()
        self.news = news or NewsIngestionClient()
        self.rate_probability = rate_probability or RateProbabilityClient()
        self.nyfed = nyfed or NYFedRatesClient()
        self.gov_report = gov_report or GovReportIngestionClient()
        self.eia = eia or EIAIngestionClient()
        self.treasury_fiscal = treasury_fiscal or TreasuryFiscalIngestionClient()
        self._obs_seeded = False
        self._family_lookup: dict[tuple[str, str], str] = {}

    def _ensure_obs_seed(self) -> None:
        """Seed observation sources/families once, then build lookup cache."""
        if self._obs_seeded:
            return
        self.store.seed_obs_sources_and_families()
        self.store.backfill_obs_family_ids()
        self._family_lookup = self.store.build_obs_family_lookup()
        self._obs_seeded = True

    def refresh_calendar(self) -> dict[str, int]:
        total = 0
        try:
            for event in self.investing.fetch_range(days_back=1, days_forward=3):
                self.store.upsert_calendar_event(event)
                total += 1
        except Exception:
            logger.warning("Investing.com calendar refresh failed", exc_info=True)
        try:
            for event in self.forexfactory.fetch():
                self.store.upsert_calendar_event(event)
                total += 1
        except Exception:
            logger.warning("ForexFactory calendar refresh failed", exc_info=True)
        try:
            for event in self.tradingeconomics.fetch():
                self.store.upsert_calendar_event(event)
                total += 1
        except Exception:
            logger.warning("TradingEconomics calendar refresh failed", exc_info=True)
        return {"calendar": total}

    def refresh_market(self) -> dict[str, int]:
        stats = self.market.refresh(self.store)
        return {stats.source: stats.count}

    def refresh_fed(self) -> dict[str, int]:
        stats = self.fed.refresh(self.store)
        return {stats.source: stats.count}

    def refresh_fred_daily(self) -> dict[str, int]:
        stats = self.fred.refresh_daily_series(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_fred_full(self, *, lookback_days: int = 365) -> dict[str, int]:
        stats = self.fred.refresh_all_series(self.store, lookback_days=lookback_days, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_news(self, *, category: str | None = None) -> dict[str, int]:
        stats = self.news.refresh(self.store, category=category)
        return {stats.source: stats.count}

    def refresh_rate_probability(self) -> dict[str, int]:
        count = 0
        try:
            prob = self.rate_probability.fetch_probabilities()
            for m in prob.meetings:
                self.store.upsert_indicator_observation(
                    IndicatorObservationRecord(
                        series_id=f"FEDPROB_{m.meeting_date}",
                        source="rateprobability",
                        date=prob.as_of[:10] if len(prob.as_of) >= 10 else prob.as_of,
                        value=m.implied_rate,
                        metadata={
                            "prob_move_pct": m.prob_move_pct,
                            "is_cut": m.is_cut,
                            "num_moves": m.num_moves,
                            "change_bps": m.change_bps,
                            "current_band": prob.current_band,
                        },
                        # Dynamic series — no pre-registered family
                    )
                )
                count += 1
        except Exception:
            logger.warning("rateprobability.com refresh failed", exc_info=True)
        return {"rate_probability": count}

    def refresh_fred_vintages(self) -> dict[str, int]:
        stats = self.fred.refresh_vintages(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_eia(self) -> dict[str, int]:
        stats = self.eia.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_treasury_fiscal(self) -> dict[str, int]:
        stats = self.treasury_fiscal.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_gov_reports(self) -> dict[str, int]:
        try:
            stats = self.gov_report.refresh(self.store)
            return {stats.source: stats.count}
        except Exception:
            logger.warning("Gov reports refresh failed", exc_info=True)
            return {"gov_reports": 0}

    def refresh_nyfed_rates(self) -> dict[str, int]:
        count = 0
        try:
            for rate in self.nyfed.fetch_all_rates(last_n=5):
                metadata: dict[str, Any] = {}
                if rate.percentile_1 is not None:
                    metadata["percentile_1"] = rate.percentile_1
                if rate.percentile_25 is not None:
                    metadata["percentile_25"] = rate.percentile_25
                if rate.percentile_75 is not None:
                    metadata["percentile_75"] = rate.percentile_75
                if rate.percentile_99 is not None:
                    metadata["percentile_99"] = rate.percentile_99
                if rate.volume_billions is not None:
                    metadata["volume_billions"] = rate.volume_billions
                if rate.target_rate_from is not None:
                    metadata["target_range"] = f"{rate.target_rate_from}-{rate.target_rate_to}"
                series_id = f"NYFED_{rate.type}"
                fam_id = self._family_lookup.get(("nyfed", series_id)) if self._family_lookup else None
                self.store.upsert_indicator_observation(
                    IndicatorObservationRecord(
                        series_id=series_id,
                        source="nyfed",
                        date=rate.date,
                        value=rate.rate,
                        metadata=metadata,
                        obs_family_id=fam_id,
                    )
                )
                count += 1
        except Exception:
            logger.warning("NY Fed rates refresh failed", exc_info=True)
        return {"nyfed_rates": count}

    def refresh_all(self) -> dict[str, int]:
        self._ensure_obs_seed()
        results: dict[str, int] = {}
        for batch in (
            self.refresh_calendar(),
            self.refresh_fed(),
            self.refresh_market(),
            self.refresh_fred_daily(),
            self.refresh_news(),
            self.refresh_rate_probability(),
            self.refresh_nyfed_rates(),
            self.refresh_gov_reports(),
            self.refresh_eia(),
            self.refresh_treasury_fiscal(),
        ):
            results.update(batch)
        return results

    def run_schedule(self, *, poll_interval_seconds: int = 60) -> None:
        jobs = {
            "calendar": {"interval": 3600, "handler": self.refresh_calendar},
            "fed": {"interval": 14_400, "handler": self.refresh_fed},
            "market": {"interval": 1800, "handler": self.refresh_market},
            "fred_daily": {"interval": 86_400, "handler": self.refresh_fred_daily},
            "fred_vintages": {"interval": 86_400, "handler": self.refresh_fred_vintages},
            "news": {"interval": 900, "handler": self.refresh_news},
            "rate_probability": {"interval": 3600, "handler": self.refresh_rate_probability},
            "nyfed_rates": {"interval": 86_400, "handler": self.refresh_nyfed_rates},
            "gov_reports": {"interval": 21_600, "handler": self.refresh_gov_reports},
            "eia": {"interval": 86_400, "handler": self.refresh_eia},
            "treasury_fiscal": {"interval": 86_400, "handler": self.refresh_treasury_fiscal},
        }
        next_run = {name: 0.0 for name in jobs}
        self.refresh_all()
        while True:
            now = time.time()
            for job_name, job in jobs.items():
                if now >= next_run[job_name]:
                    job["handler"]()
                    next_run[job_name] = now + float(job["interval"])
            time.sleep(poll_interval_seconds)
