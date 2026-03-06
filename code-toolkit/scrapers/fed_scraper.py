"""
scrapers/fed_scraper.py

Scrapes Federal Reserve communications via official RSS feeds.
This is the MOST IMPORTANT source for the Analyst agent —
Fed language drives market expectations more than any data release.

Sources:
- Fed Press Releases (rate decisions, statements)
- Fed Speeches (Powell, Waller, Bowman, etc.)
- FOMC Minutes
- Fed Reports (Beige Book, Financial Stability Report)

All feeds are OFFICIAL and FREE — no scraping risk.
"""

import feedparser
import requests
import re
import time
from datetime import datetime, timezone
from typing import List, Dict
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from storage.event_store import store_central_bank_comm


# ─── Official Fed RSS Feeds ───

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

# FOMC calendar and minutes don't have RSS — we scrape the page
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_MINUTES_URL = "https://www.federalreserve.gov/monetarypolicy/fomcminutes{year}{month}{day}.htm"


# Known Fed speakers (for tagging)
FED_SPEAKERS = [
    "Powell", "Waller", "Bowman", "Williams", "Barr", "Cook", "Jefferson",
    "Kugler", "Musalem", "Goolsbee", "Bostic", "Daly", "Collins",
    "Harker", "Kashkari", "Logan", "Barkin", "Hammack", "Schmid",
]


def extract_speaker(title: str) -> str:
    """Extract Fed speaker name from a speech title."""
    for speaker in FED_SPEAKERS:
        if speaker.lower() in title.lower():
            return speaker
    return ""


