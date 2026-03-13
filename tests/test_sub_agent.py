from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.agents import RolePromptContext
from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.live_types import AgentTool, CompletionResult, ConversationMessage, ToolCall
from analyst.agents.companion.spec_builder import build_research_delegation_spec, render_research_delegation_prompt
from analyst.agents.research.research_agent import build_research_agent_tool, build_research_role_spec
from analyst.engine.sub_agent import SubAgentSpec, SubAgentHandler, build_sub_agent_tool, _extract_scope_tags
from analyst.engine.sub_agent_specs import (
    build_research_sub_agents,
    build_sales_sub_agents,
    build_content_sub_agents,
)
from analyst.memory.render import RenderBudget, sub_agent_budget
from analyst.storage import SQLiteEngineStore


# ---- helpers ----

class FakeProvider:
    """Minimal LLM provider that returns pre-configured completions."""

    def __init__(self, completions: list[CompletionResult]) -> None:
        self.completions = list(completions)
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if not self.completions:
            raise AssertionError("No more completions available.")
        return self.completions.pop(0)


def _dummy_tool(name: str = "dummy_tool") -> AgentTool:
    return AgentTool(
        name=name,
        description=f"Dummy tool {name}",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
    )


def _make_completion(content: str, tool_calls: list[ToolCall] | None = None) -> CompletionResult:
    return CompletionResult(
        message=ConversationMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls or [],
        ),
        raw_response={},
    )


def _temp_store() -> SQLiteEngineStore:
    tmp = tempfile.mkdtemp()
    return SQLiteEngineStore(db_path=Path(tmp) / "test.db")


# ---- tests: SubAgentSpec & SubAgentHandler ----

def test_sub_agent_spec_defaults():
    spec = SubAgentSpec(
        name="test_agent",
        description="A test sub-agent",
        system_prompt="You are a test agent.",
        tools=[_dummy_tool()],
    )
    assert spec.config.max_turns == 3
    assert spec.config.max_tokens == 1200
    assert "task" in spec.parameters["properties"]
    assert "task" in spec.parameters["required"]


def test_sub_agent_handler_success():
    """SubAgentHandler should run a loop and return structured result."""
    completion = _make_completion("Analysis complete: CPI rose 3.4% YoY.")
    provider = FakeProvider([completion])
    spec = SubAgentSpec(
        name="test_agent",
        description="test",
        system_prompt="You are a test agent.",
        tools=[_dummy_tool()],
    )
    handler = SubAgentHandler(spec, provider)
    result = handler({"task": "Analyze CPI data"})

    assert result["status"] == "ok"
    assert "CPI" in result["result"]
    assert result["turns_used"] == 1
    assert len(provider.calls) == 1
    assert provider.calls[0]["system_prompt"] == "You are a test agent."


def test_sub_agent_handler_missing_task():
    provider = FakeProvider([])
    spec = SubAgentSpec(
        name="test_agent",
        description="test",
        system_prompt="test",
        tools=[],
    )
    handler = SubAgentHandler(spec, provider)
    result = handler({})
    assert result["status"] == "error"
    assert "task" in result["error"].lower()


def test_sub_agent_handler_with_context():
    """Context argument should be appended to user prompt."""
    completion = _make_completion("Done.")
    provider = FakeProvider([completion])
    spec = SubAgentSpec(
        name="test_agent",
        description="test",
        system_prompt="test",
        tools=[_dummy_tool()],
    )
    handler = SubAgentHandler(spec, provider)
    handler({"task": "Check rates", "context": "Focus on 10Y treasury"})

    # messages[0] is the user message constructed by the sub-agent handler
    user_prompt = provider.calls[0]["messages"][0].content
    assert "Focus on 10Y treasury" in user_prompt


