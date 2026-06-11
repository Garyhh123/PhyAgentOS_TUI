"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PhyAgentOS.agent.memory import MemoryStore
from PhyAgentOS.agent.skills import SkillsLoader
from PhyAgentOS.utils.helpers import build_assistant_message, detect_image_mime


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    # Core nanobot files — always loaded
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "SKILLS.md"]

    # Embodied extension files — loaded only when present in workspace.
    # New tracks can add files here without touching other code.
    EMBODIED_FILES = [
        "EMBODIED.md", "ENVIRONMENT.md", "LESSONS.md",
        "TASK.md", "ORCHESTRATOR.md",
        "RUNTIME.md",
        "MEMORY_SPATIAL.md", "TIMELINE.md",
    ]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    _EMBODIED_TARGET_RE = re.compile(r"^##\s+Target:\s*(?P<target_id>[A-Za-z0-9_.:-]+)\s*$")

    def __init__(
        self,
        workspace: Path,
        *,
        runtime_workspace: Path | None = None,
        runtime_enabled: bool = True,
        runtime_target_enabled: dict[str, bool] | None = None,
    ):
        self.workspace = workspace
        self.runtime_workspace = runtime_workspace or workspace
        self.runtime_enabled = runtime_enabled
        self.runtime_target_enabled = dict(runtime_target_enabled or {})
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(
            workspace,
            runtime_enabled=runtime_enabled,
            runtime_target_enabled=self.runtime_target_enabled,
        )

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        platform_policy = ""
        if system == "Windows":
            platform_policy = """## Platform Policy (Windows)
- You are running on Windows. Do not assume GNU tools like `grep`, `sed`, or `awk` exist.
- Prefer Windows-native commands or file tools when they are more reliable.
- If terminal output is garbled, retry with UTF-8 output enabled.
"""
        else:
            platform_policy = """## Platform Policy (POSIX)
- You are running on a POSIX system. Prefer UTF-8 and standard shell tools.
- Use file tools when they are simpler or more reliable than shell commands.
"""

        return f"""# PhyAgentOS 🍞

You are PhyAgentOS, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

{platform_policy}

## PhyAgentOS Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

## Runtime Protocol — MANDATORY

The ONLY way to interact with runtime targets (robots, game agents, simulators) is
through the session protocol.  There are NO shortcuts.

| Rule | Description |
|------|-------------|
| **SESSIONS.md only** | Write sessions with `write_file` to `SESSIONS.md`. Never use `exec`, `curl`, `http`, or any other tool to call target APIs directly. |
| **Read before write** | Read `RUNTIME.md`, `TARGETS.md`, and `SKILLRUNTIME.md` before writing to `SESSIONS.md`. |
| **Verify before claim** | After the watchdog executes, `read_file ENVIRONMENT.md` to verify the result. Never claim success or failure without reading ENVIRONMENT.md first. |
| **YAML correctness** | Use `write_file` (not `edit_file`) for `SESSIONS.md` to preserve YAML structure. |

## Task Persistence & Reflection (Self-Evolution)

When you execute tasks through the runtime (via SESSIONS.md), follow this cycle:

1. **Plan** — read RUNTIME.md + TARGETS.md, then use `write_file` to append a session to SESSIONS.md with appropriate perception_queries.
2. **Wait** — the watchdog daemon picks up pending sessions automatically. You do NOT need to run any commands.
3. **Check** — after the watchdog executes (wait a few seconds), `read_file ENVIRONMENT.md` to see the actual result. Also read LESSONS.md.
4. **Reflect** — did it succeed or fail? What does ENVIRONMENT.md actually say?
   - If it failed: what error code, what error message, what likely caused it?
   - What alternative approach would work better?
5. **Learn** — use `edit_file` to append a structured lesson to LESSONS.md:
   - Task, Strategy, Outcome (from ENVIRONMENT.md), Insight, Escalation plan.
6. **Retry** (max 3 same-approach attempts) — if not done, write a new session with adjusted strategy.
7. **Escalate** — if the same approach fails 3 times, switch to a fundamentally different one.
   Example: `collect` fails → try `dig` + `move`; absolute `move` times out → try short relative `move`.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace.

        Core files (BOOTSTRAP_FILES) are always loaded.  Embodied extension
        files (EMBODIED_FILES) are loaded only when they exist, so new
        tracks can add protocol files without modifying this code.
        """
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        # Embodied extensions — present only when the workspace provides them.
        for filename in self.EMBODIED_FILES:
            file_path = self._context_file_path(filename)
            if file_path.exists():
                if filename == "EMBODIED.md":
                    content = self._load_enabled_embodied_content(file_path)
                    if not content:
                        continue
                else:
                    content = file_path.read_text(encoding="utf-8")
                if filename == "LESSONS.md":
                    content = self._format_lessons(content)
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _format_lessons(content: str) -> str:
        """If LESSONS.md has actual entries, prepend a prominent notice."""
        stripped = content.strip()
        if not stripped:
            return content
        lines = [line for line in stripped.splitlines() if line.strip() and not line.strip().startswith("#")]
        if len(lines) < 2:
            return content
        return (
            "**Read these lessons before planning — they describe what failed before "
            "and what worked. Apply them to avoid repeating past mistakes.**\n\n"
            + stripped
        )

    def _context_file_path(self, filename: str) -> Path:
        """Return the context-visible source path for a protocol file."""
        if self.runtime_enabled and filename in {"EMBODIED.md", "RUNTIME.md"}:
            runtime_path = self.runtime_workspace / filename
            if runtime_path.exists():
                return runtime_path
        return self.workspace / filename

    def _load_enabled_embodied_content(self, path: Path) -> str:
        """Load target capability prose only for targets enabled in TARGETS.md/config."""
        if not self.runtime_enabled:
            return ""
        content = path.read_text(encoding="utf-8")
        enabled_targets = self._enabled_runtime_target_ids()
        if enabled_targets is None:
            return content
        if not enabled_targets:
            return ""
        return self._filter_embodied_targets(content, enabled_targets)

    def _enabled_runtime_target_ids(self) -> set[str] | None:
        targets_path = self.runtime_workspace / "TARGETS.md"
        if not targets_path.exists():
            targets_path = self.workspace / "TARGETS.md"
        if not targets_path.exists():
            return None
        try:
            from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block

            document = read_yaml_block(targets_path)
        except Exception:
            return None
        targets = document.get("targets")
        if not isinstance(targets, list):
            return None

        enabled: set[str] = set()
        for target in targets:
            if not isinstance(target, dict):
                continue
            target_id = target.get("id")
            if not isinstance(target_id, str):
                continue
            is_enabled = bool(target.get("enabled", True))
            if target_id in self.runtime_target_enabled:
                is_enabled = bool(self.runtime_target_enabled[target_id])
            if is_enabled:
                enabled.add(target_id)
        return enabled

    @classmethod
    def _filter_embodied_targets(cls, content: str, enabled_targets: set[str]) -> str:
        lines = content.splitlines()
        preamble: list[str] = []
        sections: list[list[str]] = []
        current: list[str] | None = None
        current_target: str | None = None
        saw_target_section = False

        for line in lines:
            match = cls._EMBODIED_TARGET_RE.match(line)
            if match:
                saw_target_section = True
                if current is not None and current_target in enabled_targets:
                    sections.append(current)
                current_target = match.group("target_id")
                current = [line]
                continue
            if current is None:
                preamble.append(line)
            else:
                current.append(line)

        if current is not None and current_target in enabled_targets:
            sections.append(current)

        if not saw_target_section:
            return content
        if not sections:
            return ""

        output: list[str] = []
        if preamble:
            output.extend(preamble)
            while output and not output[-1].strip():
                output.pop()
            output.append("")
        for section in sections:
            output.extend(section)
            output.append("")
        while output and not output[-1].strip():
            output.pop()
        return "\n".join(output) + "\n"

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": merged},
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # Detect real MIME type from magic bytes; fallback to filename guess
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_system_continue(
        self, messages: list[dict[str, Any]],
        continuation_text: str,
    ) -> list[dict[str, Any]]:
        """Inject a continuation prompt as a system-notification user message."""
        messages.append({
            "role": "user",
            "content": f"[System — {continuation_text}",
        })
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages
