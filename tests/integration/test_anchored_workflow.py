"""End-to-end workflow: anchored bootstrap across two native requests.

The first request must see only read+bash; after the session records its
first tool_call event, the next request (and any fresh agent attached to
the same durable store) sees the complete catalog.
"""

import json

import pytest

from kohakuterrarium.builtins.tool_catalog import get_builtin_tool
from kohakuterrarium.core.agent import Agent
from kohakuterrarium.core.config_types import AgentConfig, InputConfig, OutputConfig
from kohakuterrarium.core.events import create_user_input_event
from kohakuterrarium.llm.base import NativeToolCall
from kohakuterrarium.session.store import SessionStore
from kohakuterrarium.testing.llm import ScriptedLLM, ScriptEntry
from kt_dsh_anchored.plugins.bootstrap import AnchoredToolBootstrapPlugin

pytestmark = pytest.mark.timeout(30)


class _CapturingNativeLLM(ScriptedLLM):
    """Scripted LLM that captures native tool schemas per request and
    emits one native read call on its first round."""

    def __init__(self, script, first_round_call):
        super().__init__(script)
        self._first_round_call = first_round_call
        self.last_tool_calls: list[NativeToolCall] = []
        self.last_assistant_extra_fields: dict = {}
        self.request_tools: list[list[str]] = []
        self.request_systems: list[str] = []

    async def chat(self, messages, **kwargs):
        tools = kwargs.get("tools") or []
        self.request_tools.append([tool.name for tool in tools])
        system_messages = [m for m in messages if m.get("role") == "system"]
        self.request_systems.append(
            system_messages[0].get("content", "") if system_messages else ""
        )
        idx = self.call_count
        self.last_tool_calls = []
        async for chunk in super().chat(messages, **kwargs):
            yield chunk
        if idx == 0 and self._first_round_call is not None:
            self.last_tool_calls = [self._first_round_call]


def _make_config(tmp_path):
    return AgentConfig(
        name="anchored_test",
        system_prompt="You are a helpful software engineer assistant.",
        include_tools_in_prompt=False,
        include_hints_in_prompt=False,
        tool_format="native",
        agent_path=tmp_path,
        input=InputConfig(type="none"),
        output=OutputConfig(type="stdout"),
    )


def _make_agent(cfg, llm, store):
    agent = Agent(
        cfg,
        llm=llm,
        tools=[
            get_builtin_tool("read"),
            get_builtin_tool("bash"),
            get_builtin_tool("glob"),
        ],
        plugins=[AnchoredToolBootstrapPlugin()],
    )
    agent.attach_session_store(store)
    return agent


async def test_two_phase_catalog_and_durable_promotion(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    read_call = NativeToolCall(
        "call-1",
        "read",
        json.dumps({"path": str(target)}),
    )

    store = SessionStore(tmp_path / "run.kohakutr")
    llm = _CapturingNativeLLM(
        [ScriptEntry("reading now"), ScriptEntry("done")],
        first_round_call=read_call,
    )
    agent = _make_agent(_make_config(tmp_path), llm, store)
    await agent.start()
    try:
        await agent._process_event(create_user_input_event("inspect the file"))
    finally:
        await agent.stop()
    store.close()

    assert len(llm.request_tools) >= 2
    assert set(llm.request_tools[0]) == {"bash", "read"}
    assert "## Skills" not in llm.request_systems[0]
    assert set(llm.request_tools[1]) == {"bash", "glob", "read", "skill"}

    # A fresh agent attached to the same durable store starts promoted.
    resumed_llm = _CapturingNativeLLM([ScriptEntry("resumed")], first_round_call=None)
    reopened = SessionStore(tmp_path / "run.kohakutr")
    resumed = _make_agent(_make_config(tmp_path), resumed_llm, reopened)
    await resumed.start()
    try:
        await resumed._process_event(create_user_input_event("resume please"))
    finally:
        await resumed.stop()
    reopened.close()

    assert set(resumed_llm.request_tools[0]) == {"bash", "glob", "read", "skill"}
