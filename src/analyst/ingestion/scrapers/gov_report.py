"""Government report scrapers for US, CN, JP, and EU institutions.

Fetches the latest official statistical releases and policy documents from
~40 government sources across four regions, returning structured
GovReportItem records suitable for storage in the news_articles table.
"""

from __future__ import annotations

import feedparser
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from .gov_report_configs_cn import _CN_SOURCES
from .gov_report_configs_eu import _EU_SOURCES
from .gov_report_configs_jp import _JP_SOURCES
from .gov_report_configs_us import _US_SOURCES
from .gov_report_models import GovReportItem
from .gov_report_parsing import (
    _anchor_context_text,
    _anchor_context_year,
    _build_anchor_asset_item,
    _clean_link_text,
    _extract_anchor_fallback,
    _extract_content,
    _extract_date_cn,
    _extract_date_en,
    _extract_datetime_cn,
    _extract_datetime_en,
    _extract_structured_datetime,
    _extract_title,
    _get_html,
    _html_to_markdown,
    _link_matches_keywords,
    _merge_published_values,
    _parse_rss_published,
    _resolve_url,
    _select_latest_matching_anchor,
    _USER_AGENT,
)

logger = logging.getLogger(__name__)

class USGovReportClient:
    """Scraper for US government institution reports."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _US_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("US gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "fixed_url":
            return self._fetch_fixed_url(source_id, cfg)
        if strategy == "listing_keywords":
            return self._fetch_listing_keywords(source_id, cfg)
        if strategy == "listing_regex":
            return self._fetch_listing_regex(source_id, cfg)
        return None

    def _fetch_fixed_url(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        title = _extract_title(html, cfg["title_selectors"])
        exact_published_at = _extract_structured_datetime(
            html,
            default_timezone=cfg.get("default_timezone", "UTC"),
        ) or _extract_datetime_en(
            html,
            cfg.get("datetime_patterns", []),
            default_timezone=cfg.get("default_timezone", "UTC"),
        )
        published_at = exact_published_at or _extract_date_en(html, cfg["date_patterns"])
        published_precision = "exact" if exact_published_at else ("date_only" if published_at else "estimated")
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=cfg["url"],
            published_at=published_at or "",
            published_precision=published_precision,
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )

    def _fetch_listing_keywords(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        keywords = cfg["keywords"]
        extra_keywords = cfg.get("extra_keywords")
        link_must_contain = cfg.get("link_must_contain")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if link_must_contain and link_must_contain not in href:
                continue
            if _link_matches_keywords(a_tag, keywords, extra_keywords):
                if href.endswith(".pdf"):
                    continue
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_listing_regex(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        archive_pattern = re.compile(cfg.get("archive_link_pattern", cfg["link_pattern"]))
        detail_pattern = re.compile(cfg["link_pattern"])

        if not cfg.get("archive_link_pattern"):
            a_tag = _select_latest_matching_anchor(soup, detail_pattern, cfg)
            if not a_tag:
                return None
            return self._fetch_detail_page(source_id, cfg, _resolve_url(a_tag["href"], base_url))

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not archive_pattern.search(href):
                continue
            detail_url = _resolve_url(href, base_url)
            if cfg.get("archive_link_pattern"):
                archive_html = _get_html(self.session, detail_url)
                archive_soup = BeautifulSoup(archive_html, "html.parser")
                nested_tag = _select_latest_matching_anchor(archive_soup, detail_pattern, cfg)
                if nested_tag:
                    nested_href = nested_tag["href"]
                    if nested_href.endswith(".pdf"):
                        continue
                    nested_url = _resolve_url(nested_href, detail_url)
                    nested_title, nested_published_at, nested_precision, _ = _extract_anchor_fallback(
                        nested_tag, cfg
                    )
                    item = self._fetch_detail_page(source_id, cfg, nested_url)
                    if item and (not item.published_at or item.published_precision == "estimated"):
                        return GovReportItem(
                            source=item.source,
                            source_id=item.source_id,
                            title=item.title or nested_title,
                            url=item.url,
                            published_at=nested_published_at,
                            published_precision=nested_precision,
                            institution=item.institution,
                            country=item.country,
                            language=item.language,
                            data_category=item.data_category,
                            importance=item.importance,
                            description=item.description,
                            content_markdown=item.content_markdown,
                            raw_json=item.raw_json,
                        )
                    if item:
                        return item
                    continue
            return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_detail_page(self, source_id: str, cfg: dict, url: str) -> GovReportItem | None:
        html = _get_html(self.session, url)
        title = _extract_title(html, cfg["title_selectors"])
        exact_published_at = _extract_structured_datetime(
            html,
            default_timezone=cfg.get("default_timezone", "UTC"),
        ) or _extract_datetime_en(
            html,
            cfg.get("datetime_patterns", []),
            default_timezone=cfg.get("default_timezone", "UTC"),
        )
        published_at = exact_published_at or _extract_date_en(html, cfg["date_patterns"])
        published_precision = "exact" if exact_published_at else ("date_only" if published_at else "estimated")
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=published_at or "",
            published_precision=published_precision,
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


class CNGovReportClient:
    """Scraper for Chinese government institution reports."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _CN_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("CN gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "listing_keywords":
            return self._fetch_listing_keywords(source_id, cfg)
        return None

    def _fetch_listing_keywords(self, source_id: str, cfg: dict) -> GovReportItem | None:
        encoding = cfg.get("encoding", "utf-8")
        html = _get_html(self.session, cfg["url"], encoding=encoding)
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        keywords = cfg["keywords"]
        extra_keywords = cfg.get("extra_keywords")

        link_must_contain = cfg.get("link_must_contain")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if link_must_contain and link_must_contain not in href:
                continue
            if _link_matches_keywords(a_tag, keywords, extra_keywords):
                if href.endswith(".pdf"):
                    continue
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url, encoding)
        return None

    def _fetch_detail_page(
        self, source_id: str, cfg: dict, url: str, encoding: str
    ) -> GovReportItem | None:
        html = _get_html(self.session, url, encoding=encoding)
        title = _extract_title(html, cfg["title_selectors"])
        exact_published_at = _extract_datetime_cn(html)
        published_at = exact_published_at or _extract_date_cn(html)
        if not published_at:
            published_at = _extract_date_en(html, cfg["date_patterns"])
        published_precision = "exact" if exact_published_at else ("date_only" if published_at else "estimated")
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=published_at or "",
            published_precision=published_precision,
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


