"""Bloomberg scraper – news listings and full article extraction.

Uses Playwright + stealth for browser automation (Bloomberg is React-rendered
with aggressive bot detection). Cookies are persisted to
``~/.analyst/bloomberg_cookies.json`` after a one-time manual login.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from ._common import ScrapedNewsItem

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bloomberg.com"
COOKIE_PATH = Path.home() / ".analyst" / "bloomberg_cookies.json"

BLOOMBERG_SECTIONS = {
    "markets": "/markets",
    "economics": "/economics",
    "technology": "/technology",
    "politics": "/politics",
    "wealth": "/wealth",
    "opinion": "/opinion",
    "green": "/green",
}

# Boilerplate patterns filtered from article body text.
_BOILERPLATE_PATTERNS = (
    "sign up for",
    "subscribe to",
    "read more:",
    "newsletter",
    "Bloomberg Businessweek",
    "terms of service",
    "privacy policy",
    "with assistance from",
)


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------

class BloombergAuthError(Exception):
    """Raised when Bloomberg authentication is missing or expired."""


# ------------------------------------------------------------------
# Data class for full article content
# ------------------------------------------------------------------

@dataclass
class BloombergArticle:
    """Parsed full article from Bloomberg."""

    url: str
    title: str
    content: str  # body as plain text
    authors: list[str] = field(default_factory=list)
    published_at: str = ""
    section: str = ""
    keywords: list[str] = field(default_factory=list)
    image_url: str = ""
    lede: str = ""  # Bloomberg-specific article summary
    fetched: bool = True
    error: str | None = None


# ------------------------------------------------------------------
# Playwright browser helper
# ------------------------------------------------------------------

class _BloombergBrowser:
    """Manages a stealth Playwright Chrome instance with cookie persistence.

    Uses the system Google Chrome (``channel="chrome"``) with a persistent
    user-data directory at ``~/.analyst/bloomberg_profile/`` so that the
    browser looks like a normal desktop session to Bloomberg's bot
    detection.  Both :class:`BloombergNewsClient` and
    :class:`BloombergArticleClient` compose this helper.

    Supports context-manager usage::

        with _BloombergBrowser() as browser:
            browser.page.goto("https://www.bloomberg.com/markets")
    """

    _PROFILE_DIR = Path.home() / ".analyst" / "bloomberg_profile"

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Any = None
        self._context: Any = None  # persistent context (acts as browser)
        self.page: Any = None

    # -- lifecycle ---------------------------------------------------

    def start(self) -> None:
        """Launch system Chrome with a persistent profile and stealth patches."""
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
        except ImportError as exc:
            raise ImportError(
                "Bloomberg scraper requires playwright and playwright-stealth. "
                "Install with: pip install playwright playwright-stealth && "
                "playwright install chromium"
            ) from exc

        self._PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()

        # launch_persistent_context uses system Chrome via channel and
        # keeps a real user-data-dir on disk (cookies, localStorage, etc.)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._PROFILE_DIR),
            channel="chrome",
            headless=self._headless,
            viewport={"width": 1920, "height": 1080},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        # Load any previously-exported cookies into the profile.
        self._load_cookies()

        if self._context.pages:
            self.page = self._context.pages[0]
        else:
            self.page = self._context.new_page()

        Stealth().apply_stealth_sync(self.page)

    def stop(self) -> None:
        """Close all Playwright resources (idempotent)."""
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        self.page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self) -> _BloombergBrowser:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- authentication ---------------------------------------------

    def login(self) -> None:
        """Open a headful browser for manual Bloomberg login.

        Waits up to 5 minutes for the user to complete sign-in, then
        saves cookies and restarts in headless mode.
        """
        # Restart headful if currently headless.
        was_headless = self._headless
        self.stop()
        self._headless = False
        self.start()

        self.page.goto(f"{BASE_URL}/account/signin", wait_until="domcontentloaded")
        logger.info(
            "Please log in to Bloomberg in the browser window. "
            "Waiting up to 5 minutes …"
        )
        print(
            "\n*** Bloomberg Login ***\n"
            "Log in to your Bloomberg account in the browser window.\n"
            "This script will continue automatically once sign-in completes.\n"
        )

        try:
            # Wait for navigation away from the sign-in page.
            self.page.wait_for_function(
                "() => !window.location.pathname.includes('/signin')",
                timeout=300_000,
            )
        except Exception as exc:
            self.stop()
            raise BloombergAuthError(
                "Login timed out or was cancelled."
            ) from exc

        self.save_cookies()
        logger.info("Cookies saved to %s", COOKIE_PATH)

        # Restart headless if that was the original mode.
        if was_headless:
            self.stop()
            self._headless = True
            self.start()

    def save_cookies(self) -> None:
        """Persist browser cookies to disk."""
        if self._context is None:
            return
        COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cookies = self._context.cookies()
        COOKIE_PATH.write_text(json.dumps(cookies, indent=2))

    def _load_cookies(self) -> None:
        """Load cookies from disk into the browser context, filtering expired."""
        if not COOKIE_PATH.exists() or self._context is None:
            return
        try:
            cookies = json.loads(COOKIE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read cookie file; ignoring.")
            return
        now = time.time()
        valid = [
            c for c in cookies
            if c.get("expires", -1) == -1 or c.get("expires", 0) > now
        ]
        if valid:
            self._context.add_cookies(valid)

    def is_authenticated(self) -> bool:
        """Check whether the current session has Bloomberg access."""
        if self.page is None:
            return False
        try:
            self.page.goto(
                f"{BASE_URL}/markets", wait_until="domcontentloaded", timeout=30_000,
            )
            # Bloomberg shows a paywall fence for unauthenticated users.
            fence = self.page.query_selector("[class*='paywall'], [class*='fence']")
            return fence is None
        except Exception:
            return False

    def ensure_session(self) -> None:
        """Validate authentication; raise :class:`BloombergAuthError` if invalid."""
        if not self.is_authenticated():
            raise BloombergAuthError(
                "Bloomberg session is not authenticated. "
                "Run login() first or check your cookies at "
                f"{COOKIE_PATH}"
            )

    def ensure_started(self) -> None:
        """Restart the browser if it has been closed or crashed."""
        if self.page is None or self._context is None:
            self.stop()
            self.start()


# ------------------------------------------------------------------
# News listing client
# ------------------------------------------------------------------

class BloombergNewsClient:
    """Scrapes article listings from Bloomberg section pages."""

    def __init__(self, *, headless: bool = True, browser: _BloombergBrowser | None = None) -> None:
        self._owns_browser = browser is None
        self._browser = browser or _BloombergBrowser(headless=headless)

    def __enter__(self) -> BloombergNewsClient:
        if self._owns_browser:
            self._browser.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owns_browser:
            self._browser.stop()

    def fetch_news(self, *, section: str = "markets") -> list[ScrapedNewsItem]:
        """Fetch article listings from a single Bloomberg section."""
        self._browser.ensure_started()
        path = BLOOMBERG_SECTIONS.get(section, f"/{section}")
        url = f"{BASE_URL}{path}"

        try:
            self._browser.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Wait for story cards to render.
            self._browser.page.wait_for_selector(
                "article, [data-component='story'], [class*='story']",
                timeout=15_000,
            )
        except Exception as exc:
            logger.warning("Bloomberg page load failed for %s: %s", section, exc)
            return []

        html = self._browser.page.content()
        return self._parse_listing_html(html, section)

    def fetch_all_news(
        self,
        *,
        sections: list[str] | None = None,
        sleep_between: float = 7.0,
    ) -> list[ScrapedNewsItem]:
        """Fetch article listings from multiple sections with delay.

        *sections* defaults to ``["markets", "economics", "technology"]``.
        """
        targets = sections or ["markets", "economics", "technology"]
        all_items: list[ScrapedNewsItem] = []
        seen_urls: set[str] = set()

        for idx, section in enumerate(targets):
            try:
                items = self.fetch_news(section=section)
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        all_items.append(item)
            except Exception as exc:
                logger.warning("Bloomberg listing fetch failed for %s: %s", section, exc)
            if idx < len(targets) - 1:
                time.sleep(sleep_between)

        return all_items

    # ---- internal --------------------------------------------------

    def _parse_listing_html(self, html: str, section: str) -> list[ScrapedNewsItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[ScrapedNewsItem] = []
        seen: set[str] = set()

        # Strategy 1: __NEXT_DATA__ JSON (React hydration payload).
        next_data = self._try_next_data(soup, section)
        if next_data:
            for item in next_data:
                if item.url not in seen:
                    seen.add(item.url)
                    items.append(item)
            return items

        # Strategy 2: JSON-LD structured data.
        ld_items = self._try_json_ld(soup, section)
        if ld_items:
            for item in ld_items:
                if item.url not in seen:
                    seen.add(item.url)
                    items.append(item)
            return items

        # Strategy 3: DOM article elements.
        for article in soup.find_all("article"):
            item = self._parse_article_card(article, section)
            if item and item.url not in seen:
                seen.add(item.url)
                items.append(item)

        # Also try generic story containers.
        for card in soup.find_all(
            ["div", "section"],
            class_=lambda c: c and ("story" in c.lower() if isinstance(c, str)
                                     else any("story" in x.lower() for x in c)),
        ):
            item = self._parse_article_card(card, section)
            if item and item.url not in seen:
                seen.add(item.url)
                items.append(item)

        return items

    def _try_next_data(self, soup: BeautifulSoup, section: str) -> list[ScrapedNewsItem]:
        """Extract articles from __NEXT_DATA__ JSON if present."""
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not script.string:
            return []
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return []

        items: list[ScrapedNewsItem] = []
        # Walk the JSON tree looking for story objects.
        self._walk_next_data(data, items, section)
        return items

    def _walk_next_data(self, obj: Any, items: list[ScrapedNewsItem], section: str) -> None:
        """Recursively walk a JSON structure extracting story-like objects."""
        if isinstance(obj, dict):
            # Heuristic: a story has a "headline" or "title" and a URL-like field.
            headline = obj.get("headline") or obj.get("title") or ""
            url = obj.get("url") or obj.get("canonical") or obj.get("href") or ""
            if headline and url and isinstance(headline, str) and isinstance(url, str):
                if not url.startswith("http"):
                    url = f"{BASE_URL}{url}"
                if "/news/" in url or "/articles/" in url or "/opinion/" in url:
                    items.append(ScrapedNewsItem(
                        source="bloomberg",
                        title=headline,
                        url=url,
                        published_at=str(obj.get("publishedAt", obj.get("published", ""))),
                        description=str(obj.get("summary", obj.get("abstract", ""))),
                        category=str(obj.get("primaryCategory", obj.get("section", section))),
                        image_url=str(obj.get("imageUrl", obj.get("image", ""))),
                    ))
            for v in obj.values():
                self._walk_next_data(v, items, section)
        elif isinstance(obj, list):
            for v in obj:
                self._walk_next_data(v, items, section)

    def _try_json_ld(self, soup: BeautifulSoup, section: str) -> list[ScrapedNewsItem]:
        """Extract articles from JSON-LD structured data."""
        items: list[ScrapedNewsItem] = []
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, list):
                for entry in data:
                    item = self._ld_to_news_item(entry, section)
                    if item:
                        items.append(item)
            elif isinstance(data, dict):
                item = self._ld_to_news_item(data, section)
                if item:
                    items.append(item)
        return items

    def _ld_to_news_item(self, data: dict, section: str) -> ScrapedNewsItem | None:
        """Convert a JSON-LD entry to ScrapedNewsItem if it looks like an article."""
        if not isinstance(data, dict):
            return None
        ld_type = data.get("@type", "")
        if "Article" not in ld_type and "NewsArticle" not in ld_type:
            return None
        title = data.get("headline", "")
        url = data.get("url", "")
        if not title or not url:
            return None
        return ScrapedNewsItem(
            source="bloomberg",
            title=title,
            url=url if url.startswith("http") else f"{BASE_URL}{url}",
            published_at=data.get("datePublished", ""),
            description=data.get("description", ""),
            category=data.get("articleSection", section),
            image_url=self._ld_image(data),
        )

    @staticmethod
    def _ld_image(data: dict) -> str:
        images = data.get("image", [])
        if isinstance(images, str):
            return images
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                return first.get("url", "")
        if isinstance(images, dict):
            return images.get("url", "")
        return ""

    def _parse_article_card(self, card: Tag, section: str) -> ScrapedNewsItem | None:
        """Parse a DOM element that looks like a story card."""
        try:
            # Find the primary link.
            link = card.find("a", href=True)
            if not link:
                return None
            href = link.get("href", "")
            if not href:
                return None
            full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            # Must look like an article URL.
            if not any(seg in full_url for seg in ("/news/", "/articles/", "/opinion/", "/features/")):
                return None

            # Title: prefer heading elements, fall back to link text.
            title = ""
            for tag in ("h1", "h2", "h3", "h4"):
                heading = card.find(tag)
                if heading:
                    title = heading.get_text(strip=True)
                    break
            if not title:
                title = link.get_text(strip=True)
            if not title:
                return None

            # Timestamp.
            published_at = ""
            time_el = card.find("time")
            if time_el:
                published_at = time_el.get("datetime", "") or time_el.get_text(strip=True)

            # Description / summary.
            description = ""
            summary_el = card.find("p")
            if summary_el:
                description = summary_el.get_text(strip=True)

            # Image.
            image_url = ""
            img = card.find("img")
            if img:
                image_url = img.get("src", "") or img.get("data-src", "")

            return ScrapedNewsItem(
                source="bloomberg",
                title=title,
                url=full_url,
                published_at=published_at,
                description=description,
                category=section,
                image_url=image_url,
            )
        except Exception:
            return None


# ------------------------------------------------------------------
# Full article client
# ------------------------------------------------------------------

class BloombergArticleClient:
    """Fetches and parses full Bloomberg articles with structured metadata.

    Requires an authenticated session (cookies). Use
    :meth:`_BloombergBrowser.login` for first-time setup.
    """

    def __init__(self, *, headless: bool = True, browser: _BloombergBrowser | None = None) -> None:
        self._owns_browser = browser is None
        self._browser = browser or _BloombergBrowser(headless=headless)

    def __enter__(self) -> BloombergArticleClient:
        if self._owns_browser:
            self._browser.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owns_browser:
            self._browser.stop()

    def fetch_article(self, url: str) -> BloombergArticle:
        """Fetch and parse a single Bloomberg article."""
        self._browser.ensure_started()
        try:
            self._browser.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Wait for the article body to render.
            self._browser.page.wait_for_selector(
                "article, [class*='body'], [class*='article']",
                timeout=15_000,
            )
            html = self._browser.page.content()
            return self._parse_article_html(html, url)
        except Exception as exc:
            logger.warning("Bloomberg article fetch failed for %s: %s", url, exc)
            return BloombergArticle(
                url=url, title="", content="",
                fetched=False, error=str(exc),
            )

    def fetch_articles(
        self,
        urls: list[str],
        *,
        sleep_between: float = 7.0,
    ) -> list[BloombergArticle]:
        """Fetch multiple articles with rate limiting."""
        articles: list[BloombergArticle] = []
        for idx, url in enumerate(urls):
            articles.append(self.fetch_article(url))
            if idx < len(urls) - 1:
                time.sleep(sleep_between)
        return articles

    # ---- internal --------------------------------------------------

    def _parse_article_html(self, html: str, url: str) -> BloombergArticle:
        soup = BeautifulSoup(html, "html.parser")

        # --- Tier 1: JSON-LD metadata (most reliable) -----------------
        section = ""
        keywords: list[str] = []
        image_url = ""
        ld_published = ""
        ld_title = ""
        ld_authors: list[str] = []
        ld_description = ""

        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and "Article" in data.get("@type", ""):
                ld_title = data.get("headline", "")
                section = data.get("articleSection", "")
                keywords = data.get("keywords", [])
                if isinstance(keywords, str):
                    keywords = [keywords]
                ld_description = data.get("description", "")
                ld_published = data.get("datePublished", "")
                images = data.get("image", [])
                if isinstance(images, list) and images:
                    first = images[0]
                    image_url = first if isinstance(first, str) else first.get("url", "")
                elif isinstance(images, str):
                    image_url = images
                elif isinstance(images, dict):
                    image_url = images.get("url", "")
                # Authors from JSON-LD.
                authors_raw = data.get("author", [])
                if isinstance(authors_raw, dict):
                    authors_raw = [authors_raw]
                if isinstance(authors_raw, list):
                    for a in authors_raw:
                        name = a.get("name", "") if isinstance(a, dict) else str(a)
                        if name:
                            ld_authors.append(name)
                break

        # --- Tier 2: OpenGraph meta tags ------------------------------
        og_title = self._meta(soup, "og:title")
        og_image = self._meta(soup, "og:image")
        og_published = (
            self._meta(soup, "article:published_time")
            or self._meta(soup, "article:published")
        )
        og_authors: list[str] = []
        for meta in soup.find_all("meta", {"property": "article:author"}):
            author = meta.get("content", "")
            if author:
                og_authors.append(author)
        og_section = self._meta(soup, "article:section")

        # --- Tier 3: DOM selectors ------------------------------------
        # Headline.
        title = ld_title or og_title or ""
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # Authors.
        authors = ld_authors or og_authors
        if not authors:
            # Bloomberg author bylines.
            for a in soup.find_all("a", href=lambda h: h and "/authors/" in h):
                name = a.get_text(strip=True)
                if name and name not in authors:
                    authors.append(name)

        # Published date.
        published_at = ld_published or og_published or ""
        if not published_at:
            time_el = soup.find("time")
            if time_el:
                published_at = time_el.get("datetime", "")

        # Section.
        if not section:
            section = og_section or ""

        # Image.
        if not image_url:
            image_url = og_image or ""

        # Lede / summary.
        lede = ld_description or self._meta(soup, "og:description") or ""

        # --- Body paragraphs ------------------------------------------
        paragraphs = self._extract_body(soup)
        content = "\n\n".join(paragraphs)

        return BloombergArticle(
            url=url,
            title=title,
            content=content,
            authors=authors,
            published_at=published_at,
            section=section,
            keywords=keywords,
            image_url=image_url,
            lede=lede,
            fetched=bool(content),
            error=None if content else "empty article body",
        )

    def _extract_body(self, soup: BeautifulSoup) -> list[str]:
        """Extract article body paragraphs, filtering boilerplate."""
        paragraphs: list[str] = []

        # Bloomberg renders body in <p> tags within an article container.
        # Try to find the article body container first.
        body_container = (
            soup.find("div", class_=lambda c: c and "body" in c.lower()
                       if isinstance(c, str)
                       else c and any("body" in x.lower() for x in c))
            or soup.find("article")
            or soup
        )

        for p in body_container.find_all("p"):
            text = p.get_text(strip=True)
            if text and not self._is_boilerplate(text):
                paragraphs.append(text)

        return paragraphs

    @staticmethod
    def _is_boilerplate(text: str) -> bool:
        """Filter common Bloomberg boilerplate lines."""
        lower = text.lower()
        if len(text) > 200:
            return False
        return any(bp in lower for bp in _BOILERPLATE_PATTERNS)

    @staticmethod
    def _meta(soup: BeautifulSoup, prop: str) -> str:
        """Get content of a <meta property=...> tag."""
        tag = soup.find("meta", {"property": prop}) or soup.find("meta", {"name": prop})
        if tag:
            return tag.get("content", "")
        return ""
