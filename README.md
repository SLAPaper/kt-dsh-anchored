# kt-dsh-anchored

A self-contained KohakuTerrarium package for DeepSeek V4 Pro: a creature
preset that starts each session with the Minimal-aligned system prompt and
only `read` + `bash`, then exposes the complete declared tool catalog
after the session records its first durable `tool_call` event.

> [!IMPORTANT]
> This package requires the tool-visibility plugin seam from upstream PR
> https://github.com/Kohaku-Lab/KohakuTerrarium/pull/163 (merged as
> `a83d90e3`). Use a KohakuTerrarium build that contains that commit.

This package does not ship a DeepSeek model profile. Configure one
through `kt model` / `llm_profiles.yaml` and point the creature at it.

## Install

```powershell
kt install https://github.com/SLAPaper/kt-dsh-anchored.git
```

The creature declares its own tools, sub-agents, and prompt; it has no
runtime dependency on `@kt-biome/creatures/general`.

## Run

```powershell
kt run @kt-dsh-anchored/creatures/anchored-standard
```

## Migrate into your own creature

```yaml
base_config: "@kt-dsh-anchored/creatures/anchored-standard"
```

Override or disable the plugin per creature:

```yaml
no_inherit: [plugins]
plugins:
  - name: anchored_tool_bootstrap
    options:
      bootstrap_tools: [read, bash]
```

## Behavior

- Native tool calling only (`tool_format: native`); text-mode prompt
  filtering is out of scope.
- The first request of a fresh session sees exactly the bootstrap tools
  and no sub-agents.
- The creature declares its own tool/sub-agent catalog and enables no
  other plugins by default, so prompt contributions stay minimal.
- Promotion is derived from the persisted session event log, so resume
  and reload keep the correct phase. A failed tool still promotes.
- Sessions without a durable store promote in memory on the first
  dispatched tool call.

## Development

```powershell
pip install -e .
pytest
```
