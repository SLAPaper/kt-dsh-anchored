"""Anchored tool bootstrap plugin for DeepSeek-style sessions.

The first request of a fresh session sees only the configured bootstrap
tools (default ``read`` + ``bash``) and a minimal system prompt. Once the
durable session log records its first ``tool_call`` event, every later
request sees the complete catalog, skill index, and full system prompt.
Sessions without a durable store fall back to an in-memory promotion flag
set when the first tool call is dispatched.
"""

import re
from typing import Any

from kohakuterrarium.modules.plugin.base import BasePlugin, ToolVisibility

DEFAULT_BOOTSTRAP_TOOLS = ("read", "bash")
DEFAULT_DISABLED_PLUGINS = ("goal", "drive_runtime")
TOOL_CALL_EVENT = "tool_call"
_SKILL_INDEX_PATTERN = re.compile(
    r"\n## Skills\n.*?\nRun `info` for the full body before executing a skill\.\n",
    re.DOTALL,
)


def _strip_skill_index(content: str) -> str:
    """Remove the auto-generated skill index block from a system prompt."""
    return _SKILL_INDEX_PATTERN.sub("", content).rstrip()


class AnchoredToolBootstrapPlugin(BasePlugin):
    """Hide every tool except the bootstrap set until the first tool call."""

    name = "anchored_tool_bootstrap"
    version = "0.2.0"
    description = (
        "Expose only read+bash on the first request, then the full catalog "
        "after the session records its first tool_call event."
    )
    priority = 400

    @classmethod
    def option_schema(cls) -> dict[str, dict[str, Any]]:
        """Declare the bootstrap catalog as a runtime-mutable option."""
        return {
            "bootstrap_tools": {
                "type": "list",
                "item_type": "string",
                "default": list(DEFAULT_BOOTSTRAP_TOOLS),
                "doc": "Tool names visible before the first durable tool call.",
            },
            "disabled_plugins": {
                "type": "list",
                "item_type": "string",
                "default": list(DEFAULT_DISABLED_PLUGINS),
                "doc": "Runtime plugins to keep disabled while this plugin is enabled.",
            },
        }

    def __init__(self, *, options: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__()
        self.options = {
            "bootstrap_tools": list(DEFAULT_BOOTSTRAP_TOOLS),
            "disabled_plugins": list(DEFAULT_DISABLED_PLUGINS),
        }
        merged = dict(options or {})
        merged.update(kwargs)
        if merged:
            self.set_options(merged)
        self._bootstrap_tools = self._validate_tools(
            self.options.get("bootstrap_tools")
        )
        self._disabled_plugins = self._validate_tools(
            self.options.get("disabled_plugins")
        )
        self._context: Any = None
        self._promoted_memory = False

    def refresh_options(self) -> None:
        """Re-derive the bootstrap frozenset after validated option updates."""
        self._bootstrap_tools = self._validate_tools(
            self.options.get("bootstrap_tools")
        )
        self._disabled_plugins = self._validate_tools(
            self.options.get("disabled_plugins")
        )

    async def on_load(self, context: Any) -> None:
        """Keep runtime-injected plugins disabled and retain host context."""
        self._context = context
        host_agent = getattr(context, "host_agent", None)
        plugins = getattr(host_agent, "plugins", None)
        if plugins is None:
            return
        for plugin_name in self._disabled_plugins:
            if plugins.get_plugin(plugin_name) is not None:
                plugins.disable(plugin_name)

    def get_tool_visibility(self, context: Any) -> ToolVisibility | None:
        """Return the bootstrap restriction, or None once promoted."""
        if self._is_promoted(context):
            return None
        return ToolVisibility(
            allowed_tools=self._bootstrap_tools,
            allowed_subagents=frozenset(),
        )

    async def pre_llm_call(
        self, messages: list[dict], **kwargs: Any
    ) -> list[dict] | None:
        """Strip the skill index until the session's first tool call."""
        if self._is_promoted(self._context):
            return None
        cleaned: list[dict] = []
        changed = False
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system" and isinstance(content, str):
                stripped = _strip_skill_index(content)
                if stripped != content:
                    changed = True
                    message = {**message, "content": stripped}
            cleaned.append(message)
        return cleaned if changed else None

    async def pre_tool_dispatch(self, call: Any, context: Any) -> Any | None:
        """Promote in-memory sessions that have no durable event log."""
        self._promoted_memory = True
        return None

    def _is_promoted(self, context: Any) -> bool:
        if self._promoted_memory:
            return True
        store = getattr(context, "session_store", None)
        events = getattr(store, "events", None)
        if events is None:
            return False
        return any(data.get("type") == TOOL_CALL_EVENT for data in events.values())

    @staticmethod
    def _validate_tools(value: Any) -> frozenset[str]:
        if not isinstance(value, (list, tuple)) or not value:
            raise TypeError("bootstrap_tools must be a non-empty list of strings")
        tools = frozenset(str(item) for item in value)
        if not tools or any(not tool for tool in tools):
            raise TypeError("bootstrap_tools must contain non-empty strings")
        return tools
