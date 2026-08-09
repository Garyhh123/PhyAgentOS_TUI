"""Runtime dashboard screen for PhyAgentOS TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block
from PhyAgentOS.tui.widgets.app_header import AppHeader
from PhyAgentOS.tui.widgets.section_title import SectionTitle


class RuntimeDashboardScreen(Screen):
    """Read-only dashboard for runtime targets, sessions, and recent state."""

    BINDINGS = [
        Binding("r", "runtime_refresh", "Refresh"),
        Binding("/", "runtime_search", "Search"),
        Binding("e", "toggle_errors", "Errors"),
        Binding("a", "toggle_active", "Active"),
        Binding("t", "toggle_target_filter", "Target"),
        Binding("y", "copy_runtime_detail", "Copy Detail"),
        Binding("?", "runtime_help", "Help"),
    ]

    FAILURE_STATUSES = {"failed", "rejected", "timed_out"}
    ACTIVE_STATUSES = {"pending", "claimed", "running", "executing", "in_progress"}

    def __init__(self) -> None:
        super().__init__()
        self._targets: list[dict[str, Any]] = []
        self._sessions: list[dict[str, Any]] = []
        self._skillruntimes: list[dict[str, Any]] = []
        self._documents: dict[str, dict[str, Any] | str] = {}
        self._search_query = ""
        self._session_filter = "all"
        self._target_filter: str | None = None
        self._selected_row_key: str | None = None
        self._current_detail_raw = ""

    def compose(self) -> ComposeResult:
        yield AppHeader()
        with Vertical(id="runtime-main"):
            yield SectionTitle("Runtime Dashboard")
            with Horizontal(id="runtime-toolbar"):
                yield Label(
                    "r refresh | / search | e errors | a active | t target | y copy | ? help",
                    classes="hint",
                )
                yield Button("Refresh", id="runtime-refresh", variant="primary")
            search_input = Input(placeholder="Search targets and sessions...", id="runtime-search")
            search_input.display = False
            yield search_input
            with Horizontal(id="runtime-body"):
                with Vertical(id="runtime-left"):
                    yield SectionTitle("Overview")
                    yield Static("", id="runtime-overview")
                    yield SectionTitle("Targets")
                    yield DataTable(id="runtime-targets")
                with Vertical(id="runtime-middle"):
                    yield SectionTitle("Sessions")
                    yield DataTable(id="runtime-sessions")
                with ScrollableContainer(id="runtime-detail-wrap"):
                    yield SectionTitle("Details")
                    yield Static("Select a target or session.", id="runtime-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dashboard()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "runtime-refresh":
            self.refresh_dashboard()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "runtime-search":
            return
        self._search_query = event.value.strip().lower()
        self._refresh_targets_table()
        self._refresh_sessions_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "runtime-search":
            return
        event.input.display = False
        self._search_query = event.value.strip().lower()
        self._refresh_targets_table()
        self._refresh_sessions_table()

    def action_runtime_refresh(self) -> None:
        self.refresh_dashboard()
        self.notify("Runtime dashboard refreshed")

    def action_runtime_search(self) -> None:
        search = self.query_one("#runtime-search", Input)
        search.display = True
        search.value = self._search_query
        search.focus()

    def action_toggle_errors(self) -> None:
        self._session_filter = "all" if self._session_filter == "errors" else "errors"
        self._refresh_sessions_table()
        self.notify(f"Session filter: {self._session_filter}")

    def action_toggle_active(self) -> None:
        self._session_filter = "all" if self._session_filter == "active" else "active"
        self._refresh_sessions_table()
        self.notify(f"Session filter: {self._session_filter}")

    def action_toggle_target_filter(self) -> None:
        target_id = self._target_id_from_selection()
        if target_id is None:
            if self._target_filter:
                self._target_filter = None
                self._refresh_sessions_table()
                self.notify("Target filter cleared")
            else:
                self.notify("Select a target or session first", severity="warning")
            return

        self._target_filter = None if self._target_filter == target_id else target_id
        self._refresh_sessions_table()
        self.notify(f"Target filter: {self._target_filter or 'all'}")

    def action_copy_runtime_detail(self) -> None:
        text = self._current_detail_raw or str(self.query_one("#runtime-detail", Static).renderable)
        if not text.strip():
            self.notify("No detail to copy", severity="warning")
            return
        self.app.copy_to_clipboard(text)
        self.notify("Runtime detail copied")

    def action_runtime_help(self) -> None:
        self._current_detail_raw = ""
        self.query_one("#runtime-detail", Static).update(
            "Keyboard\n\n"
            "r: refresh runtime documents\n"
            "/: search targets and sessions\n"
            "e: toggle failed/rejected/timed_out sessions\n"
            "a: toggle active sessions\n"
            "t: filter sessions by selected target\n"
            "y: copy the current raw detail\n"
            "Enter: inspect selected table row\n"
            "Esc: return to chat"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        self._selected_row_key = key
        detail = self.query_one("#runtime-detail", Static)
        if key.startswith("target:"):
            target_id = key.removeprefix("target:")
            target = next((item for item in self._targets if item.get("id") == target_id), None)
            data = target or {"id": target_id, "error": "not found"}
            self._current_detail_raw = yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
            ).rstrip()
            detail.update(self._format_target_detail(data))
        elif key.startswith("session:"):
            session_id = key.removeprefix("session:")
            session = next(
                (item for item in self._sessions if item.get("session_id") == session_id),
                None,
            )
            data = session or {"session_id": session_id, "error": "not found"}
            self._current_detail_raw = yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
            ).rstrip()
            detail.update(self._format_session_detail(data))

    def refresh_dashboard(self) -> None:
        workspace = self.app.config.runtime_workspace_path
        self._documents = {
            "targets": self._read_runtime_doc(workspace / "TARGETS.md"),
            "skillruntimes": self._read_runtime_doc(workspace / "SKILLRUNTIME.md"),
            "sessions": self._read_runtime_doc(workspace / "SESSIONS.md"),
            "environment": self._read_text_doc(workspace / "ENVIRONMENT.md"),
            "lessons": self._read_text_doc(workspace / "LESSONS.md"),
        }

        targets_doc = self._documents["targets"]
        sessions_doc = self._documents["sessions"]
        skillruntimes_doc = self._documents["skillruntimes"]
        self._targets = targets_doc.get("targets", []) if isinstance(targets_doc, dict) else []
        self._sessions = sessions_doc.get("sessions", []) if isinstance(sessions_doc, dict) else []
        self._skillruntimes = (
            skillruntimes_doc.get("skillruntimes", [])
            if isinstance(skillruntimes_doc, dict)
            else []
        )

        self._refresh_overview(workspace)
        self._refresh_targets_table()
        self._refresh_sessions_table()
        self._refresh_default_detail()

    def _refresh_overview(self, workspace: Path) -> None:
        gateway = getattr(self.app, "_gateway_service", None)
        if gateway is None:
            gateway_status = "not initialized"
        elif gateway.error:
            gateway_status = f"error: {gateway.error}"
        elif gateway.is_running:
            gateway_status = "running"
        else:
            gateway_status = "starting"

        self.query_one("#runtime-overview", Static).update(
            f"Workspace: {workspace}\n"
            f"Gateway: {gateway_status}\n"
            f"Runtime: {'enabled' if self.app.config.runtime.enabled else 'disabled'}\n"
            f"Docs: {self._docs_overview()}\n"
            f"Targets: {self._target_overview()}\n"
            f"Skill runtimes: {self._skillruntime_overview()}\n"
            f"Sessions: {self._session_overview()}\n"
            f"Queue: {self._queue_overview()}\n"
            f"Last update: {self._last_session_overview()}\n"
            f"Last failure: {self._last_failure_overview()}"
        )

    def _docs_overview(self) -> str:
        labels = {
            "targets": "TARGETS",
            "skillruntimes": "SKILLRUNTIME",
            "sessions": "SESSIONS",
            "environment": "ENVIRONMENT",
            "lessons": "LESSONS",
        }
        parts: list[str] = []
        for key, label in labels.items():
            value = self._documents.get(key)
            if isinstance(value, dict):
                parts.append(f"{label}=ok")
            elif isinstance(value, str) and value.startswith("missing:"):
                parts.append(f"{label}=missing")
            elif key in {"environment", "lessons"} and isinstance(value, str) and value:
                parts.append(f"{label}=text")
            elif isinstance(value, str) and value:
                parts.append(f"{label}=error")
            else:
                parts.append(f"{label}=empty")
        return ", ".join(parts)

    def _target_overview(self) -> str:
        total = len(self._targets)
        if total == 0:
            source = self._documents.get("targets")
            return str(source) if isinstance(source, str) else "0 targets"

        enabled = sum(1 for item in self._targets if item.get("enabled", True))
        disabled = total - enabled
        kind_counts: dict[str, int] = {}
        class_counts: dict[str, int] = {}
        for target in self._targets:
            kind = str(target.get("target_kind") or "unknown")
            target_class = str(target.get("target_class") or "unknown")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            class_counts[target_class] = class_counts.get(target_class, 0) + 1

        parts = [f"{enabled}/{total} enabled"]
        if disabled:
            parts.append(f"{disabled} disabled")
        if kind_counts:
            parts.append(self._format_counts(kind_counts))
        if class_counts:
            parts.append(self._format_counts(class_counts))
        return "; ".join(parts)

    def _skillruntime_overview(self) -> str:
        total = len(self._skillruntimes)
        if total == 0:
            source = self._documents.get("skillruntimes")
            return str(source) if isinstance(source, str) else "0 skill runtimes"

        kind_counts: dict[str, int] = {}
        exposure_counts: dict[str, int] = {}
        for skillruntime in self._skillruntimes:
            runtime_kind = str(skillruntime.get("runtime_kind") or "unknown")
            exposure = str(skillruntime.get("agent_exposure") or "unknown")
            kind_counts[runtime_kind] = kind_counts.get(runtime_kind, 0) + 1
            exposure_counts[exposure] = exposure_counts.get(exposure, 0) + 1

        parts = [f"{total} total"]
        if kind_counts:
            parts.append(self._format_counts(kind_counts))
        if exposure_counts:
            parts.append(f"exposure: {self._format_counts(exposure_counts)}")
        return "; ".join(parts)

    def _session_overview(self) -> str:
        total = len(self._sessions)
        if total == 0:
            source = self._documents.get("sessions")
            return str(source) if isinstance(source, str) else "0 sessions"

        status_counts: dict[str, int] = {}
        error_counts: dict[str, int] = {}
        for session in self._sessions:
            status = str(session.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
            error_code = result.get("error_code")
            if error_code:
                error = str(error_code)
                error_counts[error] = error_counts.get(error, 0) + 1

        parts = [f"{total} total", self._format_counts(status_counts)]
        if error_counts:
            parts.append(f"errors: {self._format_counts(error_counts)}")
        return "; ".join(part for part in parts if part)

    def _queue_overview(self) -> str:
        active = [
            session
            for session in self._sessions
            if str(session.get("status") or "").lower() in self.ACTIVE_STATUSES
        ]
        if not active:
            return "idle"

        by_status: dict[str, int] = {}
        for session in active:
            status = str(session.get("status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        return f"{len(active)} active ({self._format_counts(by_status)})"

    def _last_session_overview(self) -> str:
        session = self._latest_session()
        if not session:
            return "none"
        session_id = str(session.get("session_id") or "unknown")
        status = str(session.get("status") or "unknown")
        target = self._short_target_ref(session.get("target_ref"))
        updated_at = str(session.get("updated_at") or "no timestamp")
        return f"{session_id} ({status}) on {target} at {updated_at}"

    def _last_failure_overview(self) -> str:
        session = self._recent_session_error()
        if not session:
            return "none"

        result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
        error_code = str(result.get("error_code") or session.get("status") or "failure")
        session_id = str(session.get("session_id") or "unknown")
        target = self._short_target_ref(session.get("target_ref"))
        updated_at = str(session.get("updated_at") or "no timestamp")
        return f"{error_code} in {session_id} on {target} at {updated_at}"

    def _filtered_targets(self) -> list[dict[str, Any]]:
        return [target for target in self._targets if self._matches_search(target)]

    def _filtered_sessions(self) -> list[dict[str, Any]]:
        return [
            session
            for session in self._sessions
            if self._session_matches_filter(session)
            and self._session_matches_target_filter(session)
            and self._matches_search(session)
        ]

    def _session_matches_filter(self, session: dict[str, Any]) -> bool:
        status = str(session.get("status") or "").lower()
        result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
        if self._session_filter == "errors":
            return bool(
                result.get("error_code")
                or result.get("error_message")
                or status in self.FAILURE_STATUSES
            )
        if self._session_filter == "active":
            return status in self.ACTIVE_STATUSES
        return True

    def _session_matches_target_filter(self, session: dict[str, Any]) -> bool:
        return self._target_filter is None or self._session_target_id(session) == self._target_filter

    def _matches_search(self, data: dict[str, Any]) -> bool:
        if not self._search_query:
            return True
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).lower()
        return self._search_query in text

    def _target_id_from_selection(self) -> str | None:
        if not self._selected_row_key:
            return None
        if self._selected_row_key.startswith("target:"):
            return self._selected_row_key.removeprefix("target:")
        if self._selected_row_key.startswith("session:"):
            session_id = self._selected_row_key.removeprefix("session:")
            session = next((item for item in self._sessions if item.get("session_id") == session_id), None)
            if session:
                return self._session_target_id(session)
        return None

    def _session_target_id(self, session: dict[str, Any]) -> str:
        return self._short_target_ref(session.get("target_ref"))

    def _refresh_targets_table(self) -> None:
        table = self.query_one("#runtime-targets", DataTable)
        table.clear(columns=True)
        table.add_columns("Target", "Kind", "Enabled", "Runtime")
        table.cursor_type = "row"
        targets = self._filtered_targets()
        for target in targets:
            runtime = target.get("runtime", {}) if isinstance(target.get("runtime"), dict) else {}
            table.add_row(
                str(target.get("id", "")),
                str(target.get("target_kind", "")),
                "yes" if target.get("enabled", True) else "no",
                str(runtime.get("target_runtime", "")),
                key=f"target:{target.get('id', '')}",
            )
        if not targets:
            table.add_row("No matching targets", "", "", "", key="empty:targets")

    def _refresh_sessions_table(self) -> None:
        table = self.query_one("#runtime-sessions", DataTable)
        table.clear(columns=True)
        table.add_columns("Session", "Status", "Target", "Result")
        table.cursor_type = "row"
        sessions = self._filtered_sessions()
        for session in sessions:
            result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
            result_text = str(result.get("error_code") or result.get("status") or "")
            table.add_row(
                str(session.get("session_id", "")),
                str(session.get("status", "")),
                str(session.get("target_ref", "")),
                result_text,
                key=f"session:{session.get('session_id', '')}",
            )
        if not sessions:
            table.add_row("No matching sessions", "", "", "", key="empty:sessions")

    def _refresh_default_detail(self) -> None:
        detail = self.query_one("#runtime-detail", Static)
        recent_error = self._recent_session_error()
        if recent_error:
            self._current_detail_raw = yaml.safe_dump(
                recent_error,
                allow_unicode=True,
                sort_keys=False,
            ).rstrip()
            detail.update(self._format_session_detail(recent_error))
        else:
            self._current_detail_raw = ""
            detail.update("Select a target or session to inspect its full YAML.")

    def _recent_session_error(self) -> dict[str, Any] | None:
        for session in reversed(self._sessions):
            result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
            status = str(session.get("status") or "").lower()
            if result.get("error_code") or result.get("error_message") or status in self.FAILURE_STATUSES:
                return session
        return None

    def _latest_session(self) -> dict[str, Any] | None:
        if not self._sessions:
            return None
        dated_sessions = [session for session in self._sessions if session.get("updated_at")]
        if dated_sessions:
            return max(dated_sessions, key=lambda session: str(session.get("updated_at") or ""))
        return self._sessions[-1]

    @staticmethod
    def _format_counts(counts: dict[str, int]) -> str:
        return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"

    @staticmethod
    def _short_target_ref(target_ref: Any) -> str:
        text = str(target_ref or "unknown")
        if text.startswith("target://"):
            return text.removeprefix("target://")
        return text

    @staticmethod
    def _short_skillruntime_ref(skillruntime_ref: Any) -> str:
        text = str(skillruntime_ref or "unknown")
        if text.startswith("skillruntime://"):
            return text.removeprefix("skillruntime://")
        return text

    @staticmethod
    def _read_runtime_doc(path: Path) -> dict[str, Any] | str:
        if not path.exists():
            return f"missing: {path}"
        try:
            return read_yaml_block(path)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _read_text_doc(path: Path) -> str:
        if not path.exists():
            return f"missing: {path}"
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    def _format_target_detail(self, target: dict[str, Any]) -> str:
        runtime = target.get("runtime", {}) if isinstance(target.get("runtime"), dict) else {}
        observation = target.get("observation", {}) if isinstance(target.get("observation"), dict) else {}
        perception = target.get("perception", {}) if isinstance(target.get("perception"), dict) else {}
        skillruntimes = target.get("supported_skillruntimes", [])
        if isinstance(skillruntimes, list):
            skillruntime_text = ", ".join(str(item) for item in skillruntimes) or "none"
        else:
            skillruntime_text = self._brief_value(skillruntimes)

        summary = [
            "Summary",
            "",
            f"Target: {target.get('id', 'unknown')}",
            f"Kind: {target.get('target_kind', 'unknown')}",
            f"Class: {target.get('target_class', 'unknown')}",
            f"Enabled: {'yes' if target.get('enabled', True) else 'no'}",
            f"Workspace: {target.get('workspace', 'unknown')}",
            f"Skillruntimes: {skillruntime_text}",
        ]
        if target.get("error"):
            summary.append(f"Error: {target.get('error')}")

        runtime_lines = [
            "Runtime",
            "",
            f"Runtime: {runtime.get('target_runtime', 'unknown')}",
            f"Endpoint: {runtime.get('target_endpoint', 'none')}",
            f"Adapter: {runtime.get('target_adapter', 'unknown')}",
            f"Contract: {runtime.get('runtime_contract_ref', 'unknown')}",
        ]

        observation_lines = [
            "Observation",
            "",
            f"Type: {observation.get('observation_type', 'unknown')}",
            f"Empty allowed: {observation.get('empty_observation_allowed', 'unknown')}",
            f"Perception: {'enabled' if perception.get('enabled') else 'disabled'}",
            f"Strict preflight: {perception.get('strict_preflight', 'unknown')}",
        ]

        raw_yaml = yaml.safe_dump(target, allow_unicode=True, sort_keys=False).rstrip()
        return self._join_detail_sections(
            summary,
            runtime_lines,
            observation_lines,
            ["Raw YAML", "", raw_yaml],
        )

    def _format_session_detail(self, session: dict[str, Any]) -> str:
        result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
        error_code = result.get("error_code")
        error_message = result.get("error_message") or session.get("error")
        explanation = self._explain_error(str(error_code or ""))
        summary = [
            "Summary",
            "",
            f"Session: {session.get('session_id', '')}",
            f"Status: {session.get('status', '')}",
            f"Target: {self._short_target_ref(session.get('target_ref'))}",
            f"Skillruntime: {self._short_skillruntime_ref(session.get('skillruntime_ref'))}",
        ]
        if session.get("task_description"):
            summary.append(f"Task: {session.get('task_description')}")
        if session.get("updated_at"):
            summary.append(f"Updated: {session.get('updated_at')}")
        if error_code:
            summary.append(f"Error: {error_code}")
        if error_message:
            summary.append(f"Message: {error_message}")
        if explanation:
            summary.append(f"Hint: {explanation}")

        raw_yaml = yaml.safe_dump(session, allow_unicode=True, sort_keys=False).rstrip()
        return self._join_detail_sections(
            summary,
            self._format_result_section(result),
            ["Raw YAML", "", raw_yaml],
        )

    def _format_result_section(self, result: dict[str, Any]) -> list[str]:
        lines = ["Result", ""]
        if not result:
            lines.append("no result data")
            return lines

        for label, key in (
            ("status", "status"),
            ("success", "success"),
            ("error_message", "error_message"),
            ("duration", "duration_s"),
            ("duration", "duration_ms"),
            ("steps", "num_steps"),
            ("return_value", "return_value"),
            ("artifact_dir", "artifact_dir"),
        ):
            if key in result:
                lines.append(f"{label}: {self._brief_value(result.get(key))}")

        output = self._result_output(result)
        if output:
            lines.append(f"output: {output}")
        if len(lines) == 2:
            lines.append("no summary fields")
        return lines

    @staticmethod
    def _join_detail_sections(*sections: list[str]) -> str:
        return "\n\n".join(
            "\n".join(line for line in section if line is not None).rstrip()
            for section in sections
        )

    @staticmethod
    def _brief_value(value: Any) -> str:
        if value is None:
            return "none"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list)):
            return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip().replace("\n", " ")
        return str(value)

    @staticmethod
    def _result_output(result: dict[str, Any]) -> str:
        for key in ("output", "message", "return_value"):
            if result.get(key) is not None:
                return RuntimeDashboardScreen._brief_value(result.get(key))

        metadata = result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {}
        for key in ("output", "message", "return_value"):
            if metadata.get(key) is not None:
                return RuntimeDashboardScreen._brief_value(metadata.get(key))
        return ""

    @staticmethod
    def _explain_error(error_code: str) -> str:
        explanations = {
            "TARGET_PROTOCOL": "TargetWS response type or payload does not match the runtime RPC contract.",
            "SCHEMA_VALIDATION": "A runtime protocol file or config YAML does not match the expected schema.",
            "RUNTIME_PREFLIGHT_FAILED": "Target, skillruntime, adapter, sensor, or action contract failed preflight.",
            "COMMAND_STEP": "A builtin target tool step returned success=false.",
            "EXECUTION_TIMEOUT": "The session exceeded execute_timeout_s.",
            "VERIFICATION_SERVICE_UNAVAILABLE": "Audit/recovery verification needs the Agent verification service.",
        }
        return explanations.get(error_code, "")