def test_sub_agent_handler_max_turns_error():
    """When max_turns is reached, handler should return error status."""
    # Create a completion that always calls a tool (never finishes)
    tool = _dummy_tool("always_call")
    tool_call_completion = _make_completion(
        None,
        tool_calls=[ToolCall(call_id="tc1", name="always_call", arguments={})],
    )
    # Provide exactly max_turns completions, all with tool calls
    provider = FakeProvider([tool_call_completion, tool_call_completion, tool_call_completion])
    spec = SubAgentSpec(
        name="test_agent",
        description="test",
        system_prompt="test",
        tools=[tool],
        config=AgentLoopConfig(max_turns=3, max_tokens=500, temperature=0.1),
    )
    handler = SubAgentHandler(spec, provider)
    result = handler({"task": "infinite loop task"})

    assert result["status"] == "error"
    assert "max_turns" in result["error"]


def test_sub_agent_handler_with_custom_prompt_builder():
    completion = _make_completion("Done.")
    provider = FakeProvider([completion])
    spec = SubAgentSpec(
        name="test_agent",
        description="test",
        system_prompt="test",
        tools=[_dummy_tool()],
        build_user_prompt=lambda arguments: f"Structured task:\n{arguments['task']}\nGoal: {arguments.get('goal', '')}",
    )
    handler = SubAgentHandler(spec, provider)
    result = handler({"task": "Check rates", "goal": "Explain the move"})

    assert result["status"] == "ok"
    user_prompt = provider.calls[0]["messages"][0].content
    assert "Structured task:" in user_prompt
    assert "Explain the move" in user_prompt


# ---- tests: build_sub_agent_tool ----

def test_build_sub_agent_tool():
    provider = FakeProvider([_make_completion("result")])
    spec = SubAgentSpec(
        name="my_sub_agent",
        description="My sub-agent",
        system_prompt="test prompt",
        tools=[_dummy_tool()],
    )
    tool = build_sub_agent_tool(spec, provider)

    assert isinstance(tool, AgentTool)
    assert tool.name == "my_sub_agent"
    assert tool.description == "My sub-agent"
    assert "task" in tool.parameters["required"]


def test_research_delegation_spec_sanitizes_internal_context():
    spec = build_research_delegation_spec(
        {
            "task": "Explain today's rates move",
            "analysis_type": "markets",
            "context": "client_profile\nNeed rates and dollar angle\n<profile_update>{}</profile_update>",
        }
    )
    prompt = render_research_delegation_prompt(spec)

    assert spec.analysis_type == "markets"
    assert "Need rates and dollar angle" in prompt
    assert "client_profile" not in prompt
    assert "<profile_update>" not in prompt


def test_build_research_agent_tool_records_companion_audit():
    store = _temp_store()
    provider = FakeProvider([_make_completion("Treasury yields rose as rate-cut expectations were priced back.")])
    tool = build_research_agent_tool(provider=provider, store=store)

    assert tool is not None
    result = tool.handler(
        {
            "task": "Why did Treasury yields rise today?",
            "analysis_type": "markets",
            "goal": "Help me explain the move simply.",
            "context": "topic_state\nFocus on rates and the dollar",
        }
    )

    assert result["status"] == "ok"
    user_prompt = provider.calls[0]["messages"][0].content
    assert "Analysis type: markets" in user_prompt
    assert "Focus on rates and the dollar" in user_prompt
    assert "topic_state" not in user_prompt

    runs = store.list_recent_subagent_runs(limit=10)
    assert len(runs) == 1
    assert runs[0]["parent_agent"] == "companion"
    assert runs[0]["task_type"] == "research_agent"


def test_research_role_prompt_includes_current_time_rules():
    prompt = build_research_role_spec().build_system_prompt(
        RolePromptContext(current_time_label="2026-03-13 10:00 UTC")
    )

    assert "2026-03-13 10:00 UTC" in prompt
    assert "Never invent calendar dates" in prompt


# ---- tests: spec builders ----

