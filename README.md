# PhyAgentOS TUI

Standalone Terminal User Interface for PhyAgentOS.

This repository contains only the Textual-based TUI layer. The agent runtime,
configuration, providers, channels, Forge Tool API, Skill Runtime, and
AgentTask ledger remain in `PhyAgentOS-ai`.

## Local Development

From this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m phyagentos_tui
```

If you already use a local core repository virtual environment, you can run the
module from that environment:

```powershell
path\to\core\.venv\Scripts\python.exe -m phyagentos_tui
```

After editable install, the command is also available as:

```powershell
paos-tui
```

## Core Dependency

The current development dependency points to the upstream core `dev` branch:

```toml
PhyAgentOS-ai @ git+https://github.com/PhyAgentOS/PhyAgentOS-core.git@dev
```

Before publishing this package, replace that dependency with a released version
once the matching core release is available.

## Layout

```text
phyagentos_tui/
  app.py
  styles.tcss
  themes.py
  screens/
  services/
  widgets/
```

The TUI package imports `PhyAgentOS` for core behavior and imports
`phyagentos_tui` for its own screens, widgets, styles, and services.
