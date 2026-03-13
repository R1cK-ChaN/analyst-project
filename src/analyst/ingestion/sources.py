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

from .sources_catalog import (
    BIS_SERIES,
    ECB_SERIES,
    EIA_SERIES,
    EUROSTAT_SERIES,
    FED_FEEDS,
    FED_SPEAKERS,
    IMF_SERIES,
    IMF_VINTAGE_SERIES,
    MACRO_SERIES,
    MACRO_WATCHLIST,
    OECD_SERIES,
    TREASURY_DATASETS,
    VINTAGE_SERIES,
    WORLDBANK_SERIES,
)
from .sources_fed import FedIngestionClient
from .sources_macro import (
    BISIngestionClient,
    ECBIngestionClient,
    EIAIngestionClient,
    EurostatIngestionClient,
    FREDIngestionClient,
    IMFIngestionClient,
    TreasuryFiscalIngestionClient,
    WorldBankIngestionClient,
)
from .sources_market_price import MarketPriceClient
from .sources_oecd import OECDIngestionClient
from .sources_shared import (
    OECDSeriesConfig,
    RefreshStats,
    _generated_oecd_config_key,
    _generated_oecd_series_id,
    _infer_publish_precision,
    _slugify_oecd_token,
    render_oecd_series_configs,
)

