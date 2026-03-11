"""Tests for the news ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from analyst.ingestion.news_classify import (
    Classification,
    Deduplicator,
    _tokenize,
    _jaccard_similarity,
    classify,
)
from analyst.ingestion.news_feeds import (
    FeedInfo,
    RSS_FEEDS,
    FEED_CATEGORIES,
    _gnews,
    get_feeds,
)
from analyst.ingestion.news_fetcher import ArticleFetcher
from analyst.ingestion.url_canon import canonicalize_url, content_hash
from analyst.storage.sqlite import NewsArticleRecord, SQLiteEngineStore


# ---------------------------------------------------------------------------
# Deduplicator tests
# ---------------------------------------------------------------------------

class TestDeduplicator:
    def test_basic_dedup(self):
        d = Deduplicator(threshold=0.6)
        assert not d.is_duplicate("Fed raises interest rates by 25 basis points")
        assert d.is_duplicate("Fed raises interest rates by 25 basis points")

    def test_similar_titles(self):
        d = Deduplicator(threshold=0.6)
        assert not d.is_duplicate("Fed holds rates steady at meeting")
        assert d.is_duplicate("Fed holds rates steady at latest meeting")

    def test_different_titles(self):
        d = Deduplicator(threshold=0.6)
        assert not d.is_duplicate("Oil prices surge on OPEC cut")
        assert not d.is_duplicate("Fed raises interest rates by 50 bps")

    def test_seeding(self):
        d = Deduplicator(threshold=0.6)
        d.seed(["Fed holds rates steady at meeting"])
        assert d.seen_count == 1
        assert d.is_duplicate("Fed holds rates steady at latest meeting")

    def test_filter(self):
        d = Deduplicator(threshold=0.6)
        titles = [
            "Gold price hits record high",
            "Gold price reaches record high level",
            "Oil falls on demand concerns",
        ]
        unique = d.filter(titles)
        assert len(unique) == 2
        assert unique[0] == "Gold price hits record high"
        assert unique[1] == "Oil falls on demand concerns"

    def test_reset(self):
        d = Deduplicator()
        d.is_duplicate("Some headline")
        assert d.seen_count == 1
        d.reset()
        assert d.seen_count == 0

    def test_empty_title(self):
        d = Deduplicator()
        assert d.is_duplicate("")
        assert d.is_duplicate("  ")


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Fed Raises Interest Rates")
        assert "fed" in tokens
        assert "raises" in tokens
        assert "interest" in tokens
        assert "rates" in tokens

    def test_stopwords_removed(self):
        tokens = _tokenize("The Fed is raising the rates")
        assert "the" not in tokens
        assert "is" not in tokens

    def test_short_words_removed(self):
        tokens = _tokenize("US GDP at 3%")
        assert "at" not in tokens
        assert "us" not in tokens  # len <= 2


class TestJaccardSimilarity:
    def test_identical(self):
        s = {"fed", "rates", "hike"}
        assert _jaccard_similarity(s, s) == 1.0

    def test_empty(self):
        assert _jaccard_similarity(set(), {"a", "b"}) == 0.0

    def test_partial_overlap(self):
        a = {"fed", "rates", "hike"}
        b = {"fed", "rates", "cut"}
        sim = _jaccard_similarity(a, b)
        assert 0.5 < sim < 1.0


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

class TestClassifier:
    def test_critical(self):
        result = classify("Bank failure sends shockwaves through markets")
        assert result.impact_level == "critical"
        assert result.finance_category == "rates"
        assert result.confidence == 0.9

    def test_high(self):
        result = classify("FOMC announces rate cut of 25 bps")
        assert result.impact_level == "high"
        assert result.finance_category == "monetary_policy"

    def test_medium(self):
        result = classify("Bitcoin rallies above $60,000")
        assert result.impact_level == "medium"
        assert result.finance_category == "crypto"

    def test_low(self):
        result = classify("Housing market shows signs of cooling")
        assert result.impact_level == "low"
        assert result.finance_category == "general"

    def test_info_default(self):
        result = classify("Company launches new product line")
        assert result.impact_level == "info"
        assert result.finance_category == "general"
        assert result.confidence == 0.3

    def test_exclusions(self):
        result = classify("Celebrity cooking recipe goes viral")
        assert result.impact_level == "info"

    def test_title_then_description_fallback(self):
        result = classify(
            "Breaking: Major policy announcement",
            description="Federal Reserve FOMC decides to cut rates",
        )
        assert result.impact_level == "high"
        assert result.finance_category == "monetary_policy"


# ---------------------------------------------------------------------------
# Feed registry tests
# ---------------------------------------------------------------------------

class TestFeedRegistry:
    def test_feed_count(self):
        assert len(RSS_FEEDS) >= 130

    def test_all_have_category(self):
        for feed in RSS_FEEDS:
            assert feed.category, f"Feed {feed.name} has empty category"
            assert feed.name, f"Feed has empty name"
            assert feed.url, f"Feed {feed.name} has empty URL"

    def test_gnews_url_format(self):
        url = _gnews("test+query", "1d")
        assert "news.google.com/rss/search" in url
        assert "test+query" in url
        assert "when:1d" in url

    def test_get_feeds_all(self):
        all_feeds = get_feeds()
        assert len(all_feeds) == len(RSS_FEEDS)

    def test_get_feeds_filtered(self):
        market_feeds = get_feeds("markets")
        assert len(market_feeds) >= 8
        assert all(f.category == "markets" for f in market_feeds)

    def test_categories_sorted(self):
        assert FEED_CATEGORIES == sorted(FEED_CATEGORIES)
        assert len(FEED_CATEGORIES) > 10


# ---------------------------------------------------------------------------
# ArticleFetcher URL detection
# ---------------------------------------------------------------------------

class TestArticleFetcher:
    def test_is_google_news_url_true(self):
        assert ArticleFetcher._is_google_news_url(
            "https://news.google.com/rss/articles/abc123"
        )

    def test_is_google_news_url_false(self):
        assert not ArticleFetcher._is_google_news_url(
            "https://www.cnbc.com/2024/01/01/article.html"
        )

    def test_is_google_news_url_invalid(self):
        assert not ArticleFetcher._is_google_news_url("")


# ---------------------------------------------------------------------------
# Storage tests (in-memory SQLite)
# ---------------------------------------------------------------------------

class TestNewsStorage:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> SQLiteEngineStore:
        return SQLiteEngineStore(db_path=tmp_path / "test.db")

    def _make_article(self, url: str = "https://example.com/article1", **kwargs) -> NewsArticleRecord:
        defaults = dict(
            url_hash=hashlib.sha256(url.encode()).hexdigest(),
            source_feed="CNBC",
            feed_category="markets",
            title="Test Article",
            url=url,
            timestamp=int(datetime.now(timezone.utc).timestamp()),
            description="Test description",
            content_markdown="# Test content",
            impact_level="high",
            finance_category="rates",
            confidence=0.8,
            content_fetched=True,
        )
        defaults.update(kwargs)
        return NewsArticleRecord(**defaults)

    def test_upsert_and_list(self, store: SQLiteEngineStore):
        article = self._make_article(
            country="US", asset_class="Macro", subject="CPI",
            extraction_provider="keyword",
        )
        store.upsert_news_article(article)
        results = store.list_recent_news(limit=10, days=1)
        assert len(results) == 1
        assert results[0].title == "Test Article"
        assert results[0].content_fetched is True
        assert results[0].country == "US"
        assert results[0].asset_class == "Macro"
        assert results[0].subject == "CPI"
        assert results[0].extraction_provider == "keyword"

    def test_dedup_by_url_hash(self, store: SQLiteEngineStore):
        article1 = self._make_article(title="First version")
        store.upsert_news_article(article1)
        article2 = self._make_article(title="Updated version")
        store.upsert_news_article(article2)
        results = store.list_recent_news(limit=10, days=1)
        assert len(results) == 1
        assert results[0].title == "Updated version"

    def test_list_recent_news_filters(self, store: SQLiteEngineStore):
        store.upsert_news_article(self._make_article(
            url="https://example.com/1",
            impact_level="high",
            feed_category="markets",
            finance_category="rates",
        ))
        store.upsert_news_article(self._make_article(
            url="https://example.com/2",
            impact_level="low",
            feed_category="crypto",
            finance_category="crypto",
        ))
        high = store.list_recent_news(impact_level="high")
        assert len(high) == 1
        crypto = store.list_recent_news(feed_category="crypto")
        assert len(crypto) == 1
        rates = store.list_recent_news(finance_category="rates")
        assert len(rates) == 1

    def test_search_news(self, store: SQLiteEngineStore):
        store.upsert_news_article(self._make_article(
            url="https://example.com/fed",
            title="Fed holds rates steady",
            description="Federal Reserve keeps rates unchanged",
        ))
        store.upsert_news_article(self._make_article(
            url="https://example.com/oil",
            title="Oil prices surge",
            description="Crude oil jumps on supply concerns",
        ))
        results = store.search_news("Fed")
        assert len(results) == 1
        assert results[0].title == "Fed holds rates steady"
        results2 = store.search_news("oil")
        assert len(results2) == 1

    def test_get_recent_news_titles(self, store: SQLiteEngineStore):
        store.upsert_news_article(self._make_article(
            url="https://example.com/1", title="Title A",
        ))
        store.upsert_news_article(self._make_article(
            url="https://example.com/2", title="Title B",
        ))
        titles = store.get_recent_news_titles(hours=24)
        assert len(titles) == 2
        assert "Title A" in titles or "Title B" in titles

    def test_news_article_exists(self, store: SQLiteEngineStore):
        article = self._make_article()
        assert not store.news_article_exists(article.url_hash)
        store.upsert_news_article(article)
        assert store.news_article_exists(article.url_hash)

    def test_fts5_search(self, store: SQLiteEngineStore):
        store.upsert_news_article(self._make_article(
            url="https://example.com/inflation",
            title="CPI inflation surges to 4 percent",
            description="Consumer prices rose sharply",
            subject="CPI",
        ))
        store.upsert_news_article(self._make_article(
            url="https://example.com/jobs",
            title="NFP shows strong job growth",
            description="Nonfarm payrolls beat expectations",
            subject="NFP",
        ))
        results = store.search_news("inflation")
        assert len(results) == 1
        assert results[0].title == "CPI inflation surges to 4 percent"

    def test_list_recent_news_country_filter(self, store: SQLiteEngineStore):
        store.upsert_news_article(self._make_article(
            url="https://example.com/us", country="US",
        ))
        store.upsert_news_article(self._make_article(
            url="https://example.com/cn", country="CN",
        ))
        us = store.list_recent_news(country="US")
        assert len(us) == 1
        assert us[0].country == "US"

    def test_get_news_context_time_decay(self, store: SQLiteEngineStore):
        now = datetime.now(timezone.utc)
        # Recent critical article
        store.upsert_news_article(self._make_article(
            url="https://example.com/recent-critical",
            title="Market crash imminent",
            impact_level="critical",
            timestamp=int(now.timestamp()),
        ))
        # Older high article
        store.upsert_news_article(self._make_article(
            url="https://example.com/old-high",
            title="Fed raises rates",
            impact_level="high",
            timestamp=int((now - timedelta(days=5)).timestamp()),
        ))
        # Recent info article
        store.upsert_news_article(self._make_article(
            url="https://example.com/recent-info",
            title="Company holds meeting",
            impact_level="info",
            timestamp=int(now.timestamp()),
        ))
        results = store.get_news_context(days=7, limit=10)
        assert len(results) == 3
        # Critical recent should score highest
        assert results[0]["title"] == "Market crash imminent"
        # Info should score lowest despite being recent
        assert results[-1]["title"] == "Company holds meeting"
        # All results should have a score field
        for r in results:
            assert "score" in r
            assert r["score"] > 0

    def test_get_news_context_old_critical_beats_recent_info(self, store: SQLiteEngineStore):
        """Old critical article must not be dropped before scoring (fix #2)."""
        now = datetime.now(timezone.utc)
        # Insert 50 recent info articles to flood the recency window
        for i in range(50):
            store.upsert_news_article(self._make_article(
                url=f"https://example.com/info-{i}",
                title=f"Low impact filler item {i}",
                impact_level="info",
                timestamp=int(now.timestamp()),
            ))
        # Insert one 5-day-old critical article
        store.upsert_news_article(self._make_article(
            url="https://example.com/old-critical",
            title="Banking crisis erupts",
            impact_level="critical",
            timestamp=int((now - timedelta(days=5)).timestamp()),
        ))
        results = store.get_news_context(days=7, limit=15)
        titles = [r["title"] for r in results]
        assert "Banking crisis erupts" in titles

    def test_get_news_context_projects_display_timezone(self, store: SQLiteEngineStore):
        ts = int(datetime(2026, 3, 7, 14, 30, tzinfo=timezone.utc).timestamp())
        store.upsert_news_article(self._make_article(
            url="https://example.com/timezone-test",
            title="Timezone projection",
            timestamp=ts,
        ))
        results = store.get_news_context(days=30, limit=5, display_timezone="Asia/Singapore")
        assert results[0]["published_at"] == "2026-03-07T14:30:00+00:00"
        assert results[0]["published_at_local"] == "2026-03-07T22:30:00+08:00"
        assert results[0]["published_timezone"] == "Asia/Singapore"

    def test_epoch_timestamp_round_trip(self, store: SQLiteEngineStore):
        """timestamp must round-trip as int through the store."""
        ts = int(datetime(2026, 3, 7, 14, 30, tzinfo=timezone.utc).timestamp())
        store.upsert_news_article(self._make_article(
            url="https://example.com/ts-test",
            timestamp=ts,
        ))
        results = store.list_recent_news(limit=1, days=30)
        assert len(results) == 1
        assert isinstance(results[0].timestamp, int)
        assert results[0].timestamp == ts


# ---------------------------------------------------------------------------
# Extraction tests
# ---------------------------------------------------------------------------

class TestNewsExtraction:
    def test_keyword_fallback_preserves_full_timestamp(self):
        """_keyword_fallback must not truncate published_at to date-only (fix #1)."""
        from analyst.ingestion.news_extract import _keyword_fallback

        full_ts = "2026-03-07T14:30:00+00:00"
        result = _keyword_fallback(
            title="Fed raises rates",
            description="The Fed raised rates",
            source_feed="CNBC",
            feed_category="markets",
            published_at=full_ts,
        )
        assert result.publish_date == full_ts
        assert "T" in result.publish_date

    def test_finance_category_always_canonical(self):
        """finance_category must use canonical keyword values, not LLM sector text (fix #3)."""
        from analyst.ingestion.news_extract import _keyword_fallback

        result = _keyword_fallback(
            title="FOMC rate decision announced",
            description="Federal Reserve holds rates",
            source_feed="Reuters",
            feed_category="centralbanks",
            published_at="2026-03-07T12:00:00+00:00",
        )
        # finance_category must be a canonical classifier value
        assert result.finance_category == "monetary_policy"
        # sector is allowed to differ
        assert result.sector in ("monetary_policy", "general")

    def test_llm_missing_filter_fields_use_classifier_defaults(self):
        """Partial LLM responses should still populate filterable fields."""
        from analyst.ingestion.news_extract import extract_news_metadata

        payload = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "sector": "Interest Rate",
                        "impact_level": "high",
                        "confidence": 0.8,
                        "market": None,
                        "asset_class": None,
                        "event_type": None,
                    })
                }
            }]
        }

        with patch("analyst.ingestion.news_extract.get_env_value") as mock_env, patch(
            "analyst.ingestion.news_extract.httpx.Client"
        ) as mock_client_cls:
            def _env_side_effect(*keys: str, default: str = "") -> str:
                if "LLM_API_KEY" in keys or "OPENROUTER_API_KEY" in keys:
                    return "test-key"
                return default

            mock_env.side_effect = _env_side_effect
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = payload
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = extract_news_metadata(
                title="FOMC rate decision announced",
                description="Federal Reserve holds rates steady",
                content_markdown="body",
                source_feed="Reuters",
                feed_category="markets",
                published_at="2026-03-07T12:00:00+00:00",
            )

        assert result.finance_category == "monetary_policy"
        assert result.sector == "Interest Rate"
        assert result.market == "Global Markets"
        assert result.asset_class == "Macro"
        assert result.event_type == "Policy Statement"