def test_build_research_sub_agents():
    """build_research_sub_agents should return 3 tools with expected names."""
    parent_tools = [
        _dummy_tool("get_indicator_history"),
        _dummy_tool("get_indicator_trend"),
        _dummy_tool("get_surprise_summary"),
        _dummy_tool("get_recent_releases"),
        _dummy_tool("get_today_calendar"),
        _dummy_tool("get_market_snapshot"),
        _dummy_tool("get_vix_regime"),
        _dummy_tool("fetch_reference_rates"),
        _dummy_tool("fetch_rate_expectations"),
        _dummy_tool("fetch_live_markets"),
        _dummy_tool("fetch_live_news"),
        _dummy_tool("web_search"),
        _dummy_tool("web_fetch_page"),
        _dummy_tool("fetch_article"),
        _dummy_tool("search_news"),
        _dummy_tool("get_recent_news"),
    ]
    provider = FakeProvider([])
    tools = build_research_sub_agents(parent_tools, provider)

    assert len(tools) == 3
    names = {t.name for t in tools}
    assert names == {"data_deep_dive", "market_scanner", "news_researcher"}
    for tool in tools:
        assert isinstance(tool, AgentTool)
        assert "task" in tool.parameters["required"]


def test_build_sales_sub_agents():
    """build_sales_sub_agents should return 2 tools with expected names."""
    parent_tools = [
        _dummy_tool("fetch_live_markets"),
        _dummy_tool("fetch_live_news"),
        _dummy_tool("fetch_article"),
        _dummy_tool("fetch_country_indicators"),
        _dummy_tool("fetch_reference_rates"),
        _dummy_tool("get_regime_summary"),
        _dummy_tool("get_calendar"),
        _dummy_tool("web_search"),
        _dummy_tool("get_portfolio_risk"),
        _dummy_tool("get_portfolio_holdings"),
        _dummy_tool("get_vix_regime"),
        _dummy_tool("sync_portfolio_from_broker"),
    ]
    provider = FakeProvider([])
    tools = build_sales_sub_agents(parent_tools, provider)

    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"research_lookup", "portfolio_analyst"}


def test_build_content_sub_agents():
    """build_content_sub_agents should return 2 tools."""
    provider = FakeProvider([])
    tools = build_content_sub_agents(provider)

    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"fact_checker", "content_researcher"}


# ---- tests: sub_agent_budget ----

def test_sub_agent_budget_is_smaller():
    default = RenderBudget()
    sa = sub_agent_budget()

    assert sa.total_chars < default.total_chars
    assert sa.max_item_chars < default.max_item_chars
    assert sa.max_recent_messages == 0
    assert sa.max_delivery_items == 0
    assert sa.max_research_items <= default.max_research_items


# ---- tests: memory / subagent ----

def test_build_subagent_memory_empty():
    """build_subagent_memory with an empty store should return empty string."""
    store = _temp_store()
    from analyst.memory.subagent import build_subagent_memory
    result = build_subagent_memory(store, scope_tags=[], parent_agent="test")
    assert result == ""


def test_build_subagent_memory_with_data():
    """build_subagent_memory with regime data should return non-empty string."""
    store = _temp_store()
    store.save_regime_snapshot(
        regime_json={"risk_appetite": 0.6, "dominant_narrative": "CPI drove risk-on"},
        trigger_event="CPI",
        summary="CPI surprise drove risk appetite higher",
    )
    from analyst.memory.subagent import build_subagent_memory
    result = build_subagent_memory(store, scope_tags=["cpi"], parent_agent="data_deep_dive")
    assert "CPI" in result or "cpi" in result.lower()
    assert len(result) <= 2500


# ---- tests: storage ----

