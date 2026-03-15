from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.cli import main
from analyst.contracts import ResearchNote, RegimeScore, RegimeState
from analyst.engine import LiveAnalystEngine
from analyst.engine.live_provider import OpenRouterConfig
from analyst.engine.live_types import CompletionResult, ConversationMessage, ToolCall
from analyst.env import clear_env_cache
from analyst.storage import (
    CentralBankCommunicationRecord,
    IndicatorObservationRecord,
    MarketPriceRecord,
    SQLiteEngineStore,
    StoredEventRecord,
)


class FakeProvider:
    def __init__(self, completions: list[CompletionResult]) -> None:
        self.completions = completions
        self.calls: list[list[ConversationMessage]] = []

    def complete(self, **kwargs):
        self.calls.append(list(kwargs["messages"]))
        if not self.completions:
            raise AssertionError("No more completions available.")
        return self.completions.pop(0)


class FakeIngestion:
    def refresh_all(self):
        return {"calendar": 2, "fed": 1}

    def run_schedule(self):
        raise AssertionError("schedule should not be called in this test")


def seed_store(store: SQLiteEngineStore) -> None:
    store.upsert_calendar_event(
        StoredEventRecord(
            source="investing",
            event_id="evt-cpi",
            timestamp=int(datetime(2026, 3, 7, 12, 30, tzinfo=timezone.utc).timestamp()),
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
    store.insert_market_price(
        MarketPriceRecord(
            symbol="^VIX",
            asset_class="equity",
            name="VIX",
            price=18.2,
            change_pct=-1.2,
            timestamp=int(datetime(2026, 3, 7, 12, 40, tzinfo=timezone.utc).timestamp()),
        )
    )
    store.insert_market_price(
        MarketPriceRecord(
            symbol="^TNX",
            asset_class="bond",
            name="10Y Treasury Yield",
            price=4.35,
            change_pct=0.14,
            timestamp=int(datetime(2026, 3, 7, 12, 40, tzinfo=timezone.utc).timestamp()),
        )
    )
    store.upsert_central_bank_comm(
        CentralBankCommunicationRecord(
            source="fed",
            title="Powell remarks",
            url="https://example.com/fed/powell",
            timestamp=int(datetime(2026, 3, 6, 20, 0, tzinfo=timezone.utc).timestamp()),
            content_type="speech",
            speaker="Powell",
            summary="Policy remains data dependent.",
            full_text="Policy remains data dependent.",
        )
    )
    store.upsert_indicator_observation(
        IndicatorObservationRecord(
            series_id="CPIAUCSL",
            source="fred",
            date="2026-03-01",
            value=318.2,
            metadata={"name": "CPI All Urban"},
        )
    )


class LiveEngineTest(unittest.TestCase):
    def test_store_recent_event_queries_filter_and_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing",
                    event_id="evt-cpi",
                    timestamp=int(datetime(2026, 3, 7, 12, 30, tzinfo=timezone.utc).timestamp()),
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
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing",
                    event_id="evt-cpi",
                    timestamp=int(datetime(2026, 3, 7, 12, 30, tzinfo=timezone.utc).timestamp()),
                    country="US",
                    indicator="CPI YoY",
                    category="inflation",
                    importance="high",
                    actual="3.5%",
                    forecast="3.2%",
                    previous="3.1%",
                    surprise=0.3,
                    raw_json={"headline": "US CPI reloaded"},
                )
            )
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="forexfactory",
                    event_id="evt-gdp",
                    timestamp=int(datetime(2026, 3, 8, 12, 30, tzinfo=timezone.utc).timestamp()),
                    country="US",
                    indicator="GDP QoQ",
                    category="growth",
                    importance="medium",
                    forecast="2.0%",
                    previous="2.2%",
                    raw_json={"headline": "GDP pending"},
                )
            )

            released = store.list_recent_events(limit=10, days=30, released_only=True, importance="high")
            latest_cpi = store.latest_released_event(indicator_keyword="cpi")

            self.assertEqual(len(released), 1)
            self.assertEqual(released[0].event_id, "evt-cpi")
            self.assertEqual(released[0].actual, "3.5%")
            self.assertIsNotNone(latest_cpi)
            self.assertEqual(latest_cpi.event_id, "evt-cpi")

    def test_refresh_all_sources_without_remote_service_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            engine = LiveAnalystEngine(store=store, provider=None)
            result = engine.refresh_all_sources()
            self.assertEqual(result, {})

    def test_generate_flash_commentary_requires_released_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            engine = LiveAnalystEngine(store=store, provider=None)
            with self.assertRaisesRegex(RuntimeError, "No released calendar event available"):
                engine.generate_flash_commentary()

    def test_generate_flash_commentary_executes_tool_loop_and_persists_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            seed_store(store)
            provider = FakeProvider(
                [
                    CompletionResult(
                        message=ConversationMessage(
                            role="assistant",
                            content=None,
                            tool_calls=[
                                ToolCall(
                                    call_id="call-1",
                                    name="get_recent_releases",
                                    arguments={"days": 7, "limit": 3},
                                )
                            ],
                        ),
                        raw_response={},
                    ),
                    CompletionResult(
                        message=ConversationMessage(
                            role="assistant",
                            content=(
                                "### 一句话总结\n"
                                "美国CPI再次高于预期，市场继续交易更久维持高利率。\n\n"
                                "### 核心数据\n"
                                "- CPI同比 3.4%，高于预期 3.2%。\n\n"
                                "```json\n"
                                "{\n"
                                '  "risk_appetite": 0.42,\n'
                                '  "fed_hawkishness": 0.74,\n'
                                '  "growth_momentum": 0.51,\n'
                                '  "inflation_trend": "accelerating",\n'
                                '  "liquidity_conditions": "tightening",\n'
                                '  "dominant_narrative": "通胀黏性压制降息预期。",\n'
                                '  "narrative_risk": "若就业同时转弱，市场会改写滞胀交易。",\n'
                                '  "regime_label": "risk_off",\n'
                                '  "confidence": 0.8,\n'
                                '  "cross_asset_implications": {\n'
                                '    "rates": "美债利率易上难下。",\n'
                                '    "dollar": "美元维持偏强。",\n'
                                '    "a_shares": "A股更看国内政策托底。",\n'
                                '    "hk_stocks": "港股科技对美债上行更敏感。",\n'
                                '    "us_equities": "估值股承压。",\n'
                                '    "commodities": "黄金受实际利率牵制。",\n'
                                '    "crypto": "风险资产弹性受限。"\n'
                                "  },\n"
                                '  "last_updated": "2026-03-07T12:45:00Z",\n'
                                '  "trigger": "CPI YoY"\n'
                                "}\n"
                                "```"
                            ),
                            tool_calls=[],
                        ),
                        raw_response={},
                    ),
                ]
            )
            engine = LiveAnalystEngine(store=store, provider=provider)

            note = engine.generate_flash_commentary()

            self.assertIsInstance(note, ResearchNote)
            self.assertEqual(note.note_type, "flash_commentary")
            self.assertIn("数据快评", note.title)
            self.assertIn("一句话总结", note.body_markdown)
            self.assertIsNotNone(note.regime_state)
            self.assertEqual(len(provider.calls), 2)

            connection = sqlite3.connect(str(store.db_path))
            notes_count = connection.execute("SELECT COUNT(*) FROM generated_notes").fetchone()[0]
            regime_count = connection.execute("SELECT COUNT(*) FROM regime_snapshots").fetchone()[0]
            research_artifact_count = connection.execute("SELECT COUNT(*) FROM research_artifacts").fetchone()[0]
            observation_count = connection.execute("SELECT COUNT(*) FROM analytical_observations").fetchone()[0]
            connection.close()
            self.assertEqual(notes_count, 1)
            self.assertEqual(regime_count, 1)
            self.assertEqual(research_artifact_count, 1)
            self.assertEqual(observation_count, 1)

    def test_openrouter_config_reads_project_env_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "LLM_API_KEY=test-llm-key",
                        "LLM_BASE_URL=https://openrouter.example/api/v1",
                        "LLM_MODEL=anthropic/test-model",
                    ]
                ),
                encoding="utf-8",
            )
            with patch("analyst.env.DEFAULT_ENV_FILES", (env_file,)):
                with patch.dict("os.environ", {}, clear=True):
                    clear_env_cache()
                    config = OpenRouterConfig.from_env()
            self.assertEqual(config.api_key, "test-llm-key")
            self.assertEqual(config.base_url, "https://openrouter.example/api/v1")
            self.assertEqual(config.model, "anthropic/test-model")

    def test_default_env_files_only_include_project_env(self) -> None:
        from analyst.env import DEFAULT_ENV_FILES, PROJECT_ROOT

        self.assertEqual(DEFAULT_ENV_FILES, (PROJECT_ROOT / ".env",))

    def test_extract_regime_payload_skips_invalid_json_and_merges_nested_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            engine = LiveAnalystEngine(store=store, provider=None)
            fallback = engine._baseline_regime()

            payload = engine._extract_regime_payload(
                markdown=(
                    "```json\n"
                    "{\n"
                    '  "risk_appetite": 1.2,\n'
                    '  "confidence": -0.5,\n'
                    '  "dominant_narrative": "通胀交易延续。",\n'
                    '  "cross_asset_implications": {"rates": "长端利率上行。"}\n'
                    "}\n"
                    "```\n"
                    "```json\n"
                    "{ invalid json }\n"
                    "```"
                ),
                fallback=fallback,
                trigger_event=None,
            )

            self.assertEqual(payload["dominant_narrative"], "通胀交易延续。")
            self.assertEqual(payload["cross_asset_implications"]["rates"], "长端利率上行。")
            self.assertEqual(
                payload["cross_asset_implications"]["dollar"],
                fallback["cross_asset_implications"]["dollar"],
            )
            self.assertEqual(payload["risk_appetite"], 1.0)
            self.assertEqual(payload["confidence"], 0.0)


