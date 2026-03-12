from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.app import build_live_engine_app
from analyst.env import clear_env_cache
from analyst.macro_data.client import HttpMacroDataClient
from analyst.storage import NewsArticleRecord, SQLiteEngineStore, StoredEventRecord


SERVICE_ROOT = PROJECT_ROOT.parent / "macro-data-service"
SERVICE_SRC = SERVICE_ROOT / "src"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _macro_data_server(*, db_path: Path, api_token: str):
    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SERVICE_SRC)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "analyst.macro_data.server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--db-path",
            str(db_path),
            "--api-token",
            api_token,
        ],
        cwd=str(SERVICE_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                response = httpx.get(f"{base_url}/health", timeout=0.2)
                if response.status_code == 200:
                    yield base_url
                    return
            except Exception:
                pass
            time.sleep(0.1)
        stdout, stderr = process.communicate(timeout=1)
        raise AssertionError(f"macro-data service failed to start\nstdout:\n{stdout}\nstderr:\n{stderr}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class MacroDataHttpIntegrationTest(unittest.TestCase):
    def test_agent_uses_extracted_macro_data_service_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "engine.db"
            store = SQLiteEngineStore(db_path)
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing",
                    event_id="evt-http-cpi",
                    timestamp=int(datetime(2026, 3, 11, 12, 30, tzinfo=timezone.utc).timestamp()),
                    country="US",
                    indicator="CPI YoY",
                    category="inflation",
                    importance="high",
                    actual="3.4%",
                    forecast="3.2%",
                    previous="3.1%",
                    surprise=0.2,
                    raw_json={"headline": "US CPI beats"},
                )
            )
            url = "https://example.com/us-inflation"
            store.upsert_news_article(
                NewsArticleRecord(
                    url_hash=hashlib.sha256(url.encode("utf-8")).hexdigest(),
                    source_feed="reuters",
                    feed_category="markets",
                    title="US inflation surprises to the upside",
                    url=url,
                    timestamp=int(datetime(2026, 3, 11, 13, 0, tzinfo=timezone.utc).timestamp()),
                    description="Inflation and CPI both moved above consensus.",
                    content_markdown="Inflation details",
                    impact_level="high",
                    finance_category="inflation",
                    confidence=0.9,
                    content_fetched=True,
                    country="US",
                    asset_class="fixed_income",
                    subject="inflation",
                )
            )

            with _macro_data_server(db_path=db_path, api_token="secret-token") as base_url:
                with patch.dict(
                    os.environ,
                    {
                        "ANALYST_MACRO_DATA_BASE_URL": base_url,
                        "ANALYST_MACRO_DATA_API_TOKEN": "secret-token",
                    },
                    clear=False,
                ):
                    clear_env_cache()
                    app = build_live_engine_app(db_path=db_path)
                    self.assertIsInstance(app.engine.data_client, HttpMacroDataClient)

                    recent = app.engine._tool_recent_releases({"limit": 5, "days": 30})["events"]
                    news = app.engine._tool_search_news({"query": "inflation", "limit": 5})["articles"]

                clear_env_cache()

            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["event_id"], "evt-http-cpi")
            self.assertEqual(recent[0]["actual"], "3.4%")

            self.assertEqual(len(news), 1)
            self.assertEqual(news[0]["title"], "US inflation surprises to the upside")
            self.assertEqual(news[0]["country"], "US")


if __name__ == "__main__":
    unittest.main()
