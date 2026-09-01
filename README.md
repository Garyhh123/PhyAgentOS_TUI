# PhyAgentOS TUI

<p>
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.11-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/UI-Textual-7B61FF" alt="Textual">
  <img src="https://img.shields.io/badge/License-MIT-3DA639" alt="License">
</p>

<p>
  <sub>English | <a href="README_zh.md">中文</a> | <a href="https://github.com/PhyAgentOS/PhyAgentOS-core/tree/dev">PhyAgentOS Core</a></sub>
</p>

Official terminal user interface for PhyAgentOS.

`phyagentos-tui` provides a Textual-based console workspace for operating a
local PhyAgentOS installation. It keeps the terminal experience separate from
the core agent runtime while reusing the same configuration, providers,
channels, Forge Tool API, AgentTask ledger, and Skill Runtime state exposed by
`PhyAgentOS-ai`.

This repository intentionally contains no demonstration playback scripts. It is
the reusable interface layer for daily operation, inspection, and local
development.

## Relationship To Core

PhyAgentOS core owns the agent runtime and embodied execution contracts:

- Agent loop, tools, memory, Cron, Heartbeat, MCP, and channels
- Provider configuration and model routing
- Forge Tool API client and AgentTask persistence
- Evidence capture, verifier integration, recovery, and Skill Runtime state

PhyAgentOS TUI owns the terminal interface:

- Chat page for direct local interaction with the agent
- Providers page for API key and endpoint configuration
- Channels page for enabling or disabling configured channels
- Settings page for common local defaults
- Forge Runtime page for read-only inspection of sessions, artifacts, storage,
  and health signals
- Command palette, navigation, status pane, and log capture

Keeping these layers separate makes the UI easier to evolve without coupling
release timing to the physical-agent runtime.

## Install

Python 3.11 or 3.12 is recommended.

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS-TUI.git
cd PhyAgentOS-TUI
python -m pip install -e .
```

The current development dependency points to the PhyAgentOS core `dev` branch:

```toml
PhyAgentOS-ai @ git+https://github.com/PhyAgentOS/PhyAgentOS-core.git@dev
```

For a released package, replace this direct branch dependency with the matching
released `PhyAgentOS-ai` version.

## Run

Start the TUI directly:

```bash
paos-tui
```

Or run it as a Python module:

```bash
python -m phyagentos_tui
```

If PhyAgentOS core is installed with the optional TUI entry point, this command
can also launch the standalone package:

```bash
paos tui
```

## First Use

Initialize the PhyAgentOS workspace from the core package before using the TUI:

```bash
paos onboard
```

Then open the TUI and configure a provider:

1. Open `Providers`.
2. Select the provider you want to use.
3. Fill the API key and optional API base.
4. Save the provider and set it as default if needed.
5. Return to `Chat`.

The TUI reads and writes the same configuration used by the PhyAgentOS CLI.

## Screens

| Screen | Purpose |
|:-------|:--------|
| Chat | Direct local conversation with the PhyAgentOS agent through the in-process message bus. |
| Providers | Configure supported model providers, API keys, and compatible relay endpoints. |
| Channels | Inspect and toggle available channel integrations. |
| Settings | Edit common defaults such as provider, model, gateway port, theme, and tool settings. |
| Forge Runtime | Inspect persisted AgentTask, Skill Runtime, evidence, storage, and health records without exposing private local paths. |

## Keyboard

| Shortcut | Action |
|:---------|:-------|
| `Ctrl+K` | Open the command palette. |
| `Ctrl+1` to `Ctrl+5` | Switch between main pages. |
| `Alt+Left` / `Alt+Right` | Move to the previous or next page. |
| `Esc` | Return to Chat, or press twice from Chat to quit. |
| `Ctrl+R` | Restart the local gateway service. |

Some pages also provide local shortcuts such as refresh, save, search, or copy.
Use `?` on supported pages for page-specific help.

## Development

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run quality checks:

```bash
ruff check phyagentos_tui tests
pytest
python -m compileall -q phyagentos_tui tests
```

Build distribution artifacts:

```bash
python -m pip install build
python -m build
```

## Repository Layout

```text
phyagentos_tui/
  app.py                  # Textual application and navigation
  styles.tcss             # TUI layout and visual styling
  themes.py               # Theme registry
  screens/                # Chat, providers, channels, settings, runtime
  services/               # In-process gateway lifecycle integration
  widgets/                # Shared Textual widgets
tests/                    # Smoke tests and UI import checks
```

## Compatibility

This package currently tracks the PhyAgentOS core `dev` branch. Compatibility
should be tested whenever core changes any of these surfaces:

- `PhyAgentOS.config`
- `PhyAgentOS.cli.commands._make_provider`
- `PhyAgentOS.cli.commands._make_forge_components`
- `PhyAgentOS.bus`
- provider registry and channel registry APIs
- Forge AgentTask storage schema

## Security And Privacy

The Runtime page displays workspace-relative or redacted path labels for local
storage. It should not expose absolute home-directory paths, usernames, API
keys, or provider secrets.

Provider API keys are entered through password fields and stored through the
PhyAgentOS core configuration writer. Follow the core security model for secret
storage and deployment controls.

## Contributing

Issues and pull requests are welcome. Keep UI changes aligned with the core
execution model: the TUI may inspect, configure, and route PhyAgentOS behavior,
but it should not create a second execution protocol beside the Forge Tool API.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development expectations.

## License

MIT License. See [LICENSE](LICENSE).