logger = logging.getLogger(__name__)

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

        # Seed fuzzy deduplicator with recent titles
        deduplicator = Deduplicator(threshold=0.6)
        recent_titles = store.get_recent_news_titles(hours=24)
        deduplicator.seed(recent_titles)

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

                    # Compute timestamp early — needed for content_hash
                    ts = 0
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        ts = int(datetime(
                            *entry.published_parsed[:6], tzinfo=timezone.utc
                        ).timestamp())
                    if not ts:
                        ts = int(datetime.now(timezone.utc).timestamp())

                    # Layer 1+2: fingerprint check (cheap, before HTTP fetch)
                    canonical = canonicalize_url(link)
                    url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    title_hash = content_hash(title, ts)
                    if store.fingerprint_exists(url_hash=url_hash, title_hash=title_hash):
                        continue

                    # Layer 3: fuzzy title check
                    if deduplicator.is_duplicate(title):
                        continue

                    raw_desc = entry.get("summary", "") or entry.get("description", "")
                    from bs4 import BeautifulSoup as _BS
                    description = _BS(raw_desc, "html.parser").get_text(" ", strip=True)

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
                    store.insert_fingerprint(
                        url_hash=url_hash,
                        title_hash=title_hash,
                        canonical_url=canonical,
                        raw_url=link,
                        title=title,
                        source_feed=feed.name,
                    )
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
        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()
        now_epoch_ms = int(now_dt.timestamp() * 1000)
        for item in items:
            try:
                canonical = canonicalize_url(item.url)
                url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                published_precision = item.published_precision or _infer_publish_precision(item.published_at)
                try:
                    if published_precision == "exact" and item.published_at:
                        published_at = normalize_utc_iso(item.published_at)
                        published_epoch_ms = to_epoch_ms(item.published_at)
                    elif published_precision == "date_only" and item.published_at:
                        published_at = item.published_at[:10]
                        published_epoch_ms = to_epoch_ms(published_at)
                    else:
                        published_at = now_iso
                        published_epoch_ms = now_epoch_ms
                        published_precision = "estimated"
                except ValueError:
                    published_at = now_iso
                    published_epoch_ms = now_epoch_ms
                    published_precision = "estimated"
                published_date = published_at[:10]

                # --- Normalized document storage ---
                if not store.document_exists(item.url):
                    doc_id = url_hash[:16]
                    release_family_id = item.source_id.replace("_", ".")
                    parts = item.source_id.split("_")
                    source_key = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else item.source_id

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
                        published_at=published_at,
                        published_precision=published_precision,
                        status="published",
                        version_no=1,
                        parent_document_id="",
                        hash_sha256=url_hash,
                        created_at=now_iso,
                        updated_at=now_iso,
                        published_epoch_ms=published_epoch_ms,
                        created_epoch_ms=now_epoch_ms,
                        updated_epoch_ms=now_epoch_ms,
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
                        extra_data["published_precision"] = published_precision
                        store.upsert_document_extra(DocumentExtraRecord(
                            document_id=doc_id,
                            extra_json=extra_data,
                        ))

                # --- Legacy news_articles storage ---
                if store.news_article_exists(url_hash):
                    continue
                ts = int(published_epoch_ms / 1000)
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
        imf: IMFIngestionClient | None = None,
        eurostat: EurostatIngestionClient | None = None,
        bis: BISIngestionClient | None = None,
        ecb: ECBIngestionClient | None = None,
        oecd: OECDIngestionClient | None = None,
        worldbank: WorldBankIngestionClient | None = None,
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
        self.imf = imf or IMFIngestionClient()
        self.eurostat = eurostat or EurostatIngestionClient()
        self.bis = bis or BISIngestionClient()
        self.ecb = ecb or ECBIngestionClient()
        self.oecd = oecd or OECDIngestionClient()
        self.worldbank = worldbank or WorldBankIngestionClient()
        self._obs_seeded = False
        self._cal_seeded = False
        self._family_lookup: dict[tuple[str, str], str] = {}

    def _ensure_obs_seed(self) -> None:
        """Seed observation sources/families once, then build lookup cache."""
        if self._obs_seeded:
            return
        self.store.seed_obs_sources_and_families()
        self.store.backfill_obs_family_ids()
        self._family_lookup = self.store.build_obs_family_lookup()
        self._obs_seeded = True

    def _ensure_calendar_indicator_seed(self) -> None:
        if self._cal_seeded:
            return
        self.store.seed_calendar_indicators()
        self._cal_seeded = True

    def _resolve_calendar_indicator(self, event: StoredEventRecord) -> StoredEventRecord:
        indicator_id = self.store.resolve_calendar_alias(
            event.indicator, event.source, event.country
        )
        if indicator_id:
            return dataclasses.replace(event, indicator_id=indicator_id)
        return event

    def refresh_calendar(self) -> dict[str, int]:
        self._ensure_calendar_indicator_seed()
        total = 0
        for label, fetch_fn in [
            ("Investing.com", lambda: self.investing.fetch_range(days_back=1, days_forward=3)),
            ("ForexFactory", lambda: self.forexfactory.fetch()),
            ("TradingEconomics", lambda: self.tradingeconomics.fetch()),
        ]:
            try:
                for event in fetch_fn():
                    event = self._resolve_calendar_indicator(event)
                    self.store.upsert_calendar_event(event)
                    total += 1
            except Exception:
                logger.warning("%s calendar refresh failed", label, exc_info=True)
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

    def refresh_imf(self) -> dict[str, int]:
        stats = self.imf.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_imf_vintages(self) -> dict[str, int]:
        stats = self.imf.refresh_vintages(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_eurostat(self) -> dict[str, int]:
        stats = self.eurostat.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_bis(self) -> dict[str, int]:
        stats = self.bis.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_ecb(self) -> dict[str, int]:
        stats = self.ecb.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_oecd(self) -> dict[str, int]:
        stats = self.oecd.refresh(self.store, family_lookup=self._family_lookup or None)
        return {stats.source: stats.count}

    def refresh_worldbank(self) -> dict[str, int]:
        stats = self.worldbank.refresh(self.store, family_lookup=self._family_lookup or None)
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
            self.refresh_imf(),
            self.refresh_imf_vintages(),
            self.refresh_eurostat(),
            self.refresh_bis(),
            self.refresh_ecb(),
            self.refresh_oecd(),
            self.refresh_worldbank(),
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
            "imf": {"interval": 86_400, "handler": self.refresh_imf},
            "imf_vintages": {"interval": 86_400, "handler": self.refresh_imf_vintages},
            "eurostat": {"interval": 86_400, "handler": self.refresh_eurostat},
            "bis": {"interval": 86_400, "handler": self.refresh_bis},
            "ecb": {"interval": 86_400, "handler": self.refresh_ecb},
            "oecd": {"interval": 86_400, "handler": self.refresh_oecd},
            "worldbank": {"interval": 86_400, "handler": self.refresh_worldbank},
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

