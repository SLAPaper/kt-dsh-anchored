"""Unit tests for AnchoredToolBootstrapPlugin."""

import pytest

from kohakuterrarium.modules.plugin.base import ToolVisibility
from kohakuterrarium.modules.plugin.option_validation import PluginOptionError
from kt_dsh_anchored.plugins.bootstrap import AnchoredToolBootstrapPlugin


class _FakeStore:
    def __init__(self, events=None):
        self.events = events if events is not None else {}


class _FakeContext:
    def __init__(self, store):
        self.session_store = store


def _event(event_type):
    return {"type": event_type}


class TestVisibility:
    def test_fresh_session_restricts_to_bootstrap_tools(self):
        plugin = AnchoredToolBootstrapPlugin()
        ctx = _FakeContext(_FakeStore())
        assert plugin.get_tool_visibility(ctx) == ToolVisibility(
            allowed_tools=frozenset({"read", "bash"}),
            allowed_subagents=frozenset(),
        )

    def test_durable_tool_call_promotes_full_catalog(self):
        plugin = AnchoredToolBootstrapPlugin()
        ctx = _FakeContext(_FakeStore({"e0": _event("tool_call")}))
        assert plugin.get_tool_visibility(ctx) is None

    def test_other_events_do_not_promote(self):
        plugin = AnchoredToolBootstrapPlugin()
        ctx = _FakeContext(_FakeStore({"e0": _event("text_chunk")}))
        visibility = plugin.get_tool_visibility(ctx)
        assert visibility is not None
        assert visibility.allowed_tools == frozenset({"read", "bash"})

    async def test_dispatch_promotes_sessionless_runs(self):
        plugin = AnchoredToolBootstrapPlugin()
        ctx = _FakeContext(None)
        assert plugin.get_tool_visibility(ctx) is not None
        await plugin.pre_tool_dispatch(object(), ctx)
        assert plugin.get_tool_visibility(ctx) is None


class TestOptions:
    def test_custom_bootstrap_tools(self):
        plugin = AnchoredToolBootstrapPlugin(bootstrap_tools=["read", "grep"])
        ctx = _FakeContext(_FakeStore())
        visibility = plugin.get_tool_visibility(ctx)
        assert visibility.allowed_tools == frozenset({"read", "grep"})

    def test_nested_options_mapping(self):
        plugin = AnchoredToolBootstrapPlugin(
            options={"bootstrap_tools": ["read", "bash", "glob"]}
        )
        ctx = _FakeContext(_FakeStore())
        visibility = plugin.get_tool_visibility(ctx)
        assert visibility.allowed_tools == frozenset({"read", "bash", "glob"})

    def test_empty_tools_rejected(self):
        with pytest.raises(TypeError, match="non-empty"):
            AnchoredToolBootstrapPlugin(bootstrap_tools=[])

    def test_non_string_tools_rejected_by_schema(self):
        with pytest.raises(PluginOptionError, match="string"):
            AnchoredToolBootstrapPlugin(bootstrap_tools=[1])


class TestPromptSanitization:
    async def test_skill_index_block_is_stripped(self):
        plugin = AnchoredToolBootstrapPlugin()
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful software engineer assistant.\n\n"
                    "## Skills\n\nProcedural skills loaded for this session.\n\n"
                    "- `arming-thought` — example skill\n\n"
                    "Run `info` for the full body before executing a skill.\n"
                ),
            },
            {"role": "user", "content": "hi"},
        ]
        cleaned = await plugin.pre_llm_call(messages)
        assert cleaned is not None
        assert cleaned[0]["content"] == "You are a helpful software engineer assistant."
        assert cleaned[1] == messages[1]

    async def test_prompt_without_skill_index_is_unchanged(self):
        plugin = AnchoredToolBootstrapPlugin()
        messages = [{"role": "system", "content": "Minimal prompt only."}]
        assert await plugin.pre_llm_call(messages) is None

    async def test_non_string_system_content_is_untouched(self):
        plugin = AnchoredToolBootstrapPlugin()
        content = [{"type": "text", "text": "## Skills"}]
        messages = [{"role": "system", "content": content}]
        assert await plugin.pre_llm_call(messages) is None