class JPGovReportClient:
    """Scraper for Japanese government institution reports."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _JP_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("JP gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        if source_id == "jp_cao_gdp":
            return self._fetch_cao_gdp(source_id, cfg)
        strategy = cfg["strategy"]
        if strategy == "listing_regex":
            return self._fetch_listing_regex(source_id, cfg)
        return None

    def _fetch_listing_regex(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        archive_pattern = re.compile(cfg.get("archive_link_pattern", cfg["link_pattern"]))
        detail_pattern = re.compile(cfg["link_pattern"])

        if not cfg.get("archive_link_pattern"):
            a_tag = _select_latest_matching_anchor(soup, detail_pattern, cfg)
            if not a_tag:
                return None
            href = a_tag["href"]
            if href.endswith(".pdf") and cfg.get("allow_pdf_links"):
                return _build_anchor_asset_item(
                    source_id=source_id,
                    cfg=cfg,
                    tag=a_tag,
                    base_url=base_url,
                )
            if href.endswith(".pdf"):
                return None
            return self._fetch_detail_page(source_id, cfg, _resolve_url(href, base_url))

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if not archive_pattern.search(href):
                continue
            detail_url = _resolve_url(href, base_url)
            if cfg.get("archive_link_pattern"):
                archive_html = _get_html(self.session, detail_url)
                archive_soup = BeautifulSoup(archive_html, "html.parser")
                nested_tag = _select_latest_matching_anchor(archive_soup, detail_pattern, cfg)
                if nested_tag:
                    nested_href = nested_tag["href"]
                    if nested_href.endswith(".pdf") and cfg.get("allow_pdf_links"):
                        return _build_anchor_asset_item(
                            source_id=source_id,
                            cfg=cfg,
                            tag=nested_tag,
                            base_url=detail_url,
                        )
                    if nested_href.endswith(".pdf"):
                        continue
                    nested_url = _resolve_url(nested_href, detail_url)
                    fallback_title, fallback_published_at, fallback_precision, _ = _extract_anchor_fallback(
                        nested_tag, cfg
                    )
                    item = self._fetch_detail_page(source_id, cfg, nested_url)
                    if item and (not item.published_at or item.published_precision == "estimated"):
                        return GovReportItem(
                            source=item.source,
                            source_id=item.source_id,
                            title=item.title or fallback_title,
                            url=item.url,
                            published_at=fallback_published_at,
                            published_precision=fallback_precision,
                            institution=item.institution,
                            country=item.country,
                            language=item.language,
                            data_category=item.data_category,
                            importance=item.importance,
                            description=item.description,
                            content_markdown=item.content_markdown,
                            raw_json=item.raw_json,
                        )
                    if item:
                        return item
                    continue
                continue
        return None

    def _fetch_detail_page(self, source_id: str, cfg: dict, url: str) -> GovReportItem | None:
        html = _get_html(self.session, url)
        title = _extract_title(html, cfg["title_selectors"])
        exact_published_at = _extract_structured_datetime(
            html,
            default_timezone=cfg.get("default_timezone", "UTC"),
        ) or _extract_datetime_en(
            html,
            cfg.get("datetime_patterns", []),
            default_timezone=cfg.get("default_timezone", "UTC"),
        )
        date = exact_published_at or _extract_date_en(html, cfg["date_patterns"])
        published_precision = "exact" if exact_published_at else ("date_only" if date else "estimated")
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=date or "",
            published_precision=published_precision,
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )

    def _fetch_cao_gdp(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])

        archive_url = ""
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.endswith("files/toukei_top.html"):
                archive_url = _resolve_url(href, base_url)
                break
        if not archive_url:
            return None

        archive_html = _get_html(self.session, archive_url)
        archive_soup = BeautifulSoup(archive_html, "html.parser")
        year_url = ""
        year_pattern = re.compile(cfg.get("archive_link_pattern", ""))
        for a_tag in archive_soup.find_all("a", href=True):
            href = a_tag["href"]
            if year_pattern.search(href):
                year_url = _resolve_url(href, archive_url)
                break
        if not year_url:
            return None

        year_html = _get_html(self.session, year_url)
        year_soup = BeautifulSoup(year_html, "html.parser")
        detail_pattern = re.compile(cfg["link_pattern"])
        a_tag = _select_latest_matching_anchor(year_soup, detail_pattern, cfg)
        if a_tag:
            href = a_tag["href"]
            detail_url = _resolve_url(href, year_url)
            fallback_title, fallback_published_at, fallback_precision, _ = _extract_anchor_fallback(a_tag, cfg)
            item = self._fetch_detail_page(source_id, cfg, detail_url)
            if item and fallback_published_at:
                return GovReportItem(
                    source=item.source,
                    source_id=item.source_id,
                    title=item.title or fallback_title,
                    url=item.url,
                    published_at=fallback_published_at,
                    published_precision=fallback_precision,
                    institution=item.institution,
                    country=item.country,
                    language=item.language,
                    data_category=item.data_category,
                    importance=item.importance,
                    description=item.description,
                    content_markdown=item.content_markdown,
                    raw_json=item.raw_json,
                )
            if item and (not item.published_at or item.published_precision == "estimated"):
                return GovReportItem(
                    source=item.source,
                    source_id=item.source_id,
                    title=item.title or fallback_title,
                    url=item.url,
                    published_at=fallback_published_at,
                    published_precision=fallback_precision,
                    institution=item.institution,
                    country=item.country,
                    language=item.language,
                    data_category=item.data_category,
                    importance=item.importance,
                    description=item.description,
                    content_markdown=item.content_markdown,
                    raw_json=item.raw_json,
                )
            return item
        return None


class EUGovReportClient:
    """Scraper for EU institution reports (ECB, Eurostat)."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _EU_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("EU gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "listing_regex":
            return self._fetch_listing_regex(source_id, cfg)
        if strategy == "listing_keywords":
            return self._fetch_listing_keywords(source_id, cfg)
        if strategy == "rss":
            return self._fetch_rss(source_id, cfg)
        return None

    def _fetch_listing_regex(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        pattern = re.compile(cfg["link_pattern"])

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if pattern.search(href):
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_listing_keywords(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        keywords = cfg["keywords"]

        for a_tag in soup.find_all("a", href=True):
            if _link_matches_keywords(a_tag, keywords):
                href = a_tag["href"]
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_rss(self, source_id: str, cfg: dict) -> GovReportItem | None:
        parsed = feedparser.parse(cfg["url"])
        if not parsed.entries:
            return None
        entry = parsed.entries[0]
        link = entry.get("link", "")
        if not link:
            return None

        title = entry.get("title", "")
        published = entry.get("published", "")
        rss_published_at, rss_published_precision = _parse_rss_published(
            published,
            default_timezone=cfg.get("default_timezone", "UTC"),
        )

        # Try to scrape the full page
        try:
            detail = self._fetch_detail_page(source_id, cfg, link)
            if detail:
                merged_at, merged_precision = _merge_published_values(
                    preferred_at=detail.published_at,
                    preferred_precision=detail.published_precision,
                    fallback_at=rss_published_at or "",
                    fallback_precision=rss_published_precision,
                )
                return GovReportItem(
                    source=detail.source,
                    source_id=detail.source_id,
                    title=detail.title or title,
                    url=detail.url,
                    published_at=merged_at,
                    published_precision=merged_precision,
                    institution=detail.institution,
                    country=detail.country,
                    language=detail.language,
                    data_category=detail.data_category,
                    importance=detail.importance,
                    content_markdown=detail.content_markdown,
                )
        except Exception:
            pass

        # Fallback: use RSS metadata only
        summary = BeautifulSoup(
            entry.get("summary", ""), "html.parser"
        ).get_text(" ", strip=True)
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower()}",
            source_id=source_id,
            title=title,
            url=link,
            published_at=rss_published_at or "",
            published_precision=rss_published_precision,
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            description=summary,
        )

    def _fetch_detail_page(self, source_id: str, cfg: dict, url: str) -> GovReportItem | None:
        html = _get_html(self.session, url)
        title = _extract_title(html, cfg["title_selectors"])
        exact_published_at = _extract_structured_datetime(
            html,
            default_timezone=cfg.get("default_timezone", "UTC"),
        ) or _extract_datetime_en(
            html,
            cfg.get("datetime_patterns", []),
            default_timezone=cfg.get("default_timezone", "UTC"),
        )
        date = exact_published_at or _extract_date_en(html, cfg["date_patterns"])
        published_precision = "exact" if exact_published_at else ("date_only" if date else "estimated")
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower()}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=date or "",
            published_precision=published_precision,
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


class GovReportClient:
    """Unified facade for all government report scrapers."""

    def __init__(self) -> None:
        self.us = USGovReportClient()
        self.cn = CNGovReportClient()
        self.jp = JPGovReportClient()
        self.eu = EUGovReportClient()

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for region_client, label in [
            (self.us, "US"),
            (self.cn, "CN"),
            (self.jp, "JP"),
            (self.eu, "EU"),
        ]:
            try:
                items.extend(region_client.fetch_all())
            except Exception:
                logger.warning("Gov report region fetch failed: %s", label, exc_info=True)
        return items

    def fetch_us(self) -> list[GovReportItem]:
        return self.us.fetch_all()

    def fetch_cn(self) -> list[GovReportItem]:
        return self.cn.fetch_all()

    def fetch_jp(self) -> list[GovReportItem]:
        return self.jp.fetch_all()

    def fetch_eu(self) -> list[GovReportItem]:
        return self.eu.fetch_all()