class CalendarEnhancementsTest(unittest.TestCase):
    def test_list_recent_events_country_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-us", timestamp=int(datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="CPI", category="inflation", importance="high",
                    actual="3.0%", raw_json={},
                )
            )
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-jp", timestamp=int(datetime(2026, 3, 7, 6, 0, tzinfo=timezone.utc).timestamp()),
                    country="JP", indicator="GDP", category="growth", importance="medium",
                    actual="1.5%", raw_json={},
                )
            )
            us_events = store.list_recent_events(limit=10, days=30, country="US")
            jp_events = store.list_recent_events(limit=10, days=30, country="JP")
            self.assertEqual(len(us_events), 1)
            self.assertEqual(us_events[0].country, "US")
            self.assertEqual(len(jp_events), 1)
            self.assertEqual(jp_events[0].country, "JP")

    def test_list_recent_events_category_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-infl", timestamp=int(datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="CPI", category="inflation", importance="high",
                    actual="3.0%", raw_json={},
                )
            )
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-grow", timestamp=int(datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="GDP", category="growth", importance="medium",
                    actual="2.0%", raw_json={},
                )
            )
            inflation = store.list_recent_events(limit=10, days=30, category="inflation")
            growth = store.list_recent_events(limit=10, days=30, category="growth")
            self.assertEqual(len(inflation), 1)
            self.assertEqual(inflation[0].category, "inflation")
            self.assertEqual(len(growth), 1)
            self.assertEqual(growth[0].category, "growth")

    def test_list_events_in_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-d5", timestamp=int(datetime(2026, 3, 5, 10, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="ADP", category="employment", importance="medium",
                    actual="150K", raw_json={},
                )
            )
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-d7", timestamp=int(datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="NFP", category="employment", importance="high",
                    actual="200K", raw_json={},
                )
            )
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-d9", timestamp=int(datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="CPI", category="inflation", importance="high",
                    actual="3.0%", raw_json={},
                )
            )
            events = store.list_events_in_range(
                date_from=int(datetime(2026, 3, 6, 0, 0, 0, tzinfo=timezone.utc).timestamp()),
                date_to=int(datetime(2026, 3, 8, 23, 59, 59, tzinfo=timezone.utc).timestamp()),
            )
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_id, "evt-d7")

    def test_list_today_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            now = datetime.now(timezone.utc)
            today_epoch = int(now.replace(hour=12, minute=0, second=0, microsecond=0).timestamp())
            yesterday_epoch = int((now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).timestamp())
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-today", timestamp=today_epoch,
                    country="US", indicator="CPI", category="inflation", importance="high",
                    raw_json={},
                )
            )
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-yesterday", timestamp=yesterday_epoch,
                    country="US", indicator="GDP", category="growth", importance="medium",
                    raw_json={},
                )
            )
            events = store.list_today_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_id, "evt-today")

    def test_list_indicator_releases_trend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            for i, actual in enumerate(["3.0%", "3.1%", "3.2%"]):
                store.upsert_calendar_event(
                    StoredEventRecord(
                        source="investing", event_id=f"evt-cpi-{i}",
                        timestamp=int(datetime(2026, i + 1, 7, 12, 30, tzinfo=timezone.utc).timestamp()),
                        country="US", indicator="CPI YoY", category="inflation", importance="high",
                        actual=actual, forecast="3.0%", previous="2.9%",
                        surprise=round(float(actual.replace("%", "")) - 3.0, 4),
                        raw_json={},
                    )
                )
            releases = store.list_indicator_releases(indicator_keyword="CPI")
            self.assertEqual(len(releases), 3)
            self.assertEqual(releases[0].actual, "3.2%")  # most recent first

    def test_currency_field_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            store.upsert_calendar_event(
                StoredEventRecord(
                    source="investing", event_id="evt-cur", timestamp=int(datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc).timestamp()),
                    country="US", indicator="CPI", category="inflation", importance="high",
                    actual="3.0%", currency="USD", raw_json={},
                )
            )
            events = store.list_recent_events(limit=1, days=30)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].currency, "USD")

    def test_tool_indicator_trend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEngineStore(Path(temp_dir) / "engine.db")
            for i in range(3):
                store.upsert_calendar_event(
                    StoredEventRecord(
                        source="investing", event_id=f"evt-nfp-{i}",
                        timestamp=int(datetime(2026, i + 1, 7, 12, 30, tzinfo=timezone.utc).timestamp()),
                        country="US", indicator="Nonfarm Payrolls", category="employment", importance="high",
                        actual=f"{200+i*10}K", forecast="200K", previous="190K",
                        surprise=float(i * 10), raw_json={},
                    )
                )
            engine = LiveAnalystEngine(store=store, provider=None)
            result = engine._tool_indicator_trend({"indicator_keyword": "Nonfarm"})
            self.assertEqual(len(result["releases"]), 3)
            self.assertEqual(result["indicator_keyword"], "Nonfarm")

    def test_live_calendar_cli_today(self) -> None:
        fake_app = Mock()
        fake_app.live_calendar.return_value = [
            StoredEventRecord(
                source="investing", event_id="evt-cli", timestamp=int(datetime(2026, 3, 7, 12, 30, tzinfo=timezone.utc).timestamp()),
                country="US", indicator="CPI YoY", category="inflation", importance="high",
                actual="3.4%", forecast="3.2%", previous="3.1%", raw_json={},
            )
        ]
        output = io.StringIO()
        with patch("analyst.cli.build_live_engine_app", return_value=fake_app):
            with redirect_stdout(output):
                rc = main(["live-calendar", "--scope", "today"])
        self.assertEqual(rc, 0)
        self.assertIn("INVESTING", output.getvalue())
        self.assertIn("CPI YoY", output.getvalue())
        self.assertIn("3.4%", output.getvalue())