def test_save_and_list_subagent_runs():
    store = _temp_store()
    store.save_subagent_run(
        task_id="abc123",
        parent_agent="research",
        task_type="data_deep_dive",
        objective="Analyze US CPI",
        scope_tags=["cpi", "inflation"],
        status="ok",
        summary="CPI rose 3.4% YoY",
        elapsed_seconds=2.5,
    )
    store.save_subagent_run(
        task_id="def456",
        parent_agent="sales",
        task_type="research_lookup",
        objective="Check rates",
        scope_tags=["rates"],
        status="ok",
        summary="10Y at 4.5%",
        elapsed_seconds=1.2,
    )

    all_runs = store.list_recent_subagent_runs(limit=10)
    assert len(all_runs) == 2

    research_runs = store.list_recent_subagent_runs(parent_agent="research", limit=10)
    assert len(research_runs) == 1
    assert research_runs[0]["task_id"] == "abc123"
    assert research_runs[0]["scope_tags"] == ["cpi", "inflation"]


def test_list_tagged_observations():
    store = _temp_store()
    store.add_analytical_observation(
        observation_type="published_output",
        summary="CPI inflation accelerating in Q1",
        detail="test",
        source_kind="test",
        source_id=1,
        metadata={},
    )
    store.add_analytical_observation(
        observation_type="published_output",
        summary="NFP employment strong",
        detail="test",
        source_kind="test",
        source_id=2,
        metadata={},
    )

    tagged = store.list_tagged_observations(tags=["cpi"], limit=10)
    assert len(tagged) == 1
    assert "CPI" in tagged[0].summary

    all_obs = store.list_tagged_observations(tags=[], limit=10)
    assert len(all_obs) == 2


def test_list_tagged_observations_matches_punctuation_boundaries():
    store = _temp_store()
    store.add_analytical_observation(
        observation_type="published_output",
        summary="US, CPI beat expectations",
        detail="test",
        source_kind="test",
        source_id=1,
        metadata={},
    )
    store.add_analytical_observation(
        observation_type="published_output",
        summary="Fed: CPI still sticky",
        detail="test",
        source_kind="test",
        source_id=2,
        metadata={},
    )
    store.add_analytical_observation(
        observation_type="published_output",
        summary="Risk-off after payrolls",
        detail="test",
        source_kind="test",
        source_id=3,
        metadata={},
    )

    assert [o.summary for o in store.list_tagged_observations(tags=["us"], limit=10)] == [
        "US, CPI beat expectations",
    ]
    assert [o.summary for o in store.list_tagged_observations(tags=["fed"], limit=10)] == [
        "Fed: CPI still sticky",
    ]
    assert [o.summary for o in store.list_tagged_observations(tags=["risk"], limit=10)] == [
        "Risk-off after payrolls",
    ]


def test_list_tagged_regime_snapshots():
    store = _temp_store()
    store.save_regime_snapshot(
        regime_json={"risk_appetite": 0.6},
        trigger_event="CPI",
        summary="CPI beat drove risk higher",
    )
    store.save_regime_snapshot(
        regime_json={"risk_appetite": 0.4},
        trigger_event="NFP",
        summary="NFP miss drove risk lower",
    )

    cpi_snaps = store.list_tagged_regime_snapshots(tags=["cpi"], limit=10)
    assert len(cpi_snaps) == 1
    assert "CPI" in cpi_snaps[0].summary


def test_list_tagged_regime_snapshots_matches_punctuation_boundaries():
    store = _temp_store()
    store.save_regime_snapshot(
        regime_json={"risk_appetite": 0.6},
        trigger_event="CPI",
        summary="US, CPI beat drove risk-on",
    )
    store.save_regime_snapshot(
        regime_json={"risk_appetite": 0.4},
        trigger_event="FOMC",
        summary="Fed: markets repriced higher-for-longer",
    )

    assert [s.summary for s in store.list_tagged_regime_snapshots(tags=["us"], limit=10)] == [
        "US, CPI beat drove risk-on",
    ]
    assert [s.summary for s in store.list_tagged_regime_snapshots(tags=["fed"], limit=10)] == [
        "Fed: markets repriced higher-for-longer",
    ]


# ---- tests: integration ----

