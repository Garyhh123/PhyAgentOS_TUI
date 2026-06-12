"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from PhyAgentOS.agent.memory import MemoryStore
from PhyAgentOS.agent.skills import SkillsLoader
from PhyAgentOS.utils.helpers import build_assistant_message, detect_image_mime

_YAML_BLOCK_RE = re.compile(
    r"(?P<fence>`{3,}|~{3,})\s*yaml\s*\n(?P<body>.*?)(?:\n(?P=fence)\s*)",
    re.DOTALL | re.IGNORECASE,
)


def _parse_lessons_yaml(content: str) -> list | None:
    """Extract the lessons list from a LESSONS.md YAML block. Returns None on failure."""
    match = _YAML_BLOCK_RE.search(content)
    if not match:
        return None
    try:
        payload = yaml.safe_load(match.group("body"))
        if not isinstance(payload, dict):
            return None
        lessons = payload.get("lessons")
        if not isinstance(lessons, list):
            return None
        return lessons
    except Exception:
        return None


def _filter_recent_and_successful(
    lessons: list,
    max_items: int = 25,
    recent_count: int = 15,
) -> tuple[list, int]:
    """Filter lessons: keep most recent + succeeded entries, dedup by session_id.

    Returns (filtered_lessons, original_count).
    """
    # Dedup: keep newest entry per session_id
    seen_sessions: set[str] = set()
    deduped: list[dict] = []
    for lesson in reversed(lessons):
        sid = lesson.get("session_id", "")
        if sid and sid in seen_sessions:
            continue
        if sid:
            seen_sessions.add(sid)
        deduped.append(lesson)
    deduped.reverse()

    recent = deduped[-recent_count:] if len(deduped) > recent_count else list(deduped)

    recent_ids = {item.get("session_id") for item in recent}
    succeeded: list[dict] = []
    for lesson in reversed(deduped):
        if len(recent) + len(succeeded) >= max_items:
            break
        sid = lesson.get("session_id", "")
        if sid in recent_ids:
            continue
        metadata = lesson.get("metadata") or {}
        summary = lesson.get("summary", "")
        if metadata.get("success") or "succeeded" in str(summary):
            succeeded.append(lesson)
            recent_ids.add(sid)
    succeeded.reverse()

    filtered = recent + succeeded
    return filtered[:max_items], len(lessons)


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
        self._prompt_cache: tuple[str, float] | None = None

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills.

        Cached based on file mtimes — refresh only when workspace files change
        or the memory/skills state is stale (ttl = 5s to catch memory updates).
        """
        now = time.time()
        if self._prompt_cache is not None:
            cached, ts = self._prompt_cache
            if now - ts < 5.0:
                return cached

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

        prompt = "\n\n---\n\n".join(parts)
        self._prompt_cache = (prompt, now)
        return prompt

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
8. **Abstract** — after the task is done (or definitively failed), distill the key
   lesson into an abstract, game-agnostic principle. Write it to `memory/MEMORY.md`
   using `edit_file`. Use format:
   ```
   ## [Category Name]

   [Game] Specific observation. Why it matters. How to handle it.
   Pattern: abstract rule that applies across games.
   ```
   Tag each entry with `[Minecraft]`, `[Stardew]`, or `[Cross-game]` so it's clear
   where the lesson came from. Cross-game principles help future tasks in ANY game.
9. **Convert to Skill** — when a pattern has been proven in ≥2 successful sessions
   in the same game, promote it from MEMORY.md into a reusable `skills/` guide.
   Use the `skill-creator` skill (`read_file skills/skill-creator/SKILL.md`)
   to generate `skills/<skill-name>/SKILL.md`. A pattern should become a skill when:
   - It describes a reproducible *methodology or workflow* (not just a fact)
   - Multiple attempts confirm it works reliably
   - It would save significant time if the next agent reads it before acting
   Example: cave escape via dy-climbing was confirmed twice → create `minecraft-navigation` skill.
   Skills override MEMORY.md principles because they are more actionable and structured.

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

    _LESSONS_NOTICE = (
        "**Read these lessons before planning — they describe what failed before "
        "and what worked. Apply them to avoid repeating past mistakes.**\n\n"
    )

    @staticmethod
    def _format_lessons(content: str) -> str:
        """Filter LESSONS.md to ≤25 entries and prepend a prominent notice."""
        stripped = content.strip()
        if not stripped:
            return content

        lessons = _parse_lessons_yaml(stripped)
        if lessons is None:
            # YAML parse failed — fall back to original heuristic
            lines = [
                line
                for line in stripped.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if len(lines) < 2:
                return content
            return ContextBuilder._LESSONS_NOTICE + stripped

        if not lessons:
            return content

        filtered, orig_count = _filter_recent_and_successful(lessons)

        if len(filtered) >= orig_count:
            return ContextBuilder._LESSONS_NOTICE + stripped

        # Rebuild content with filtered YAML block
        filtered_yaml = yaml.dump(
            {
                "version": "runtime_lessons_v1",
                "lessons": filtered,
            },
            sort_keys=False,
            allow_unicode=True,
        )

        def _replace_block(match: re.Match) -> str:
            return f"{match.group('fence')}yaml\n{filtered_yaml}\n{match.group('fence')}"

        new_content = _YAML_BLOCK_RE.sub(_replace_block, stripped)
        result = ContextBuilder._LESSONS_NOTICE + new_content
        if orig_count > len(filtered):
            result += (
                f"\n(+{orig_count - len(filtered)} older lessons, "
                "use read_file to view LESSONS.md)"
            )
        return result

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
        """Build the complete message list for an LLM call.

        Runtime context (time, channel) is injected as an interstitial
        system message before the user message, which avoids the need to
        strip it back out in _save_turn.
        """
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
        ]
        if runtime_ctx and runtime_ctx != self._RUNTIME_CONTEXT_TAG:
            messages.append({"role": "system", "content": runtime_ctx})
        messages.append({"role": "user", "content": user_content})
        return messages

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
