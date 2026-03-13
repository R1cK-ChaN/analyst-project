from __future__ import annotations

import json
import re
from datetime import timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from markdownify import markdownify as md

from .gov_report_models import GovReportItem

_TZINFOS = {
    "UTC": timezone.utc,
    "GMT": timezone.utc,
    "ET": ZoneInfo("America/New_York"),
    "EST": ZoneInfo("America/New_York"),
    "EDT": ZoneInfo("America/New_York"),
}


_BLS_EMBARGO_DATETIME_PATTERN = (
    r"embargoed until.*?([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*"
    r"(?:\([A-Z]{2,4}\)|[A-Z]{2,4})\s*\w+,\s*\w+\s+\d{1,2},\s*\d{4})"
)


_RELEASE_AT_DATETIME_PATTERN = (
    r"(\w+\s+\d{1,2},\s*\d{4}.*?For release at\s+[0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*"
    r"(?:\([A-Z]{2,4}\)|[A-Z]{2,4})?)"
)


_COMMON_EN_DATE_PATTERNS = [
    r"([A-Za-z]{3,9}\.?\s+\d{1,2}(?:\s*\([A-Za-z]{3,9}\.?\))?,?\s*\d{4})",
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    r"(\d{4}[/-]\d{1,2}[/-]\d{1,2})",
]


_STRUCTURED_DATE_KEYS = (
    "article:published_time",
    "published_time",
    "publishdate",
    "datepublished",
    "datecreated",
    "date",
    "dc.date",
    "dcterms.issued",
    "dcterms.created",
    "citation_publication_date",
    "citation_online_date",
)


_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


_NOISE_SELECTORS = ["script", "style", "nav", "noscript", "header", "footer", "iframe"]


_NOISE_CLASSES = [
    ".breadcrumb", ".pagination", ".social-share", ".sidebar",
    "#sidebar", ".nav", ".menu", ".footer", ".header",
]


def _get_html(
    session: requests.Session,
    url: str,
    *,
    timeout: int = 30,
    encoding: str | None = None,
) -> str:
    """Fetch a URL and return its HTML as a string."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    if encoding:
        resp.encoding = encoding
    return resp.text

def _extract_content(html: str, selectors: list[str]) -> str:
    """Extract the main content region via CSS selector priority list.

    Returns inner HTML of the first matching selector after removing noise
    elements. Falls back to <body> if no selector matches.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_NOISE_SELECTORS):
        tag.decompose()
    for sel in _NOISE_CLASSES:
        for el in soup.select(sel):
            el.decompose()

    for selector in selectors:
        match = soup.select_one(selector)
        if match:
            return str(match)
    body = soup.find("body")
    return str(body) if body else html

def _extract_title(html: str, selectors: list[str]) -> str:
    """Extract the page title using a selector priority list."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in selectors:
        match = soup.select_one(selector)
        if match:
            text = match.get_text(strip=True)
            if text:
                return text
    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else ""

def _extract_date_en(html: str, patterns: list[str]) -> str | None:
    """Extract a publication date via regex patterns, return YYYY-MM-DD or None."""
    text_content = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    search_spaces = [html, re.sub(r"\s+", " ", html), text_content]
    for search_text in search_spaces:
        for pattern in [*patterns, *_COMMON_EN_DATE_PATTERNS]:
            m = re.search(pattern, search_text, re.I | re.S)
            if m:
                raw = m.group(1) if m.lastindex else m.group(0)
                try:
                    dt = dateutil_parser.parse(raw, fuzzy=True)
                    return dt.strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    continue
    return None

def _extract_datetime_en(
    html: str,
    patterns: list[str],
    *,
    default_timezone: str = "UTC",
) -> str | None:
    """Extract an English publication datetime and normalize to UTC ISO."""
    text_content = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    for search_text in [html, re.sub(r"\s+", " ", html), text_content]:
        for pattern in patterns:
            m = re.search(pattern, search_text, re.I | re.S)
            if not m:
                continue
            raw = m.group(1) if m.lastindex else m.group(0)
            cleaned = re.sub(r"\(([A-Z]{2,4})\)", r" \1 ", raw)
            cleaned = re.sub(r"\ba\.m\.\b", "am", cleaned, flags=re.I)
            cleaned = re.sub(r"\bp\.m\.\b", "pm", cleaned, flags=re.I)
            try:
                dt = dateutil_parser.parse(cleaned, fuzzy=True, tzinfos=_TZINFOS)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo(default_timezone))
                return dt.astimezone(timezone.utc).isoformat()
            except (ValueError, OverflowError):
                continue
    return None

def _extract_structured_datetime(
    html: str,
    *,
    default_timezone: str = "UTC",
) -> str | None:
    """Extract exact publication timestamps from common metadata formats."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for meta in soup.find_all("meta"):
        key = " ".join(
            str(meta.get(attr, ""))
            for attr in ("property", "name", "itemprop")
            if meta.get(attr)
        ).lower()
        if not any(token in key for token in _STRUCTURED_DATE_KEYS):
            continue
        content = meta.get("content", "").strip()
        if content:
            candidates.append(content)

    for time_tag in soup.find_all("time"):
        raw = time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
        raw = raw.strip()
        if raw:
            candidates.append(raw)

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        if not script.string:
            continue
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            for key in ("datePublished", "dateCreated", "uploadDate"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
            for value in node.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

    seen: set[str] = set()
    for raw in candidates:
        if raw in seen or not re.search(r"\d{1,2}:\d{2}|T\d{2}:\d{2}", raw):
            continue
        seen.add(raw)
        cleaned = re.sub(r"\(([A-Z]{2,4})\)", r" \1 ", raw)
        try:
            dt = dateutil_parser.parse(cleaned, fuzzy=True, tzinfos=_TZINFOS)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(default_timezone))
            return dt.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            continue
    return None

def _clean_link_text(text: str) -> str:
    return re.sub(r"\s*\[\s*PDF.*?\]\s*", "", text, flags=re.I).strip()

def _anchor_context_text(tag: BeautifulSoup) -> str:
    anchor_text = tag.get_text(" ", strip=True)
    for ancestor in tag.parents:
        if getattr(ancestor, "name", "") not in {"tr", "li", "p", "div", "section", "article"}:
            continue
        text = ancestor.get_text(" ", strip=True)
        if text and text != anchor_text:
            return text
    return anchor_text

def _anchor_context_year(tag: BeautifulSoup) -> str:
    for ancestor in tag.parents:
        if getattr(ancestor, "name", "") == "table":
            caption = ancestor.find("caption")
            if caption:
                match = re.search(r"\b(20\d{2})\b", caption.get_text(" ", strip=True))
                if match:
                    return match.group(1)
        text = ancestor.get_text(" ", strip=True)
        years = re.findall(r"\b(20\d{2})\b", text)
        if len(set(years)) == 1:
            return years[0]
    return ""

def _select_latest_matching_anchor(
    soup: BeautifulSoup,
    pattern: re.Pattern[str],
    cfg: dict,
) -> BeautifulSoup | None:
    best_tag: BeautifulSoup | None = None
    best_rank: tuple[str, int] = ("", -1)
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not pattern.search(href):
            continue
        _, published_at, published_precision, _ = _extract_anchor_fallback(a_tag, cfg)
        rank = (published_at, 1 if published_precision == "exact" else 0)
        if rank > best_rank:
            best_tag = a_tag
            best_rank = rank
    return best_tag

def _extract_datetime_cn(
    html: str,
    *,
    default_timezone: str = "Asia/Shanghai",
) -> str | None:
    """Extract a Chinese publication datetime and normalize to UTC ISO."""
    candidates: list[str] = []

    meta = re.search(r'<meta\s+name=["\']PubDate["\']\s+content=["\']([^"\']+)["\']', html, re.I)
    if meta:
        candidates.append(meta.group(1).strip())

    patterns = [
        r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)",
        r"(\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}(?::\d{2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            candidates.append(match.group(1))

    seen: set[str] = set()
    for raw in candidates:
        if raw in seen:
            continue
        seen.add(raw)
        try:
            dt = dateutil_parser.parse(raw, fuzzy=True)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(default_timezone))
            return dt.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            continue
    return None

def _parse_rss_published(
    published: str,
    *,
    default_timezone: str = "UTC",
) -> tuple[str | None, str]:
    if not published:
        return None, "estimated"
    try:
        dt = dateutil_parser.parse(published, fuzzy=True)
    except (ValueError, OverflowError):
        return None, "estimated"
    has_time = bool(re.search(r"\d{1,2}:\d{2}|[ap]\.?m\.?|T\d{2}:\d{2}", published, re.I))
    if has_time:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(default_timezone))
        return dt.astimezone(timezone.utc).isoformat(), "exact"
    return dt.strftime("%Y-%m-%d"), "date_only"

def _merge_published_values(
    *,
    preferred_at: str,
    preferred_precision: str,
    fallback_at: str,
    fallback_precision: str,
) -> tuple[str, str]:
    if preferred_precision == "exact" and preferred_at:
        return preferred_at, preferred_precision
    if fallback_precision == "exact" and fallback_at:
        return fallback_at, fallback_precision
    if preferred_at:
        return preferred_at, preferred_precision or "date_only"
    if fallback_at:
        return fallback_at, fallback_precision or "date_only"
    return "", "estimated"