# ---------------------------------------------------------------------------
# NewsIngestionClient integration test
# ---------------------------------------------------------------------------

class TestNewsIngestionClient:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> SQLiteEngineStore:
        return SQLiteEngineStore(db_path=tmp_path / "test.db")

    def test_full_pipeline(self, store: SQLiteEngineStore):
        from analyst.ingestion.sources import NewsIngestionClient
        from analyst.ingestion.news_fetcher import ArticleContent

        class FeedEntry(dict):
            """Dict subclass that also supports attribute access like feedparser."""
            def __getattr__(self, key):
                try:
                    return self[key]
                except KeyError:
                    raise AttributeError(key)

        mock_entry = FeedEntry(
            title="Fed Raises Rates by 25bps in Surprise Move",
            link="https://example.com/fed-rates",
            summary="<p>The Federal Reserve raised interest rates.</p>",
            published_parsed=datetime.now(timezone.utc).timetuple(),
        )

        mock_parsed = SimpleNamespace(entries=[mock_entry])

        client = NewsIngestionClient(max_items_per_feed=5)

        with patch.object(client._session, "get") as mock_get, \
             patch("analyst.ingestion.sources.feedparser") as mock_fp, \
             patch.object(client._article_fetcher, "fetch_article") as mock_fetch:

            mock_response = MagicMock()
            mock_response.text = "<rss>mock</rss>"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            mock_fp.parse.return_value = mock_parsed

            mock_fetch.return_value = ArticleContent(
                content="# Full article markdown content here",
                fetched=True,
                content_length=100,
            )

            stats = client.refresh(store, category="markets")

        assert stats.source == "news"
        assert stats.count > 0

        articles = store.list_recent_news(limit=100, days=1)
        assert len(articles) > 0
        article = articles[0]
        assert "Fed" in article.title or "Rates" in article.title
        assert article.impact_level in ("critical", "high", "medium", "low", "info")
        assert article.content_fetched is True
        assert article.extraction_provider in ("llm", "keyword")
        assert article.finance_category != ""


