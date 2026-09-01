# Contributing To PhyAgentOS TUI

Thank you for helping improve PhyAgentOS TUI.

This repository contains the terminal interface layer for PhyAgentOS. The core
agent runtime, Forge Tool API implementation, provider abstractions, channels,
verification logic, and Skill Runtime contracts live in `PhyAgentOS-ai`.

## Design Boundary

TUI changes should stay inside the interface layer:

- Inspect and present core runtime state clearly.
- Edit supported local configuration through core config APIs.
- Route user input through the existing PhyAgentOS message bus.
- Reuse core provider, channel, Forge, AgentTask, and Skill Runtime contracts.

TUI changes should not introduce a second physical execution protocol, bypass
Forge Tool API boundaries, or encode action-specific verifier behavior.

## Development Setup

```bash
python -m pip install -e ".[dev]"
```

Run checks before opening a pull request:

```bash
ruff check phyagentos_tui tests
pytest
python -m compileall -q phyagentos_tui tests
```

## Pull Request Checklist

- Keep user-facing behavior aligned with the current PhyAgentOS core `dev`
  branch.
- Avoid exposing local absolute paths, usernames, API keys, or provider secrets
  in the UI.
- Update `README.md`, `README_zh.md`, or `CHANGELOG.md` when behavior,
  configuration, installation, or compatibility changes.
- Add or update tests for navigation, imports, and data-formatting behavior
  when touching shared UI or service code.
- Keep demo, marketing, and one-off showcase scripts out of the package.

## Release Notes

When preparing a release:

1. Replace the core branch dependency with the matching released
   `PhyAgentOS-ai` version.
2. Update `CHANGELOG.md`.
3. Verify the package metadata in `pyproject.toml`.
4. Build the distribution with `python -m build`.
