"""Tests for companion agent tool assembly, research delegation, and tool use flow."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.agents.base import AgentRoleSpec, RoleDependencies, RolePromptContext
from analyst.agents.companion.companion_agent import (
    _build_companion_tools,
    build_companion_role_spec,
)
from analyst.agents.companion.companion_prompts import build_companion_system_prompt
from analyst.agents.companion.spec_builder import (
    ResearchDelegationSpec,
    _sanitize_context,
    build_research_delegation_spec,
    render_research_delegation_prompt,
)
from analyst.engine.executor import ExecutorBackend
from analyst.engine.live_provider import ClaudeCodeProvider
from analyst.engine.live_types import AgentTool, LLMProvider
from analyst.runtime.capabilities import (
    CAPABILITY_MATRIX,
    CapabilityBuildContext,
    build_capability_tools,
    get_capability_surface,
)
from analyst.runtime.chat import (
    ChatPersonaMode,
    TurnExecutionPlan,
    build_chat_tools,
    build_companion_tools,
    resolve_chat_persona_mode,
    resolve_turn_execution_plan,
    system_prompt_with_memory,
)


def _make_mock_provider() -> MagicMock:
    """Create a generic MagicMock LLM provider (not ClaudeCode)."""
    provider = MagicMock(spec=LLMProvider)
    provider.complete = MagicMock()
    return provider


def _make_claude_code_provider() -> MagicMock:
    """Create a MagicMock that isinstance-checks as ClaudeCodeProvider."""
    provider = MagicMock(spec=ClaudeCodeProvider)
    return provider


def _make_mock_store() -> MagicMock:
    """Create a MagicMock SQLiteEngineStore."""
    store = MagicMock()
    store.db_path = Path("/tmp/test.db")
    return store


def _make_agent_tool(name: str = "test_tool") -> AgentTool:
    return AgentTool(
        name=name,
        description=f"Test tool {name}",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "ok",
    )


def _make_mock_executor(backend: ExecutorBackend = ExecutorBackend.HOST_LOOP) -> MagicMock:
    """Create a mock AgentExecutor."""
    executor = MagicMock()
    executor.backend = backend
    executor.provider = _make_mock_provider()
    executor.mcp_tool_names = ()
    executor.config = MagicMock()
    return executor


# ---------------------------------------------------------------------------
# 1. Companion Tool Assembly
# ---------------------------------------------------------------------------

class TestBuildCompanionRoleSpec(unittest.TestCase):
    """Test build_companion_role_spec returns a valid AgentRoleSpec."""

    def test_role_id_is_companion(self):
        spec = build_companion_role_spec()
        self.assertIsInstance(spec, AgentRoleSpec)
        self.assertEqual(spec.role_id, "companion")

    def test_has_system_prompt_builder(self):
        spec = build_companion_role_spec()
        self.assertTrue(callable(spec.build_system_prompt))

    def test_has_tools_builder(self):
        spec = build_companion_role_spec()
        self.assertTrue(callable(spec.build_tools))


class TestBuildCompanionTools(unittest.TestCase):
    """Test _build_companion_tools tool list composition."""

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_contains_generate_image(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        mock_research.return_value = _make_agent_tool("research_agent")
        deps = RoleDependencies(provider=_make_mock_provider())
        tools = _build_companion_tools(deps)
        tool_names = [t.name for t in tools]
        self.assertIn("generate_image", tool_names)

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_may_contain_live_photo(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = _make_agent_tool("generate_live_photo")
        mock_research.return_value = _make_agent_tool("research_agent")
        deps = RoleDependencies(provider=_make_mock_provider())
        tools = _build_companion_tools(deps)
        tool_names = [t.name for t in tools]
        self.assertIn("generate_live_photo", tool_names)

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_contains_research_agent_for_non_claudecode(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        mock_research.return_value = _make_agent_tool("research_agent")
        deps = RoleDependencies(provider=_make_mock_provider())
        tools = _build_companion_tools(deps)
        tool_names = [t.name for t in tools]
        self.assertIn("research_agent", tool_names)

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_excludes_research_agent_for_claudecode(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        mock_research.return_value = _make_agent_tool("research_agent")
        deps = RoleDependencies(provider=_make_claude_code_provider())
        tools = _build_companion_tools(deps)
        tool_names = [t.name for t in tools]
        self.assertNotIn("research_agent", tool_names)
        # build_research_agent_tool should not even be called
        mock_research.assert_not_called()

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_no_live_photo_when_unavailable(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        mock_research.return_value = None
        deps = RoleDependencies(provider=_make_mock_provider())
        tools = _build_companion_tools(deps)
        tool_names = [t.name for t in tools]
        self.assertNotIn("generate_live_photo", tool_names)

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_no_research_agent_when_builder_returns_none(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        mock_research.return_value = None
        deps = RoleDependencies(provider=_make_mock_provider())
        tools = _build_companion_tools(deps)
        tool_names = [t.name for t in tools]
        self.assertNotIn("research_agent", tool_names)


class TestBuildCompanionSystemPrompt(unittest.TestCase):
    """Test build_companion_system_prompt produces a valid system prompt."""

    @patch("analyst.agents.companion.companion_prompts.assemble_persona_system_prompt")
    def test_prompt_has_companion_identity(self, mock_assemble):
        mock_assemble.return_value = MagicMock(
            prompt="你是陈襄 (Shawn Chan)，一个companion风格的角色。sunny cheerful personality."
        )
        ctx = RolePromptContext(user_text="hello")
        prompt = build_companion_system_prompt(ctx)
        self.assertIn("陈襄", prompt)
        self.assertIn("Shawn Chan", prompt)
        self.assertIn("companion", prompt)
        self.assertIn("sunny", prompt)
        self.assertIn("cheerful", prompt)

    @patch("analyst.agents.companion.companion_prompts.assemble_persona_system_prompt")
    def test_prompt_contains_research_delegation_module(self, mock_assemble):
        mock_assemble.return_value = MagicMock(prompt="Base persona prompt.")
        ctx = RolePromptContext(user_text="hello")
        prompt = build_companion_system_prompt(ctx)
        self.assertIn("Research delegation:", prompt)
        self.assertIn("research_agent", prompt)

    @patch("analyst.agents.companion.companion_prompts.assemble_persona_system_prompt")
    def test_prompt_is_string(self, mock_assemble):
        mock_assemble.return_value = MagicMock(prompt="Some base prompt.")
        ctx = RolePromptContext()
        prompt = build_companion_system_prompt(ctx)
        self.assertIsInstance(prompt, str)
        self.assertTrue(len(prompt) > 0)


# ---------------------------------------------------------------------------
# 2. Research Delegation
# ---------------------------------------------------------------------------

class TestBuildResearchDelegationSpec(unittest.TestCase):
    """Test build_research_delegation_spec."""

    def test_valid_spec_creation(self):
        args = {
            "task": "What moved the S&P 500 today?",
            "goal": "Explain the market move to the user.",
            "analysis_type": "markets",
            "output_format": "summary",
            "time_horizon": "today",
            "context": "User is concerned about tech exposure.",
        }
        spec = build_research_delegation_spec(args)
        self.assertIsInstance(spec, ResearchDelegationSpec)
        self.assertEqual(spec.task, "What moved the S&P 500 today?")
        self.assertEqual(spec.analysis_type, "markets")
        self.assertEqual(spec.output_format, "summary")
        self.assertEqual(spec.time_horizon, "today")

    def test_normalized_analysis_type(self):
        args = {"task": "Check macro data", "analysis_type": "MACRO"}
        spec = build_research_delegation_spec(args)
        self.assertEqual(spec.analysis_type, "macro")

    def test_normalized_output_format(self):
        args = {"task": "Check news", "output_format": "Bullet_Points"}
        spec = build_research_delegation_spec(args)
        self.assertEqual(spec.output_format, "bullet_points")

    def test_invalid_analysis_type_falls_back_to_general(self):
        args = {"task": "Some task", "analysis_type": "nonexistent_type"}
        spec = build_research_delegation_spec(args)
        self.assertEqual(spec.analysis_type, "general")

    def test_invalid_output_format_falls_back_to_summary(self):
        args = {"task": "Some task", "output_format": "invalid_format"}
        spec = build_research_delegation_spec(args)
        self.assertEqual(spec.output_format, "summary")

    def test_missing_task_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_research_delegation_spec({})

    def test_empty_task_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_research_delegation_spec({"task": ""})

    def test_default_goal(self):
        spec = build_research_delegation_spec({"task": "Lookup rates"})
        self.assertIn("factual answer", spec.goal)

    def test_default_time_horizon(self):
        spec = build_research_delegation_spec({"task": "Lookup rates"})
        self.assertEqual(spec.time_horizon, "current")

    def test_task_truncation(self):
        long_task = "x" * 600
        spec = build_research_delegation_spec({"task": long_task})
        self.assertLessEqual(len(spec.task), 500)
        self.assertTrue(spec.task.endswith("..."))


class TestRenderResearchDelegationPrompt(unittest.TestCase):
    """Test render_research_delegation_prompt output."""

    def test_prompt_formatting(self):
        spec = ResearchDelegationSpec(
            task="Check Fed rate expectations",
            goal="Give the companion a factual answer it can relay naturally.",
            analysis_type="macro",
            time_horizon="this week",
            output_format="briefing",
            context="User mentioned FOMC.",
        )
        prompt = render_research_delegation_prompt(spec)
        self.assertIn("Primary task:", prompt)
        self.assertIn("Check Fed rate expectations", prompt)
        self.assertIn("Research brief:", prompt)
        self.assertIn("- Analysis type: macro", prompt)
        self.assertIn("- Time horizon: this week", prompt)
        self.assertIn("- Output format: briefing", prompt)
        self.assertIn("User-safe context:", prompt)
        self.assertIn("User mentioned FOMC.", prompt)
        self.assertIn("Response requirements:", prompt)

    def test_prompt_without_context(self):
        spec = ResearchDelegationSpec(
            task="Check S&P",
            goal="Explain movement",
            analysis_type="markets",
            time_horizon="today",
            output_format="summary",
            context="",
        )
        prompt = render_research_delegation_prompt(spec)
        self.assertNotIn("User-safe context:", prompt)

    def test_prompt_contains_tool_instruction(self):
        spec = ResearchDelegationSpec(
            task="Lookup VIX",
            goal="Report regime",
            analysis_type="markets",
            time_horizon="current",
            output_format="summary",
            context="",
        )
        prompt = render_research_delegation_prompt(spec)
        self.assertIn("Use tools if freshness or factual accuracy matters", prompt)
        self.assertIn("Be concise and concrete", prompt)


class TestSanitizeContext(unittest.TestCase):
    """Test _sanitize_context filters internal metadata."""

    def test_filters_client_profile(self):
        text = "client_profile: {name: John}\nUser likes crypto."
        result = _sanitize_context(text)
        self.assertNotIn("client_profile", result)
        self.assertIn("User likes crypto", result)

    def test_filters_topic_state(self):
        text = "topic_state: active\nBTC is up 5%."
        result = _sanitize_context(text)
        self.assertNotIn("topic_state", result)
        self.assertIn("BTC is up 5%", result)

    def test_filters_speaker_memory(self):
        text = "speaker_memory: {...}\nUser asked about yields."
        result = _sanitize_context(text)
        self.assertNotIn("speaker_memory", result)
        self.assertIn("User asked about yields", result)

    def test_filters_delivery_history(self):
        text = "delivery_history: old stuff\nMarket update."
        result = _sanitize_context(text)
        self.assertNotIn("delivery_history", result)
        self.assertIn("Market update", result)

    def test_filters_profile_update_tags(self):
        text = "<profile_update>\nsome update\n</profile_update>\nClean line."
        result = _sanitize_context(text)
        self.assertNotIn("<profile_update>", result)
        self.assertNotIn("</profile_update>", result)
        self.assertIn("Clean line", result)

    def test_empty_input(self):
        self.assertEqual(_sanitize_context(""), "")
        self.assertEqual(_sanitize_context(None), "")

    def test_normal_text_passes_through(self):
        text = "The user wants to understand why oil prices dropped."
        result = _sanitize_context(text)
        self.assertIn("oil prices dropped", result)

    def test_truncation_at_max_chars(self):
        long_text = "Safe context line. " * 100
        result = _sanitize_context(long_text)
        self.assertLessEqual(len(result), 700)


# ---------------------------------------------------------------------------
# 3. Capability Integration
# ---------------------------------------------------------------------------

class TestCapabilityToolsCompanion(unittest.TestCase):
    """Test build_capability_tools for the companion surface."""

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_build_capability_tools_companion(self, mock_img, mock_live, mock_research):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        mock_research.return_value = _make_agent_tool("research_agent")
        provider = _make_mock_provider()
        store = _make_mock_store()
        tools = build_capability_tools("companion", store=store, provider=provider)
        self.assertIsInstance(tools, list)
        tool_names = [t.name for t in tools]
        self.assertIn("generate_image", tool_names)

    def test_companion_surface_exists_in_matrix(self):
        self.assertIn("companion", CAPABILITY_MATRIX)
        spec = get_capability_surface("companion")
        self.assertEqual(spec.surface_id, "companion")

    def test_companion_surface_has_build_tools(self):
        spec = get_capability_surface("companion")
        self.assertIsNotNone(spec.build_tools)


class TestBuildCompanionToolsShorthand(unittest.TestCase):
    """Test the build_companion_tools() shorthand in chat.py."""

    @patch("analyst.runtime.chat.build_capability_tools")
    def test_shorthand_calls_capability_tools(self, mock_build):
        mock_build.return_value = [_make_agent_tool("generate_image")]
        result = build_companion_tools()
        mock_build.assert_called_once_with("companion")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "generate_image")


class TestBuildChatTools(unittest.TestCase):
    """Test build_chat_tools always returns companion tools."""

    @patch("analyst.runtime.chat.build_capability_tools")
    def test_returns_companion_tools_regardless_of_persona(self, mock_build):
        mock_build.return_value = [_make_agent_tool("generate_image")]
        result = build_chat_tools(persona_mode="sales")
        mock_build.assert_called_once_with("companion", store=None, provider=None)
        self.assertEqual(len(result), 1)

    @patch("analyst.runtime.chat.build_capability_tools")
    def test_returns_companion_tools_with_no_args(self, mock_build):
        mock_build.return_value = [_make_agent_tool("generate_image")]
        result = build_chat_tools()
        mock_build.assert_called_once_with("companion", store=None, provider=None)
        self.assertIsInstance(result, list)

    @patch("analyst.runtime.chat.build_capability_tools")
    def test_passes_store_and_provider(self, mock_build):
        mock_build.return_value = []
        store = _make_mock_store()
        provider = _make_mock_provider()
        build_chat_tools(store=store, provider=provider)
        mock_build.assert_called_once_with("companion", store=store, provider=provider)

    @patch("analyst.runtime.chat.build_capability_tools")
    def test_ignores_engine_parameter(self, mock_build):
        mock_build.return_value = []
        engine = MagicMock()
        build_chat_tools(engine=engine, persona_mode=ChatPersonaMode.COMPANION)
        # engine is del'd, so build_capability_tools should be called with store=None, provider=None
        mock_build.assert_called_once_with("companion", store=None, provider=None)


class TestBuildCompanionServices(unittest.TestCase):
    """Test build_companion_services creates executor, tools, and store."""

    @patch("analyst.runtime.chat.build_agent_executor")
    @patch("analyst.runtime.chat._build_configured_companion_tools")
    @patch("analyst.runtime.chat.SQLiteEngineStore")
    @patch("analyst.runtime.chat.build_llm_provider_from_env")
    def test_creates_executor_tools_store(
        self, mock_factory, mock_store_cls, mock_build_tools, mock_build_executor
    ):
        mock_provider = _make_mock_provider()
        mock_factory.return_value = mock_provider
        mock_store = _make_mock_store()
        mock_store_cls.return_value = mock_store
        mock_build_tools.return_value = [_make_agent_tool("generate_image")]
        mock_executor = _make_mock_executor()
        mock_build_executor.return_value = mock_executor

        from analyst.runtime.chat import build_companion_services

        executor, tools, store = build_companion_services(
            provider_factory=mock_factory,
        )
        self.assertIs(executor, mock_executor)
        self.assertIsInstance(tools, list)
        self.assertIs(store, mock_store)


class TestResolveChatPersonaMode(unittest.TestCase):
    """Test resolve_chat_persona_mode always returns COMPANION."""

    def test_returns_companion_for_none(self):
        self.assertEqual(resolve_chat_persona_mode(None), ChatPersonaMode.COMPANION)

    def test_returns_companion_for_sales_string(self):
        self.assertEqual(resolve_chat_persona_mode("sales"), ChatPersonaMode.COMPANION)

    def test_returns_companion_for_companion_enum(self):
        self.assertEqual(
            resolve_chat_persona_mode(ChatPersonaMode.COMPANION),
            ChatPersonaMode.COMPANION,
        )

    def test_returns_companion_for_arbitrary_value(self):
        self.assertEqual(resolve_chat_persona_mode("anything"), ChatPersonaMode.COMPANION)


class TestResolveTurnExecutionPlan(unittest.TestCase):
    """Test resolve_turn_execution_plan for various input patterns."""

    def test_regular_text_host_loop(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        tools = [_make_agent_tool("generate_image"), _make_agent_tool("research_agent")]
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=tools,
            user_text="What happened in markets today?",
            user_content=None,
        )
        self.assertIsInstance(plan, TurnExecutionPlan)
        self.assertFalse(plan.use_native_execution)
        self.assertEqual(len(plan.active_tools), 2)

    def test_selfie_request_host_loop(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        tools = [_make_agent_tool("generate_image")]
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=tools,
            user_text="Send me a selfie!",
            user_content=None,
        )
        # Selfie is not a visual analysis request, so tools should be active
        self.assertFalse(plan.use_native_execution)
        self.assertEqual(len(plan.active_tools), 1)

    def test_visual_analysis_with_image_host_loop(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        tools = [_make_agent_tool("generate_image")]
        user_content = [{"type": "image_url", "image_url": {"url": "data:..."}}]
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=tools,
            user_text="What do you see in this image?",
            user_content=user_content,
        )
        # Visual analysis with attached image => prefer direct reply
        self.assertTrue(plan.use_native_execution)
        self.assertEqual(len(plan.active_tools), 0)

    def test_claude_code_backend_always_native(self):
        executor = _make_mock_executor(ExecutorBackend.CLAUDE_CODE)
        executor.mcp_tool_names = ("fetch_live_calendar", "search_news")
        tools = [_make_agent_tool("generate_image")]
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=tools,
            user_text="What is the weather?",
            user_content=None,
        )
        self.assertTrue(plan.use_native_execution)
        self.assertEqual(len(plan.active_tools), 0)
        self.assertEqual(plan.mcp_tool_names, ("fetch_live_calendar", "search_news"))

    def test_language_detection_chinese(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[],
            user_text="今天市场怎么样？",
            user_content=None,
        )
        self.assertEqual(plan.user_lang, "zh")

    def test_language_detection_english(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[],
            user_text="How are the markets doing today?",
            user_content=None,
        )
        self.assertEqual(plan.user_lang, "en")

    def test_language_fallback_for_short_text(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[],
            user_text="ok",
            user_content=None,
            preferred_language="zh",
        )
        self.assertEqual(plan.user_lang, "zh")


# ---------------------------------------------------------------------------
# 4. System Prompt Assembly
# ---------------------------------------------------------------------------

class TestSystemPromptWithMemory(unittest.TestCase):
    """Test system_prompt_with_memory for various input scenarios."""

    @patch("analyst.runtime.chat.get_role_spec")
    @patch("analyst.runtime.chat.coerce_agent_executor", return_value=None)
    def test_empty_memory(self, mock_coerce, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Base companion prompt."
        mock_get_spec.return_value = mock_spec
        prompt = system_prompt_with_memory("")
        self.assertIsInstance(prompt, str)
        self.assertIn("Base companion prompt", prompt)

    @patch("analyst.runtime.chat.get_role_spec")
    @patch("analyst.runtime.chat.coerce_agent_executor", return_value=None)
    def test_with_memory_context(self, mock_coerce, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Prompt with memory injected."
        mock_get_spec.return_value = mock_spec
        prompt = system_prompt_with_memory("User prefers Chinese. User is interested in macro.")
        mock_spec.build_system_prompt.assert_called_once()
        ctx_arg = mock_spec.build_system_prompt.call_args[0][0]
        self.assertEqual(ctx_arg.memory_context, "User prefers Chinese. User is interested in macro.")

    @patch("analyst.runtime.chat.get_role_spec")
    @patch("analyst.runtime.chat.coerce_agent_executor", return_value=None)
    def test_with_group_context(self, mock_coerce, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Group prompt."
        mock_get_spec.return_value = mock_spec
        prompt = system_prompt_with_memory("", group_context="Group: trading chat")
        ctx_arg = mock_spec.build_system_prompt.call_args[0][0]
        self.assertEqual(ctx_arg.group_context, "Group: trading chat")

    @patch("analyst.runtime.chat.get_role_spec")
    @patch("analyst.runtime.chat.coerce_agent_executor", return_value=None)
    def test_with_proactive_kind(self, mock_coerce, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Proactive prompt."
        mock_get_spec.return_value = mock_spec
        prompt = system_prompt_with_memory("", proactive_kind="morning")
        ctx_arg = mock_spec.build_system_prompt.call_args[0][0]
        self.assertEqual(ctx_arg.proactive_kind, "morning")

    @patch("analyst.runtime.chat.get_role_spec")
    @patch("analyst.runtime.chat.coerce_agent_executor", return_value=None)
    def test_user_lang_passthrough(self, mock_coerce, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Prompt."
        mock_get_spec.return_value = mock_spec
        prompt = system_prompt_with_memory("", user_lang="en")
        ctx_arg = mock_spec.build_system_prompt.call_args[0][0]
        self.assertEqual(ctx_arg.user_lang, "en")

    @patch("analyst.runtime.chat.get_role_spec")
    def test_capability_overlay_with_tools(self, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Base prompt."
        mock_get_spec.return_value = mock_spec
        tools = [_make_agent_tool("generate_image"), _make_agent_tool("research_agent")]
        prompt = system_prompt_with_memory("", tools=tools)
        self.assertIn("CURRENT CAPABILITIES", prompt)
        self.assertIn("generate_image", prompt)
        self.assertIn("research_agent", prompt)

    @patch("analyst.runtime.chat.get_role_spec")
    def test_no_overlay_when_no_tools(self, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Base prompt."
        mock_get_spec.return_value = mock_spec
        prompt = system_prompt_with_memory("")
        self.assertNotIn("CURRENT CAPABILITIES", prompt)

    @patch("analyst.runtime.chat.get_role_spec")
    def test_persona_mode_ignored(self, mock_get_spec):
        mock_spec = MagicMock()
        mock_spec.build_system_prompt.return_value = "Base prompt."
        mock_get_spec.return_value = mock_spec
        # persona_mode is del'd, should still work
        prompt1 = system_prompt_with_memory("", persona_mode="sales")
        prompt2 = system_prompt_with_memory("", persona_mode=ChatPersonaMode.COMPANION)
        # Both should call with the same context
        self.assertEqual(
            mock_get_spec.call_count, 2,
            "get_role_spec should be called once per invocation",
        )


# ---------------------------------------------------------------------------
# Additional edge-case and integration tests
# ---------------------------------------------------------------------------

class TestResearchDelegationEdgeCases(unittest.TestCase):
    """Additional edge-case tests for research delegation."""

    def test_whitespace_only_task_raises(self):
        with self.assertRaises(ValueError):
            build_research_delegation_spec({"task": "   "})

    def test_context_with_multiple_filtered_lines(self):
        text = (
            "client_profile: secret\n"
            "topic_state: internal\n"
            "User asked about gold.\n"
            "current_thread: something\n"
            "They want a quick answer."
        )
        result = _sanitize_context(text)
        self.assertNotIn("client_profile", result)
        self.assertNotIn("topic_state", result)
        self.assertNotIn("current_thread", result)
        self.assertIn("User asked about gold", result)
        self.assertIn("quick answer", result)


class TestCapabilitySurfaceValidation(unittest.TestCase):
    """Test capability surface validation edge cases."""

    def test_unknown_surface_raises(self):
        with self.assertRaises(KeyError):
            get_capability_surface("nonexistent_surface")

    @patch("analyst.agents.companion.companion_agent.build_research_agent_tool")
    @patch("analyst.agents.companion.companion_agent.build_optional_live_photo_tool")
    @patch("analyst.agents.companion.companion_agent.build_image_gen_tool")
    def test_sub_agent_validation_skipped_for_claudecode(
        self, mock_img, mock_live, mock_research
    ):
        mock_img.return_value = _make_agent_tool("generate_image")
        mock_live.return_value = None
        # research_agent won't be built for ClaudeCode, but validation should not fail
        provider = _make_claude_code_provider()
        tools = build_capability_tools("companion", provider=provider)
        tool_names = [t.name for t in tools]
        self.assertNotIn("research_agent", tool_names)


class TestTurnExecutionPlanNativeToolNames(unittest.TestCase):
    """Test native_tool_names are correctly propagated in plans."""

    def test_claude_code_default_native_tools(self):
        from analyst.runtime.capabilities import CLAUDE_CODE_NATIVE_TOOL_NAMES
        executor = _make_mock_executor(ExecutorBackend.CLAUDE_CODE)
        executor.mcp_tool_names = ()
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[],
            user_text="Hello",
            user_content=None,
        )
        self.assertEqual(plan.native_tool_names, CLAUDE_CODE_NATIVE_TOOL_NAMES)

    def test_custom_native_tool_names(self):
        executor = _make_mock_executor(ExecutorBackend.CLAUDE_CODE)
        executor.mcp_tool_names = ()
        custom_names = ("CustomTool1", "CustomTool2")
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[],
            user_text="Hello",
            user_content=None,
            native_tool_names=custom_names,
        )
        self.assertEqual(plan.native_tool_names, custom_names)

    def test_host_loop_no_mcp(self):
        executor = _make_mock_executor(ExecutorBackend.HOST_LOOP)
        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[_make_agent_tool("test")],
            user_text="What is the weather in Singapore?",
            user_content=None,
        )
        self.assertEqual(plan.mcp_tool_names, ())


if __name__ == "__main__":
    unittest.main()
