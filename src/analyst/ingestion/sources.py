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

logger = logging.getLogger(__name__)
from analyst.storage import (
    CentralBankCommunicationRecord,
    IndicatorObservationRecord,
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


class FREDIngestionClient:
    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_env_value("FRED_API_KEY")
        self.session = requests.Session()

    def refresh_daily_series(self, store: SQLiteEngineStore) -> RefreshStats:
        daily_series = {series_id: meta for series_id, meta in MACRO_SERIES.items() if meta["freq"] == "daily"}
        count = 0
        start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
        for series_id, meta in daily_series.items():
            count += self._store_series(store, series_id, meta, start_date=start_date, limit=5)
            time.sleep(0.2)
        return RefreshStats(source="fred_daily", count=count)

    def refresh_all_series(self, store: SQLiteEngineStore, *, lookback_days: int = 365) -> RefreshStats:
        count = 0
        start_date = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        for series_id, meta in MACRO_SERIES.items():
            count += self._store_series(store, series_id, meta, start_date=start_date, limit=100)
            time.sleep(0.2)
        return RefreshStats(source="fred_all", count=count)

    def _store_series(
        self,
        store: SQLiteEngineStore,
        series_id: str,
        meta: dict[str, str],
        *,
        start_date: str,
        limit: int,
    ) -> int:
        stored = 0
        for observation in self.get_series(series_id, start_date=start_date, limit=limit):
            store.upsert_indicator_observation(
                IndicatorObservationRecord(
                    series_id=series_id,
                    source="fred",
                    date=observation["date"],
                    value=observation["value"],
                    metadata={"name": meta["name"], "category": meta["category"]},
                )
            )
            stored += 1
        return stored

    def get_series(self, series_id: str, *, start_date: str, limit: int) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        response = self.session.get(
            f"{self.BASE_URL}/series/observations",
            params={
                "series_id": series_id,
                "observation_start": start_date,
                "sort_order": "desc",
                "limit": limit,
                "api_key": self.api_key,
                "file_type": "json",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        observations: list[dict[str, Any]] = []
        for observation in payload.get("observations", []):
            if observation["value"] == ".":
                continue
            observations.append({"date": observation["date"], "value": float(observation["value"])})
        return observations


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
    ) -> None:
        self.store = store
        self.fred = fred or FREDIngestionClient()
        self.investing = investing or InvestingCalendarClient()
        self.forexfactory = forexfactory or ForexFactoryCalendarClient()
        self.tradingeconomics = tradingeconomics or TradingEconomicsCalendarClient()
        self.fed = fed or FedIngestionClient()
        self.market = market or MarketPriceClient()
        self.news = news or NewsIngestionClient()

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
        stats = self.fred.refresh_daily_series(self.store)
        return {stats.source: stats.count}

    def refresh_fred_full(self, *, lookback_days: int = 365) -> dict[str, int]:
        stats = self.fred.refresh_all_series(self.store, lookback_days=lookback_days)
        return {stats.source: stats.count}

    def refresh_news(self, *, category: str | None = None) -> dict[str, int]:
        stats = self.news.refresh(self.store, category=category)
        return {stats.source: stats.count}

    def refresh_all(self) -> dict[str, int]:
        results: dict[str, int] = {}
        for batch in (self.refresh_calendar(), self.refresh_fed(), self.refresh_market(), self.refresh_fred_daily(), self.refresh_news()):
            results.update(batch)
        return results

    def run_schedule(self, *, poll_interval_seconds: int = 60) -> None:
        jobs = {
            "calendar": {"interval": 3600, "handler": self.refresh_calendar},
            "fed": {"interval": 14_400, "handler": self.refresh_fed},
            "market": {"interval": 1800, "handler": self.refresh_market},
            "fred_daily": {"interval": 86_400, "handler": self.refresh_fred_daily},
            "news": {"interval": 900, "handler": self.refresh_news},
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
