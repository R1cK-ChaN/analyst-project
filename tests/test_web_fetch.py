"""Tests for the web_fetch_page tool via LocalMacroDataService."""

from __future__ import annotations

from unittest.mock import MagicMock

from analyst.macro_data.service import LocalMacroDataService
from analyst.tools._web_fetch import FetchPageConfig, build_web_fetch_tool


# ---------------------------------------------------------------------------
# LocalMacroDataService._op_web_fetch_page
# ---------------------------------------------------------------------------

class TestWebFetchPageOperation:
    def _make_service(self):
        return LocalMacroDataService(store=MagicMock())

    def test_missing_url_returns_error(self):
        svc = self._make_service()
        result = svc.invoke("web_fetch_page", {})
        assert "error" in result

    def test_empty_url_returns_error(self):
        svc = self._make_service()
        result = svc.invoke("web_fetch_page", {"url": "  "})
        assert "error" in result

    def test_web_fetch_page_is_remote_only(self):
        svc = self._make_service()
        result = svc.invoke("web_fetch_page", {"url": "https://example.com"})
        assert "error" in result
        assert "macro-data-service" in result["error"]


# ---------------------------------------------------------------------------
# build_web_fetch_tool factory
# ---------------------------------------------------------------------------

class TestBuildWebFetchTool:
    def test_returns_agent_tool_with_correct_schema(self):
        tool = build_web_fetch_tool()
        assert tool.name == "web_fetch_page"
        assert "url" in tool.parameters["required"]
        assert "url" in tool.parameters["properties"]
        assert "web page" in tool.description.lower()

    def test_custom_config_is_respected(self):
        config = FetchPageConfig(timeout=10, max_content_chars=5_000, max_return_chars=2_000)
        tool = build_web_fetch_tool(config)
        assert tool.handler is not None
        assert callable(tool.handler)

    def test_default_config(self):
        tool = build_web_fetch_tool()
        assert tool.handler is not None
        assert callable(tool.handler)