def test_sub_agent_in_parent_loop():
    """Integration: parent loop calls a sub-agent tool, then produces final text."""
    # Sub-agent provider: will return a direct answer
    sub_completion = _make_completion("CPI analysis: rose 3.4%, beating expectations by 0.2pp.")

    # Parent provider: first call returns a tool call to the sub-agent,
    # second call returns final text incorporating sub-agent result
    parent_tool_call = _make_completion(
        None,
        tool_calls=[ToolCall(
            call_id="tc-sub-1",
            name="data_deep_dive",
            arguments={"task": "Analyze latest CPI release"},
        )],
    )
    parent_final = _make_completion(
        "Based on the deep dive, CPI rose 3.4% YoY, beating consensus. "
        "This reinforces the higher-for-longer rate narrative."
    )

    # Build the sub-agent tool with its own provider
    sub_provider = FakeProvider([sub_completion])
    spec = SubAgentSpec(
        name="data_deep_dive",
        description="Deep dive analysis",
        system_prompt="You are an analyst.",
        tools=[_dummy_tool("get_indicator_history")],
    )
    sa_tool = build_sub_agent_tool(spec, sub_provider)

    # Run parent loop
    from analyst.engine.agent_loop import PythonAgentLoop

    parent_provider = FakeProvider([parent_tool_call, parent_final])
    loop = PythonAgentLoop(parent_provider, AgentLoopConfig(max_turns=3))
    result = loop.run(
        system_prompt="You are the main analyst.",
        user_prompt="What's the latest on CPI?",
        tools=[sa_tool],
    )

    assert "CPI" in result.final_text
    assert "3.4%" in result.final_text
    # Verify sub-agent was called
    assert len(sub_provider.calls) == 1


def test_scope_tags_extraction():
    tags = _extract_scope_tags("Analyze the latest US CPI inflation data")
    assert "cpi" in tags
    assert "inflation" in tags
    assert "us" in tags


def test_scope_tags_no_false_positives():
    """Substring matches inside words should not produce tags."""
    tags = _extract_scope_tags("Discuss business inflation outlook")
    assert "inflation" in tags
    assert "us" not in tags  # "bus" contains "us" but should not match

    tags2 = _extract_scope_tags("Reuters reported on European markets")
    assert "eu" not in tags2  # "Reuters"/"European" contain "eu" but should not match

    tags3 = _extract_scope_tags("Goldman Sachs analysis")
    assert "gold" not in tags3  # "Goldman" contains "gold" but should not match


# ---- tests: OpenRouterAgentRuntime with tools ----

def test_openrouter_runtime_with_tools():
    """OpenRouterAgentRuntime with tools should use PythonAgentLoop."""
    from analyst.runtime.openrouter import OpenRouterAgentRuntime, OpenRouterRuntimeConfig
    from analyst.contracts import InteractionMode, MarketSnapshot, RegimeState, RegimeScore
    from analyst.runtime.service import RuntimeContext
    from datetime import datetime, timezone

    completion = _make_completion("Here is the enriched content with verified data.")
    provider = FakeProvider([completion])

    runtime = OpenRouterAgentRuntime(
        provider=provider,
        config=OpenRouterRuntimeConfig(max_tokens=800, temperature=0.2),
        tools=[_dummy_tool("fact_checker")],
    )

    now = datetime.now(timezone.utc)
    context = RuntimeContext(
        mode=InteractionMode.QA,
        user_id="test",
        instruction="test instruction",
        memory_context="",
        focus="macro",
        audience="internal",
        market_snapshot=MarketSnapshot(
            as_of=now,
            focus="macro",
            headline_summary=["Test headline"],
            key_events=[],
            market_prices={},
        ),
        regime_state=RegimeState(
            as_of=now,
            summary="Test regime",
            scores=[
                RegimeScore(axis="risk_appetite", score=50.0, label="neutral", rationale="test"),
            ],
            evidence=[],
            confidence=0.6,
        ),
    )

    result = runtime.generate(context)
    assert "enriched content" in result.markdown
    assert len(provider.calls) == 1