class CLIWSTest(unittest.TestCase):
    def test_refresh_command_requires_once_flag(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["refresh"])
        self.assertEqual(raised.exception.code, 2)

    def test_refresh_command_routes_to_live_app(self) -> None:
        fake_app = Mock()
        fake_app.refresh.return_value = {"calendar": 3}
        output = io.StringIO()
        with patch("analyst.cli.build_live_engine_app", return_value=fake_app):
            with redirect_stdout(output):
                rc = main(["refresh", "--once"])
        self.assertEqual(rc, 0)
        self.assertIn("calendar", output.getvalue())

    def test_flash_command_prints_body_markdown(self) -> None:
        fake_app = Mock()
        fake_app.flash.return_value = ResearchNote(
            note_id="note-1",
            created_at=datetime.now(timezone.utc),
            note_type="flash_commentary",
            title="数据快评",
            summary="summary",
            body_markdown="### flash body",
        )
        output = io.StringIO()
        with patch("analyst.cli.build_live_engine_app", return_value=fake_app):
            with redirect_stdout(output):
                rc = main(["flash", "--indicator", "cpi"])
        self.assertEqual(rc, 0)
        self.assertIn("flash body", output.getvalue())

    def test_regime_refresh_command_formats_scores(self) -> None:
        fake_app = Mock()
        fake_app.regime_refresh.return_value = RegimeState(
            as_of=datetime.now(timezone.utc),
            summary="current regime",
            scores=[RegimeScore(axis="risk", score=55.0, label="neutral", rationale="")],
            evidence=[],
            confidence=0.7,
        )
        output = io.StringIO()
        with patch("analyst.cli.build_live_engine_app", return_value=fake_app):
            with redirect_stdout(output):
                rc = main(["regime-refresh"])
        self.assertEqual(rc, 0)
        rendered = output.getvalue()
        self.assertIn("current regime", rendered)
        self.assertIn("neutral", rendered)


if __name__ == "__main__":
    unittest.main()