# ---------------------------------------------------------------------------
# Fingerprint dedup tests
# ---------------------------------------------------------------------------

class TestFingerprintStorage:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> SQLiteEngineStore:
        return SQLiteEngineStore(db_path=tmp_path / "test.db")

    def test_fingerprint_insert_and_exists_url(self, store: SQLiteEngineStore):
        url = "https://example.com/article"
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        title_hash = content_hash("Some title", 3600)
        store.insert_fingerprint(url_hash, title_hash, url, url, title="Some title")
        assert store.fingerprint_exists(url_hash=url_hash, title_hash=None)

    def test_fingerprint_insert_and_exists_title(self, store: SQLiteEngineStore):
        url = "https://example.com/article"
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        title_hash = content_hash("Some title", 3600)
        store.insert_fingerprint(url_hash, title_hash, url, url, title="Some title")
        assert store.fingerprint_exists(url_hash=None, title_hash=title_hash)

    def test_fingerprint_not_exists_unknown(self, store: SQLiteEngineStore):
        assert not store.fingerprint_exists(url_hash="nonexistent", title_hash="nonexistent")

    def test_fingerprint_or_semantics(self, store: SQLiteEngineStore):
        """Match on either url_hash or title_hash should return True."""
        url_hash = hashlib.sha256(b"url1").hexdigest()
        title_hash = content_hash("Title One", 7200)
        store.insert_fingerprint(url_hash, title_hash, "url1", "url1")
        # Match on url_hash only
        assert store.fingerprint_exists(url_hash=url_hash, title_hash="other")
        # Match on title_hash only
        assert store.fingerprint_exists(url_hash="other", title_hash=title_hash)
        # Match on both
        assert store.fingerprint_exists(url_hash=url_hash, title_hash=title_hash)
        # Match on neither
        assert not store.fingerprint_exists(url_hash="x", title_hash="y")

    def test_backfill_from_existing_articles(self, store: SQLiteEngineStore):
        url = "https://example.com/backfill-test?utm_source=twitter"
        url_hash_raw = hashlib.sha256(url.encode()).hexdigest()
        ts = int(datetime.now(timezone.utc).timestamp())
        record = NewsArticleRecord(
            url_hash=url_hash_raw,
            source_feed="Test",
            feed_category="markets",
            title="Backfill Article",
            url=url,
            timestamp=ts,
            description="desc",
            content_markdown="body",
            impact_level="high",
            finance_category="rates",
            confidence=0.8,
            content_fetched=True,
        )
        store.upsert_news_article(record)
        count = store.backfill_fingerprints()
        assert count == 1
        # Canonical URL should strip utm_source
        canonical = canonicalize_url(url)
        canonical_hash = hashlib.sha256(canonical.encode()).hexdigest()
        assert store.fingerprint_exists(url_hash=canonical_hash, title_hash=None)

    def test_canonical_url_dedup(self, store: SQLiteEngineStore):
        """Same article with different tracking params → one fingerprint."""
        url1 = "https://reuters.com/article/fed-rates?utm_source=twitter"
        url2 = "https://reuters.com/article/fed-rates?utm_source=email"
        canon1 = canonicalize_url(url1)
        canon2 = canonicalize_url(url2)
        assert canon1 == canon2
        url_hash = hashlib.sha256(canon1.encode()).hexdigest()
        title_hash = content_hash("Fed holds rates", 3600)
        store.insert_fingerprint(url_hash, title_hash, canon1, url1)
        # Second insert with different raw_url is ignored (same url_hash)
        store.insert_fingerprint(url_hash, title_hash, canon2, url2)
        assert store.fingerprint_exists(url_hash=url_hash, title_hash=None)

    def test_fuzzy_title_dedup(self, store: SQLiteEngineStore):
        """Similar titles detected by Deduplicator → second is skipped."""
        deduplicator = Deduplicator(threshold=0.6)
        assert not deduplicator.is_duplicate("Fed holds rates steady at meeting")
        assert deduplicator.is_duplicate("Fed holds rates steady at latest meeting")