def _extract_date_cn(html: str) -> str | None:
    """Extract a publication date from Chinese gov pages.

    Priority: <meta name="PubDate"> → 年月日 regex → slash format.
    """
    # Meta tag first
    m = re.search(r'<meta\s+name=["\']PubDate["\']\s+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        raw = m.group(1).strip()
        try:
            dt = dateutil_parser.parse(raw, fuzzy=True)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            pass

    # Chinese date: 2024年3月15日
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Slash format: 2024/03/15
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", html)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None

def _html_to_markdown(html: str, *, max_chars: int = 15_000) -> str:
    """Convert HTML to clean markdown, stripping noise."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_NOISE_SELECTORS):
        tag.decompose()
    for sel in _NOISE_CLASSES:
        for el in soup.select(sel):
            el.decompose()
    # Remove comments
    from bs4 import Comment
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    text = md(str(soup), heading_style="ATX", strip=["img"])
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()[:max_chars]

def _resolve_url(href: str, base_url: str) -> str:
    """Convert a potentially relative URL to absolute."""
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base_url + "/", href)

def _link_matches_keywords(
    tag: BeautifulSoup,
    keywords: list[str],
    extra_keywords: list[str] | None = None,
) -> bool:
    """Check if an <a> tag's text (+ href) matches keyword criteria."""
    text = (tag.get_text(" ", strip=True) + " " + tag.get("href", "")).lower()
    primary_match = any(kw.lower() in text for kw in keywords)
    if not primary_match:
        return False
    if extra_keywords:
        return any(ek.lower() in text for ek in extra_keywords)
    return True

def _extract_anchor_fallback(
    tag: BeautifulSoup,
    cfg: dict,
) -> tuple[str, str, str, str]:
    title = _clean_link_text(tag.get_text(" ", strip=True))
    context_text = _anchor_context_text(tag)
    exact_published_at = _extract_datetime_en(
        context_text,
        cfg.get("datetime_patterns", []),
        default_timezone=cfg.get("default_timezone", "UTC"),
    )
    published_at = exact_published_at or _extract_date_en(context_text, cfg.get("date_patterns", []))
    if not published_at:
        year = ""
        year_pattern = cfg.get("asset_year_pattern")
        if year_pattern:
            href_match = re.search(year_pattern, tag.get("href", ""))
            if href_match:
                year = href_match.group(1)
        if not year:
            year = _anchor_context_year(tag)
        if year:
            anchor_text = _clean_link_text(tag.get_text(" ", strip=True))
            month_day = re.search(
                r"([A-Za-z]{3,9}\.?\s+\d{1,2}(?:\s*\([A-Za-z]{3,9}\.?\))?)",
                anchor_text,
            )
            if month_day:
                try:
                    parsed_year = int(year)
                    if cfg.get("asset_release_year_from_meeting_year"):
                        row = tag.find_parent("tr")
                        first_cell = row.find("td") if row else None
                        if first_cell:
                            meeting_month_day = re.search(
                                r"([A-Za-z]{3,9}\.?\s+\d{1,2}(?:\s*\([A-Za-z]{3,9}\.?\))?)",
                                first_cell.get_text(" ", strip=True),
                            )
                            if meeting_month_day:
                                release_month = dateutil_parser.parse(
                                    month_day.group(1), fuzzy=True
                                ).month
                                meeting_month = dateutil_parser.parse(
                                    meeting_month_day.group(1), fuzzy=True
                                ).month
                                if release_month < meeting_month:
                                    parsed_year += 1
                    published_at = dateutil_parser.parse(
                        f"{month_day.group(1)}, {parsed_year}",
                        fuzzy=True,
                    ).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    published_at = ""
    published_precision = "exact" if exact_published_at else ("date_only" if published_at else "estimated")
    return title, published_at or "", published_precision, context_text

def _build_anchor_asset_item(
    *,
    source_id: str,
    cfg: dict,
    tag: BeautifulSoup,
    base_url: str,
) -> GovReportItem:
    title, published_at, published_precision, context_text = _extract_anchor_fallback(tag, cfg)
    return GovReportItem(
        source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
        source_id=source_id,
        title=cfg.get("asset_title", title),
        url=_resolve_url(tag["href"], base_url),
        published_at=published_at,
        published_precision=published_precision,
        institution=cfg["institution"],
        country=cfg["country"],
        language=cfg["language"],
        data_category=cfg["data_category"],
        importance=cfg.get("importance", ""),
        description=context_text if context_text != title else "",
    )