def test_openrouter_runtime_without_tools():
    """OpenRouterAgentRuntime without tools should use single-shot completion (backward compat)."""
    from analyst.runtime.openrouter import OpenRouterAgentRuntime, OpenRouterRuntimeConfig
    from analyst.contracts import InteractionMode, MarketSnapshot, RegimeState, RegimeScore
    from analyst.runtime.service import RuntimeContext
    from datetime import datetime, timezone

    completion = _make_completion("Single shot response.")
    provider = FakeProvider([completion])

    runtime = OpenRouterAgentRuntime(
        provider=provider,
        config=OpenRouterRuntimeConfig(max_tokens=800),
    )

    now = datetime.now(timezone.utc)
    context = RuntimeContext(
        mode=InteractionMode.QA,
        user_id="test",
        instruction="test",
        memory_context="",
        focus="macro",
        audience="internal",
        market_snapshot=MarketSnapshot(
            as_of=now,
            focus="macro",
            headline_summary=[],
            key_events=[],
            market_prices={},
        ),
        regime_state=RegimeState(
            as_of=now,
            summary="Test",
            scores=[RegimeScore(axis="test", score=50.0, label="neutral", rationale="test")],
            evidence=[],
            confidence=0.5,
        ),
    )

    result = runtime.generate(context)
    assert "Single shot response" in result.markdown
    # Single-shot path: tools=[] should have been passed
    assert provider.calls[0]["tools"] == []


# ---- tests: tool-name mismatch regression guards ----

def _research_parent_tools() -> list[AgentTool]:
    """Build a tool list with the real tool names from the research agent."""
    return [
        _dummy_tool("get_indicator_history"),
        _dummy_tool("get_indicator_trend"),
        _dummy_tool("get_surprise_summary"),
        _dummy_tool("get_recent_releases"),
        _dummy_tool("get_today_calendar"),
        _dummy_tool("get_market_snapshot"),
        _dummy_tool("get_vix_regime"),
        _dummy_tool("fetch_reference_rates"),
        _dummy_tool("fetch_rate_expectations"),
        _dummy_tool("fetch_live_markets"),
        _dummy_tool("fetch_live_news"),
        _dummy_tool("web_search"),
        _dummy_tool("web_fetch_page"),
        _dummy_tool("fetch_article"),
        _dummy_tool("search_news"),
        _dummy_tool("get_recent_news"),
    ]


def _sales_parent_tools() -> list[AgentTool]:
    """Build a tool list with the real tool names from the sales agent."""
    return [
        _dummy_tool("fetch_live_markets"),
        _dummy_tool("fetch_live_news"),
        _dummy_tool("fetch_article"),
        _dummy_tool("fetch_country_indicators"),
        _dummy_tool("fetch_reference_rates"),
        _dummy_tool("get_regime_summary"),
        _dummy_tool("get_calendar"),
        _dummy_tool("web_search"),
        _dummy_tool("get_portfolio_risk"),
        _dummy_tool("get_portfolio_holdings"),
        _dummy_tool("get_vix_regime"),
        _dummy_tool("sync_portfolio_from_broker"),
    ]


def test_research_sub_agents_pick_correct_tools():
    """Each research sub-agent should get the expected number of tools."""
    provider = FakeProvider([])
    tools = build_research_sub_agents(_research_parent_tools(), provider)
    by_name = {t.name: t for t in tools}

    # market_scanner: get_market_snapshot, get_vix_regime, fetch_reference_rates,
    #                 fetch_rate_expectations, fetch_live_markets, fetch_live_news
    scanner_handler = by_name["market_scanner"].handler
    assert len(scanner_handler.spec.tools) == 6

    # news_researcher: web_search, web_fetch_page, fetch_live_news,
    #                  fetch_article, search_news, get_recent_news
    news_handler = by_name["news_researcher"].handler
    assert len(news_handler.spec.tools) == 6

    # data_deep_dive: get_indicator_history, get_indicator_trend,
    #                 get_surprise_summary, get_recent_releases, get_today_calendar
    data_handler = by_name["data_deep_dive"].handler
    assert len(data_handler.spec.tools) == 5


