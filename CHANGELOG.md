# Changelog

All notable changes to PhyAgentOS TUI are documented in this file.

The format follows the spirit of Keep a Changelog, and this project uses
semantic versioning once published as a standalone package.

## [0.1.0] - 2026-09-01

### Added

- Initial standalone `phyagentos-tui` package.
- Textual application shell with Chat, Providers, Channels, Settings, and Forge
  Runtime pages.
- `paos-tui` console script and `python -m phyagentos_tui` module entry point.
- In-process PhyAgentOS gateway lifecycle integration.
- Runtime dashboard for read-only AgentTask, Skill Runtime, artifact, storage,
  and health inspection.
- Workspace-relative path display for runtime storage surfaces.

### Changed

- Removed demo playback scripts from the standalone TUI package.
- Moved TUI-owned imports under the `phyagentos_tui` package namespace.

### Notes

- The package currently tracks `PhyAgentOS-ai` from the core `dev` branch until
  a matching released dependency is available.
