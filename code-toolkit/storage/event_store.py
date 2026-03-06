"""
storage/event_store.py
Unified storage for all macro data - SQLite based, simple and reliable.
Stores economic events with point-in-time values to avoid look-ahead bias.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "macro_data.db"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent access
    return conn


def init_db():
    """Create all tables. Safe to call multiple times."""
    conn = get_connection()
    
    # Economic calendar events (the core table)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,           -- 'investing', 'forexfactory', 'fred'
            event_id TEXT,                  -- source-specific ID
            datetime_utc TEXT NOT NULL,     -- when the data was released
            country TEXT NOT NULL,          -- 'US', 'EU', 'JP', etc.
            indicator TEXT NOT NULL,        -- 'CPI YoY', 'NFP', 'GDP QoQ'
            category TEXT,                 -- 'inflation', 'employment', 'growth'
            importance TEXT,               -- 'high', 'medium', 'low'
            actual TEXT,                   -- the released value
            forecast TEXT,                 -- consensus expectation
            previous TEXT,                 -- prior period value
            revised_previous TEXT,         -- revised prior (if available)
            surprise REAL,                 -- actual - forecast (computed)
            unit TEXT,                     -- '%', 'K', 'B', etc.
            scraped_at TEXT NOT NULL,       -- when we captured this
            raw_json TEXT,                 -- full raw data for debugging
            UNIQUE(source, event_id)
        )
    """)
    
    # Market prices snapshot
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,           -- 'DXY', 'US10Y', 'BTCUSD', 'SPX'
            asset_class TEXT,              -- 'fx', 'bond', 'equity', 'commodity', 'crypto'
            price REAL NOT NULL,
            change_pct REAL,
            datetime_utc TEXT NOT NULL,
            scraped_at TEXT NOT NULL
        )
    """)
    
    # Fed and central bank communications
    conn.execute("""
        CREATE TABLE IF NOT EXISTS central_bank_comms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,           -- 'fed', 'ecb', 'boj'
            title TEXT NOT NULL,
            url TEXT UNIQUE,
            published_at TEXT,
            content_type TEXT,             -- 'speech', 'minutes', 'statement', 'press_conference'
            speaker TEXT,                  -- 'Powell', 'Waller', etc.
            summary TEXT,                  -- LLM-generated summary (filled later)
            full_text TEXT,                -- scraped full text
            scraped_at TEXT NOT NULL
        )
    """)
    
    # Analyst agent's regime state (persistent memory)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            regime_json TEXT NOT NULL,      -- full regime state as JSON
            trigger_event TEXT,            -- what caused the update
            notes TEXT                     -- analyst's reasoning
        )
    """)
    
    # Economic indicators (historical time series from FRED etc.)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id TEXT NOT NULL,        -- 'CPIAUCSL', 'UNRATE', 'GDP'
            source TEXT NOT NULL,           -- 'fred', 'ecb', 'bls'
            date TEXT NOT NULL,
            value REAL NOT NULL,
            scraped_at TEXT NOT NULL,
            UNIQUE(series_id, source, date)
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def store_calendar_event(event: dict):
    """Store a single calendar event. Upserts on (source, event_id)."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    
    # Compute surprise if we have actual and forecast
    surprise = None
    try:
        if event.get("actual") and event.get("forecast"):
            actual_f = float(str(event["actual"]).replace("%", "").replace("K", "").replace("M", "").replace("B", "").strip())
            forecast_f = float(str(event["forecast"]).replace("%", "").replace("K", "").replace("M", "").replace("B", "").strip())
            surprise = round(actual_f - forecast_f, 4)
    except (ValueError, TypeError):
        pass
    
    conn.execute("""
        INSERT OR REPLACE INTO calendar_events 
        (source, event_id, datetime_utc, country, indicator, category, 
         importance, actual, forecast, previous, revised_previous, 
         surprise, unit, scraped_at, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("source", "unknown"),
        event.get("event_id", f"{event.get('indicator','')}-{event.get('datetime_utc','')}"),
        event.get("datetime_utc", ""),
        event.get("country", ""),
        event.get("indicator", ""),
        event.get("category", ""),
        event.get("importance", ""),
        str(event.get("actual", "")) if event.get("actual") else None,
        str(event.get("forecast", "")) if event.get("forecast") else None,
        str(event.get("previous", "")) if event.get("previous") else None,
        str(event.get("revised_previous", "")) if event.get("revised_previous") else None,
        surprise,
        event.get("unit", ""),
        now,
        json.dumps(event)
    ))
    conn.commit()
    conn.close()


def store_market_price(symbol: str, asset_class: str, price: float, change_pct: float = None):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO market_prices (symbol, asset_class, price, change_pct, datetime_utc, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (symbol, asset_class, price, change_pct, now, now))
    conn.commit()
    conn.close()


def store_central_bank_comm(comm: dict):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO central_bank_comms 
            (source, title, url, published_at, content_type, speaker, full_text, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comm.get("source", ""),
            comm.get("title", ""),
            comm.get("url", ""),
            comm.get("published_at", ""),
            comm.get("content_type", ""),
            comm.get("speaker", ""),
            comm.get("full_text", ""),
            now
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # already exists
    conn.close()


def store_indicator(series_id: str, source: str, date: str, value: float):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO indicators (series_id, source, date, value, scraped_at)
        VALUES (?, ?, ?, ?, ?)
    """, (series_id, source, date, value, now))
    conn.commit()
    conn.close()


# ─── Query functions (for Analyst agent context building) ───

def get_today_events(country: str = None):
    """Get all calendar events for today."""
    conn = get_connection()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    if country:
        rows = conn.execute("""
            SELECT * FROM calendar_events 
            WHERE datetime_utc LIKE ? AND country = ?
            ORDER BY datetime_utc ASC
        """, (f"{today}%", country)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM calendar_events 
            WHERE datetime_utc LIKE ?
            ORDER BY importance DESC, datetime_utc ASC
        """, (f"{today}%",)).fetchall()
    
    conn.close()
    return [dict(r) for r in rows]


def get_recent_surprises(days: int = 7, min_importance: str = "high"):
    """Get recent data surprises — key input for regime assessment."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM calendar_events 
        WHERE surprise IS NOT NULL 
          AND importance = ?
          AND datetime_utc >= datetime('now', ?)
        ORDER BY ABS(surprise) DESC
    """, (min_importance, f"-{days} days")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_market_snapshot():
    """Get most recent price for each tracked symbol."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT m1.* FROM market_prices m1
        INNER JOIN (
            SELECT symbol, MAX(id) as max_id FROM market_prices GROUP BY symbol
        ) m2 ON m1.id = m2.max_id
        ORDER BY m1.asset_class, m1.symbol
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_fed_comms(days: int = 14):
    """Get recent Fed communications."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM central_bank_comms 
        WHERE source = 'fed'
          AND scraped_at >= datetime('now', ?)
        ORDER BY published_at DESC
    """, (f"-{days} days",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_indicator_history(series_id: str, limit: int = 12):
    """Get recent history of an indicator (e.g., last 12 CPI readings)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM indicators 
        WHERE series_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (series_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_regime_state():
    """Get the most recent regime assessment."""
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM regime_state ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


def save_regime_state(regime: dict, trigger: str = "", notes: str = ""):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO regime_state (timestamp, regime_json, trigger_event, notes)
        VALUES (?, ?, ?, ?)
    """, (now, json.dumps(regime), trigger, notes))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database ready.")