class FedScraper:
    """
    Scrapes Federal Reserve communications.
    Uses official RSS feeds (reliable, no blocking risk).
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MacroResearchBot/1.0 (academic research)"
        })
    
    def scrape_all_feeds(self) -> List[Dict]:
        """Scrape all Fed RSS feeds and return new communications."""
        all_comms = []
        
        for feed_name, feed_config in FED_FEEDS.items():
            print(f"[Fed] Scraping {feed_name}...")
            comms = self._parse_feed(feed_config["url"], feed_config["content_type"])
            all_comms.extend(comms)
            time.sleep(1)
        
        print(f"[Fed] Found {len(all_comms)} total communications")
        return all_comms
    
    def _parse_feed(self, feed_url: str, content_type: str) -> List[Dict]:
        """Parse an RSS feed into communication dicts."""
        comms = []
        
        try:
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries:
                title = entry.get("title", "")
                url = entry.get("link", "")
                published = entry.get("published", "")
                summary = entry.get("summary", "")
                
                # Parse date
                published_dt = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_dt = datetime(*entry.published_parsed[:6]).isoformat()
                
                # Detect content type more precisely
                detected_type = content_type
                title_lower = title.lower()
                if "minute" in title_lower:
                    detected_type = "minutes"
                elif "statement" in title_lower or "fomc" in title_lower:
                    detected_type = "statement"
                elif "beige book" in title_lower:
                    detected_type = "beige_book"
                elif "testimony" in title_lower:
                    detected_type = "testimony"
                
                comm = {
                    "source": "fed",
                    "title": title,
                    "url": url,
                    "published_at": published_dt,
                    "content_type": detected_type,
                    "speaker": extract_speaker(title),
                    "full_text": summary,  # RSS gives summary; full text needs page fetch
                }
                
                comms.append(comm)
                
        except Exception as e:
            print(f"[Fed] Feed error ({feed_url}): {e}")
        
        return comms
    
    def fetch_full_text(self, url: str) -> str:
        """
        Fetch the full text of a Fed speech/statement.
        Critical for LLM analysis of Fed language.
        """
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                return ""
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Fed website uses specific divs for content
            content_div = (
                soup.find("div", {"id": "article"}) or
                soup.find("div", {"class": "col-xs-12 col-sm-8 col-md-8"}) or
                soup.find("div", {"class": "row"})
            )
            
            if content_div:
                # Remove script and style tags
                for tag in content_div.find_all(["script", "style", "nav"]):
                    tag.decompose()
                
                text = content_div.get_text(separator="\n", strip=True)
                # Clean up excessive whitespace
                text = re.sub(r'\n{3,}', '\n\n', text)
                return text[:50000]  # cap at 50K chars
            
            return ""
            
        except Exception as e:
            print(f"[Fed] Error fetching {url}: {e}")
            return ""
    
    def scrape_fomc_calendar(self) -> List[Dict]:
        """
        Scrape the FOMC meeting calendar for upcoming dates.
        """
        events = []
        
        try:
            resp = self.session.get(FOMC_CALENDAR_URL, timeout=30)
            if resp.status_code != 200:
                return []
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Find meeting date panels
            panels = soup.find_all("div", {"class": "fomc-meeting"})
            
            for panel in panels:
                date_div = panel.find("div", {"class": "fomc-meeting__date"})
                if date_div:
                    date_text = date_div.get_text(strip=True)
                    
                    # Check for statement/minutes links
                    has_statement = panel.find("a", string=re.compile("statement", re.I))
                    has_minutes = panel.find("a", string=re.compile("minutes", re.I))
                    
                    events.append({
                        "date": date_text,
                        "has_statement": bool(has_statement),
                        "has_minutes": bool(has_minutes),
                        "statement_url": has_statement.get("href", "") if has_statement else "",
                        "minutes_url": has_minutes.get("href", "") if has_minutes else "",
                    })
            
        except Exception as e:
            print(f"[Fed] FOMC calendar error: {e}")
        
        return events
    
    def scrape_and_store(self, fetch_full_text: bool = False):
        """
        Main function: scrape all feeds and store.
        
        Args:
            fetch_full_text: If True, also fetch full text of each speech/statement.
                            Slower but gives the Analyst agent much richer context.
        """
        comms = self.scrape_all_feeds()
        stored = 0
        
        for comm in comms:
            # Optionally fetch full text
            if fetch_full_text and comm.get("url"):
                print(f"  Fetching full text: {comm['title'][:60]}...")
                comm["full_text"] = self.fetch_full_text(comm["url"])
                time.sleep(2)  # be very respectful with full page fetches
            
            try:
                store_central_bank_comm(comm)
                stored += 1
            except Exception as e:
                print(f"[Fed] Store error: {e}")
        
        print(f"[Fed] Stored {stored}/{len(comms)} communications")
        return comms


# ─── ECB and BOJ feeds (same pattern) ───

ECB_FEEDS = {
    "press_releases": {
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "content_type": "statement",
    },
}

BOJ_FEEDS = {
    "announcements": {
        "url": "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "content_type": "announcement",
    },
}


class ECBScraper(FedScraper):
    """Same pattern as Fed, different feeds."""
    
    def scrape_all_feeds(self) -> List[Dict]:
        all_comms = []
        for feed_name, feed_config in ECB_FEEDS.items():
            comms = self._parse_feed(feed_config["url"], feed_config["content_type"])
            # Override source
            for c in comms:
                c["source"] = "ecb"
            all_comms.extend(comms)
        return all_comms


if __name__ == "__main__":
    from storage.event_store import init_db
    init_db()
    
    fed = FedScraper()
    
    print("=== Fed Communications ===")
    comms = fed.scrape_and_store(fetch_full_text=False)
    
    for comm in comms[:5]:
        print(f"  [{comm['content_type']}] {comm['title'][:80]}")
        if comm['speaker']:
            print(f"    Speaker: {comm['speaker']}")
    
    print("\n=== FOMC Calendar ===")
    meetings = fed.scrape_fomc_calendar()
    for m in meetings[:5]:
        print(f"  {m['date']} | Statement: {m['has_statement']} | Minutes: {m['has_minutes']}")