def test_sales_sub_agents_pick_correct_tools():
    """Sales research_lookup should get 8 tools including fetch_live_markets."""
    provider = FakeProvider([])
    tools = build_sales_sub_agents(_sales_parent_tools(), provider)
    by_name = {t.name: t for t in tools}

    lookup_handler = by_name["research_lookup"].handler
    assert len(lookup_handler.spec.tools) == 8
    inner_names = {t.name for t in lookup_handler.spec.tools}
    assert "fetch_live_markets" in inner_names
    assert "fetch_live_news" in inner_names
    assert "fetch_country_indicators" in inner_names
    assert "fetch_reference_rates" in inner_names

    portfolio_handler = by_name["portfolio_analyst"].handler
    assert len(portfolio_handler.spec.tools) == 4


def test_sub_agent_handler_catches_all_exceptions():
    """Inner tool raising ValueError should be caught, not propagated."""
    def bad_handler(args):
        raise ValueError("unexpected value error")

    bad_tool = AgentTool(
        name="bad_tool",
        description="A tool that always fails",
        parameters={"type": "object", "properties": {}},
        handler=bad_handler,
    )

    # Provider returns a tool call to the bad tool, then the handler should catch
    tool_call_completion = _make_completion(
        None,
        tool_calls=[ToolCall(call_id="tc1", name="bad_tool", arguments={})],
    )
    # After tool error, the loop will get another completion
    final_completion = _make_completion("Recovery after error.")
    provider = FakeProvider([tool_call_completion, final_completion])

    spec = SubAgentSpec(
        name="test_agent",
        description="test",
        system_prompt="test",
        tools=[bad_tool],
        config=AgentLoopConfig(max_turns=3, max_tokens=500, temperature=0.1),
    )
    handler = SubAgentHandler(spec, provider)
    result = handler({"task": "test task"})

    # Should NOT propagate — either returns ok (if loop recovers) or error (if loop fails)
    assert result["status"] in ("ok", "error")


def test_audit_records_correct_parent_agent():
    """Audit should record parent_agent from the handler, not the spec name."""
    store = _temp_store()
    completion = _make_completion("Analysis complete.")
    provider = FakeProvider([completion])
    spec = SubAgentSpec(
        name="data_deep_dive",
        description="test",
        system_prompt="test",
        tools=[_dummy_tool()],
    )
    handler = SubAgentHandler(spec, provider, store=store, parent_agent="research")
    result = handler({"task": "Analyze US CPI inflation data"})
    assert result["status"] == "ok"

    runs = store.list_recent_subagent_runs(limit=10)
    assert len(runs) == 1
    assert runs[0]["parent_agent"] == "research"
    assert runs[0]["task_type"] == "data_deep_dive"
    # scope_tags should be populated from the task text
    assert len(runs[0]["scope_tags"]) > 0
    assert "cpi" in runs[0]["scope_tags"]


def test_audit_error_path_preserves_scope_tags():
    """Failed sub-agent runs should still persist scope_tags in audit."""
    store = _temp_store()
    # Provider that raises on complete → triggers the error path
    class FailingProvider:
        def complete(self, **kwargs):
            raise ValueError("simulated failure")
    spec = SubAgentSpec(
        name="data_deep_dive",
        description="test",
        system_prompt="test",
        tools=[_dummy_tool()],
    )
    handler = SubAgentHandler(spec, FailingProvider(), store=store, parent_agent="research")
    result = handler({"task": "Analyze US CPI inflation data"})
    assert result["status"] == "error"

    runs = store.list_recent_subagent_runs(limit=10)
    assert len(runs) == 1
    assert runs[0]["scope_tags"] != []
    assert "cpi" in runs[0]["scope_tags"]
