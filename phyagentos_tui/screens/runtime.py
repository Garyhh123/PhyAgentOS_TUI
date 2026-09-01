"""Forge runtime dashboard screen for the PhyAgentOS TUI."""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Label, Static

from phyagentos_tui.widgets.app_footer import AppFooter
from phyagentos_tui.widgets.app_header import AppHeader
from phyagentos_tui.widgets.command_palette import CommandPalette
from phyagentos_tui.widgets.nav_bar import NavBar
from phyagentos_tui.widgets.section_title import SectionTitle


class RuntimeDashboardScreen(Screen):
    """Read-only Forge dashboard for current dev architecture."""

    BINDINGS = [
        Binding("r", "runtime_refresh", "Refresh"),
        Binding("/", "runtime_search", "Search"),
        Binding("y", "copy_runtime_detail", "Copy Detail"),
        Binding("?", "runtime_help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._artifacts: list[dict[str, Any]] = []
        self._sessions: list[dict[str, Any]] = []
        self._skill_runs: list[dict[str, Any]] = []
        self._db_info: dict[str, Any] = {}
        self._health_issues: list[dict[str, str]] = []
        self._search_query = ""
        self._current_detail_raw = ""

    def compose(self) -> ComposeResult:
        yield AppHeader()
        yield NavBar("runtime")
        with Vertical(id="runtime-main"):
            yield SectionTitle("Forge Health")
            with Horizontal(id="runtime-toolbar"):
                yield Label(
                    "Forge runtime facts, sessions, evidence, and storage | r refresh | / search | y copy | ? help",
                    classes="hint",
                )
                yield Button("Refresh", id="runtime-refresh", variant="primary")
            search_input = Input(placeholder="Search sessions, skill runs, artifacts, and storage...", id="runtime-search")
            search_input.display = False
            yield search_input
            with Horizontal(id="runtime-body"):
                with Vertical(id="runtime-left"):
                    yield SectionTitle("Runtime Facts")
                    yield Static("", id="runtime-overview")
                    yield SectionTitle("Health Checks")
                    yield Static("", id="runtime-health")
                    yield SectionTitle("Storage")
                    yield DataTable(id="runtime-targets")
                with Vertical(id="runtime-middle"):
                    yield SectionTitle("Runtime Records")
                    yield DataTable(id="runtime-sessions")
                with ScrollableContainer(id="runtime-detail-wrap"):
                    yield SectionTitle("Details")
                    yield Static("Select a session, artifact, or storage row.", id="runtime-detail")
        yield CommandPalette()
        yield AppFooter()

    def on_mount(self) -> None:
        self.refresh_dashboard()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "runtime-refresh":
            self.refresh_dashboard()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "runtime-search":
            return
        self._search_query = event.value.strip().lower()
        self._refresh_storage_table()
        self._refresh_artifacts_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "runtime-search":
            return
        event.input.display = False
        self._search_query = event.value.strip().lower()
        self._refresh_storage_table()
        self._refresh_artifacts_table()

    def action_runtime_refresh(self) -> None:
        self.refresh_dashboard()
        self.notify("Forge runtime refreshed")

    def action_runtime_search(self) -> None:
        search = self.query_one("#runtime-search", Input)
        search.display = True
        search.value = self._search_query
        search.focus()

    def action_copy_runtime_detail(self) -> None:
        text = self._current_detail_raw or str(self.query_one("#runtime-detail", Static).render())
        if not text.strip():
            self.notify("No detail to copy", severity="warning")
            return
        self.app.copy_to_clipboard(text)
        self.notify("Runtime detail copied")

    def action_runtime_help(self) -> None:
        self._current_detail_raw = ""
        self.query_one("#runtime-detail", Static).update(
            "Keyboard\n\n"
            "r: refresh Forge runtime data\n"
            "/: search artifacts and storage rows\n"
            "y: copy the current raw detail\n"
            "Enter: inspect selected table row\n"
            "Ctrl+K: open command palette\n"
            "Esc: return to chat"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        detail = self.query_one("#runtime-detail", Static)
        if key.startswith("storage:"):
            name = key.removeprefix("storage:")
            data = self._storage_detail(name)
            sanitized = self._sanitize_display_data(data)
            self._current_detail_raw = yaml.safe_dump(sanitized, allow_unicode=True, sort_keys=False).rstrip()
            detail.update(self._format_detail("Storage", sanitized))
            return
        if key.startswith("session:"):
            session_id = key.removeprefix("session:")
            data = self._session_detail(session_id)
            sanitized = self._sanitize_display_data(data)
            self._current_detail_raw = yaml.safe_dump(sanitized, allow_unicode=True, sort_keys=False).rstrip()
            detail.update(self._format_detail("Session", sanitized))
            return
        if key.startswith("skillrun:"):
            run_id = key.removeprefix("skillrun:")
            data = self._skill_run_detail(run_id)
            sanitized = self._sanitize_display_data(data)
            self._current_detail_raw = yaml.safe_dump(sanitized, allow_unicode=True, sort_keys=False).rstrip()
            detail.update(self._format_detail("Skill Runtime Run", sanitized))
            return
        if key.startswith("artifact:"):
            artifact_id = key.removeprefix("artifact:")
            data = next((item for item in self._artifacts if item["id"] == artifact_id), None)
            if data is None:
                data = {"id": artifact_id, "error": "not found"}
            sanitized = self._sanitize_display_data(data)
            self._current_detail_raw = yaml.safe_dump(sanitized, allow_unicode=True, sort_keys=False).rstrip()
            detail.update(self._format_detail("Artifact", sanitized))

    def refresh_dashboard(self) -> None:
        self._db_info = self._read_db_info()
        self._artifacts = self._read_artifacts()
        self._sessions = self._read_sessions()
        self._skill_runs = self._read_skill_runs()
        self._health_issues = self._compute_health_issues()
        self._refresh_overview()
        self._refresh_health()
        self._refresh_storage_table()
        self._refresh_artifacts_table()
        self._refresh_default_detail()

    def _refresh_overview(self) -> None:
        config = self.app.config
        forge = config.forge
        gateway = getattr(self.app, "_gateway_service", None)
        if gateway is None:
            service_status = "not initialized"
        elif gateway.error:
            service_status = f"error: {gateway.error}"
        elif gateway.is_running:
            service_status = "running"
        else:
            service_status = "starting"

        db_path = self._db_path()
        artifact_dir = self._artifact_dir()
        self.query_one("#runtime-overview", Static).update(
            "Boundary: active Skill Runtime + AgentTask ledger\n"
            "Forge: Skill-bound Tool API\n"
            f"Gateway service: {service_status}\n"
            f"Request timeout: {forge.request_timeout_s:.1f}s\n"
            f"Poll interval: {forge.poll_interval_s:.1f}s\n"
            f"Evidence sources: {', '.join(forge.evidence.required_image_sources) or 'runtime discovery'}\n"
            f"AgentTasks: {len(self._sessions)} stored\n"
            f"Skill runs: {len(self._skill_runs)} stored\n"
            f"Artifacts: {len(self._artifacts)} task dirs\n"
            f"Workspace: {self._display_path(config.workspace_path)}\n"
            f"Store: {self._display_path(db_path) if db_path.exists() else 'missing'} | "
            f"{self._display_path(artifact_dir) if artifact_dir.exists() else 'missing'}"
        )

    def _refresh_health(self) -> None:
        if not self._health_issues:
            self.query_one("#runtime-health", Static).update("OK  Forge runtime looks healthy.")
            return
        lines = [
            f"{item['level']}  {item['message']}"
            for item in self._health_issues
        ]
        self.query_one("#runtime-health", Static).update("\n".join(lines))

    def _refresh_storage_table(self) -> None:
        table = self.query_one("#runtime-targets", DataTable)
        table.clear(columns=True)
        table.add_columns("Item", "Status", "Path")
        table.cursor_type = "row"
        for item in self._storage_rows():
            if self._search_query and self._search_query not in yaml.safe_dump(item).lower():
                continue
            table.add_row(item["name"], item["status"], item["path"], key=f"storage:{item['name']}")

    def _refresh_artifacts_table(self) -> None:
        table = self.query_one("#runtime-sessions", DataTable)
        table.clear(columns=True)
        table.add_columns("Type", "Identity", "Status", "Updated", "Artifacts")
        table.cursor_type = "row"
        rows = [item for item in self._session_artifact_rows() if self._matches_search(item)]
        for item in rows[:200]:
            if item["kind"] == "session":
                table.add_row(
                    "Session",
                    item["session_id"],
                    item["status"],
                    item["updated"],
                    item["evidence"],
                    key=f"session:{item['session_id']}",
                )
                continue
            if item["kind"] == "skill_run":
                table.add_row(
                    "SkillRun",
                    item["run_id"],
                    item["status"],
                    item["updated"],
                    item["evidence"],
                    key=f"skillrun:{item['run_id']}",
                )
                continue
            table.add_row(
                "Artifact",
                item["id"],
                item["status"],
                item["updated"],
                item["evidence"],
                key=f"artifact:{item['id']}",
            )
        if not rows:
            table.add_row("None", "No matching runtime records", "", "", "", key="artifact:empty")

    def _refresh_default_detail(self) -> None:
        detail = self.query_one("#runtime-detail", Static)
        latest = self._sessions[0] if self._sessions else None
        data: dict[str, Any] = self._sanitize_display_data({
            "workspace": self.app.config.workspace_path,
            "store": self._db_path(),
            "sessions": len(self._sessions),
            "skill_runs": len(self._skill_runs),
            "artifacts": len(self._artifacts),
            "health": self._health_issues or [{"level": "OK", "message": "Forge runtime looks healthy."}],
            "latest_session": (
                {
                    "session_id": latest["session_id"],
                    "status": latest["status"],
                    "action_type": latest["action_type"],
                    "verdict": latest["verdict"],
                    "updated": latest["updated"],
                }
                if latest
                else None
            ),
            "latest_skill_run": (
                {
                    "run_id": self._skill_runs[0]["run_id"],
                    "status": self._skill_runs[0]["status"],
                    "skill_name": self._skill_runs[0]["skill_name"],
                    "profile": self._skill_runs[0]["profile"],
                    "updated": self._skill_runs[0]["updated"],
                }
                if self._skill_runs
                else None
            ),
            "next_step": "Select a SkillRun row to inspect the sealed runtime assembly.",
        })
        self._current_detail_raw = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip()
        detail.update(self._format_detail("Forge Runtime", data))

    def _storage_rows(self) -> list[dict[str, str]]:
        db_path = self._db_path()
        artifact_dir = self._artifact_dir()
        return [
            {
                "name": "forge_database",
                "status": "OK" if db_path.exists() and not self._db_info.get("error") else "ERROR" if self._db_info.get("error") else "WARN",
                "path": self._display_path(db_path),
            },
            {
                "name": "forge_artifacts",
                "status": "OK" if artifact_dir.exists() else "WARN",
                "path": self._display_path(artifact_dir),
            },
            {
                "name": "skill_runtime_runs",
                "status": "OK" if self._skill_run_dir().exists() else "WARN",
                "path": self._display_path(self._skill_run_dir()),
            },
            {
                "name": "skill_runtime_artifacts",
                "status": "OK" if self._skill_artifact_dir().exists() else "WARN",
                "path": self._display_path(self._skill_artifact_dir()),
            },
            {
                "name": "workspace",
                "status": "OK" if self.app.config.workspace_path.exists() else "ERROR",
                "path": self._display_path(self.app.config.workspace_path),
            },
        ]

    def _storage_detail(self, name: str) -> dict[str, Any]:
        rows = {row["name"]: row for row in self._storage_rows()}
        if name == "forge_database":
            return {**rows[name], "database": self._db_info}
        if name == "forge_artifacts":
            return {**rows[name], "artifact_count": len(self._artifacts)}
        if name == "skill_runtime_runs":
            return {**rows[name], "run_count": len(self._skill_runs)}
        if name == "skill_runtime_artifacts":
            return {
                **rows[name],
                "paths": [self._display_path(item.get("artifact_root", "")) for item in self._skill_runs],
            }
        return rows.get(name, {"name": name, "error": "not found"})

    def _compute_health_issues(self) -> list[dict[str, str]]:
        config = self.app.config
        forge = config.forge
        gateway = getattr(self.app, "_gateway_service", None)
        issues: list[dict[str, str]] = []

        if gateway is None:
            issues.append({"level": "ERROR", "message": "Gateway service is not initialized."})
        elif gateway.error:
            issues.append({"level": "ERROR", "message": f"Gateway service error: {gateway.error}"})
        elif not gateway.is_running:
            issues.append({"level": "WARN", "message": "Gateway service is starting or currently offline."})
        if not self._db_path().exists():
            issues.append({"level": "WARN", "message": "AgentTask store is missing; no persisted orchestration state yet."})
        if self._db_info.get("error"):
            issues.append({"level": "ERROR", "message": f"AgentTask store cannot be read: {self._db_info['error']}"})
        if not self._artifact_dir().exists():
            issues.append({"level": "WARN", "message": "AgentTask artifact directory is missing; no evidence artifacts are retained yet."})
        if not forge.evidence.required_image_sources:
            issues.append({"level": "WARN", "message": "No configured evidence image sources; runtime readiness discovery will be used."})
        return issues

    def _read_db_info(self) -> dict[str, Any]:
        path = self._db_path()
        if not path.exists():
            return {"path": str(path), "exists": False}
        info: dict[str, Any] = {"path": str(path), "exists": True, "tables": {}}
        try:
            with sqlite3.connect(path) as conn:
                table_names = [
                    row[0]
                    for row in conn.execute(
                        "select name from sqlite_master where type='table' order by name"
                    )
                ]
                for table_name in table_names:
                    quoted = '"' + table_name.replace('"', '""') + '"'
                    count = conn.execute(f"select count(*) from {quoted}").fetchone()[0]
                    info["tables"][table_name] = count
        except Exception as exc:
            info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    def _read_artifacts(self) -> list[dict[str, Any]]:
        root = self._artifact_dir()
        if not root.exists():
            return []
        artifacts: list[dict[str, Any]] = []
        for path in root.iterdir():
            if not path.is_dir():
                continue
            files = [item for item in path.rglob("*") if item.is_file()]
            total_bytes = sum(item.stat().st_size for item in files)
            updated_ts = max((item.stat().st_mtime for item in files), default=path.stat().st_mtime)
            artifacts.append({
                "id": path.name,
                "path": str(path),
                "updated": self._format_time(updated_ts),
                "files": len(files),
                "bytes": total_bytes,
                "sample_files": [str(item.relative_to(path)) for item in files[:12]],
            })
        return sorted(artifacts, key=lambda item: item["updated"], reverse=True)

    def _read_sessions(self) -> list[dict[str, Any]]:
        path = self._db_path()
        if not path.exists() or self._db_info.get("error"):
            return []
        try:
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT task_id, status, record_json, created_at, updated_at "
                    "FROM agent_tasks ORDER BY updated_at DESC LIMIT 500"
                ).fetchall()
        except Exception:
            return []

        sessions: list[dict[str, Any]] = []
        artifact_ids = {item["id"] for item in self._artifacts}
        for row in rows:
            try:
                record = json.loads(row["record_json"])
            except Exception as exc:
                record = {"parse_error": f"{type(exc).__name__}: {exc}"}
            verification_contract = record.get("verification", {})
            verdict = record.get("verdict") or {}
            revisions = record.get("revisions") if isinstance(record.get("revisions"), list) else []
            executions = [
                execution
                for revision in revisions
                if isinstance(revision, dict)
                for execution in (revision.get("execution_records") or [])
                if isinstance(execution, dict)
            ]
            action_tools = [item.get("tool_id", "") for item in executions if item.get("semantics") == "action"]
            execution_statuses = [item.get("status", "") for item in executions]
            task_id = row["task_id"]
            artifact = next((item for item in self._artifacts if item["id"] == task_id), None)
            sessions.append(
                {
                    "kind": "session",
                    "session_id": task_id,
                    "command_id": record.get("active_revision_id", ""),
                    "root_session_id": task_id,
                    "parent_session_id": None,
                    "status": row["status"],
                    "updated": row["updated_at"],
                    "created": row["created_at"],
                    "action_type": ", ".join(action_tools) or "no action",
                    "task_description": record.get("task_description", ""),
                    "verification_mode": verification_contract.get("mode", "off"),
                    "verification_status": "completed" if verdict else "not_requested",
                    "verdict": verdict.get("verdict") if isinstance(verdict, dict) else None,
                    "execution_status": ", ".join(execution_statuses) or None,
                    "evidence": self._session_evidence_label(record, artifact),
                    "has_artifact_dir": task_id in artifact_ids,
                    "artifact": artifact,
                    "record": record,
                }
            )
        return sessions

    def _session_artifact_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = list(self._sessions)
        rows.extend(self._skill_runs)
        session_ids = {item["session_id"] for item in self._sessions}
        for artifact in self._artifacts:
            if artifact["id"] in session_ids:
                continue
            rows.append(
                {
                    **artifact,
                    "kind": "artifact",
                    "status": f"{artifact['files']} files",
                    "evidence": self._format_bytes(artifact["bytes"]),
                }
            )
        return rows

    def _read_skill_runs(self) -> list[dict[str, Any]]:
        root = self._skill_run_dir()
        if not root.exists():
            return []
        runs: list[dict[str, Any]] = []
        for path in root.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                record = {"parse_error": f"{type(exc).__name__}: {exc}"}
            run_id = str(record.get("run_id") or path.stem)
            artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), list) else []
            updated = self._float_or_zero(record.get("updated_at"))
            tools = record.get("tools") if isinstance(record.get("tools"), list) else []
            ready_tools = len([item for item in tools if isinstance(item, dict) and item.get("ready")])
            runs.append(
                {
                    "kind": "skill_run",
                    "run_id": run_id,
                    "status": str(record.get("status", "unknown")),
                    "updated": self._format_time(updated or path.stat().st_mtime),
                    "updated_ts": updated or path.stat().st_mtime,
                    "skill_name": str(record.get("skill_name", "")),
                    "profile": str(record.get("profile", "")),
                    "evidence": f"{len(artifacts)} artifacts | tools {ready_tools}/{len(tools)}",
                    "artifact_root": self._display_path(self._skill_artifact_dir() / run_id),
                    "state_file": self._display_path(path),
                    "record": record,
                }
            )
        return sorted(runs, key=lambda item: item["updated_ts"], reverse=True)

    def _skill_run_detail(self, run_id: str) -> dict[str, Any]:
        run = next((item for item in self._skill_runs if item["run_id"] == run_id), None)
        if run is None:
            return {"run_id": run_id, "error": "not found"}
        record = run["record"]
        return {
            "summary": self._sanitize_display_data({
                "run_id": run["run_id"],
                "status": run["status"],
                "skill_name": run["skill_name"],
                "profile": run["profile"],
                "updated": run["updated"],
                "state_file": run["state_file"],
            }),
            "bundle": self._sanitize_display_data(record.get("bundle", {})),
            "install": self._sanitize_display_data(record.get("install", {})),
            "nodes": self._sanitize_display_data(record.get("nodes", [])),
            "environment": self._sanitize_display_data(record.get("environment", {})),
            "runtime": self._sanitize_display_data(record.get("runtime", {})),
            "tools": self._sanitize_display_data(record.get("tools", [])),
            "evolution": self._sanitize_display_data(record.get("evolution", {})),
            "artifacts": self._sanitize_display_data(record.get("artifacts", [])),
            "events": self._sanitize_display_data(record.get("events", [])),
        }

    def _session_detail(self, session_id: str) -> dict[str, Any]:
        session = next((item for item in self._sessions if item["session_id"] == session_id), None)
        if session is None:
            return {"session_id": session_id, "error": "not found"}
        record = session["record"]
        verification = record.get("verification") if isinstance(record.get("verification"), dict) else {}
        verdict = record.get("verdict") if isinstance(record.get("verdict"), dict) else {}
        revisions = record.get("revisions") if isinstance(record.get("revisions"), list) else []
        executions = [
            execution
            for revision in revisions
            if isinstance(revision, dict)
            for execution in (revision.get("execution_records") or [])
            if isinstance(execution, dict)
        ]
        return {
            "summary": self._sanitize_display_data({
                "session_id": session["session_id"],
                "command_id": session["command_id"],
                "root_session_id": session["root_session_id"],
                "parent_session_id": session["parent_session_id"],
                "status": session["status"],
                "action_type": session["action_type"],
                "execution_status": session["execution_status"],
                "verification_mode": session["verification_mode"],
                "verification_status": session["verification_status"],
                "verdict": session["verdict"],
                "evidence": session["evidence"],
                "created": session["created"],
                "updated": session["updated"],
            }),
            "task": self._sanitize_display_data({
                "description": session["task_description"],
                "origin_session_key": record.get("origin_session_key"),
                "runtime_snapshot_ref": record.get("runtime_snapshot_ref"),
            }),
            "execution": self._sanitize_display_data(executions),
            "verification": self._sanitize_display_data({
                "mode": verification.get("mode"),
                "bundle_ref": record.get("evidence_bundle_ref"),
                "verdict": verdict.get("verdict"),
                "reason": verdict.get("reason"),
                "criteria": verdict.get("criteria", []),
            }),
            "evidence": self._sanitize_display_data({
                "artifact_dir": session["artifact"],
                "bundle_ref": record.get("evidence_bundle_ref"),
                "before_snapshot_ref": record.get("before_snapshot_ref"),
                "after_snapshot_ref": record.get("after_snapshot_ref"),
            }),
            "events": self._sanitize_display_data(self._read_session_events(session["root_session_id"])),
        }

    def _read_session_events(self, root_session_id: str) -> list[dict[str, Any]]:
        path = self._db_path()
        if not path.exists() or self._db_info.get("error"):
            return []
        try:
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT task_id, event_type, created_at, payload_json "
                    "FROM agent_task_events "
                    "WHERE task_id = ? ORDER BY event_id DESC LIMIT 50",
                    (root_session_id,),
                ).fetchall()
        except Exception as exc:
            return [{"error": f"{type(exc).__name__}: {exc}"}]
        events: list[dict[str, Any]] = []
        for row in reversed(rows):
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                payload = row["payload_json"]
            events.append(
                {
                    "task_id": row["task_id"],
                    "event_type": row["event_type"],
                    "created_at": row["created_at"],
                    "payload": payload,
                }
            )
        return events

    @staticmethod
    def _session_evidence_label(record: dict[str, Any], artifact: dict[str, Any] | None) -> str:
        bundle_ref = record.get("evidence_bundle_ref")
        artifact_label = f"{artifact['files']} files" if artifact else "no dir"
        if bundle_ref:
            return f"{bundle_ref} | {artifact_label}"
        before_ref = record.get("before_snapshot_ref")
        if before_ref:
            return f"before snapshot | {artifact_label}"
        return artifact_label

    def _matches_search(self, data: dict[str, Any]) -> bool:
        if not self._search_query:
            return True
        return self._search_query in yaml.safe_dump(data, allow_unicode=True, sort_keys=False).lower()

    def _db_path(self) -> Path:
        return self.app.config.workspace_path / ".paos" / "agent_tasks" / "tasks.sqlite3"

    def _artifact_dir(self) -> Path:
        return self.app.config.workspace_path / "artifacts" / "agent_tasks"

    def _skill_run_dir(self) -> Path:
        return self.app.config.workspace_path / ".paos" / "skill_runtime" / "runs"

    def _skill_artifact_dir(self) -> Path:
        return self.app.config.workspace_path / "artifacts" / "skill_runtime"

    @staticmethod
    def _format_detail(title: str, data: dict[str, Any]) -> str:
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        return f"{title}\n\n{body}"

    def _display_path(self, value: str | Path) -> str:
        try:
            path = Path(value)
        except Exception:
            return str(value)

        try:
            workspace = self.app.config.workspace_path.resolve(strict=False)
        except Exception:
            workspace = None

        try:
            resolved = path if path.is_absolute() else (workspace / path if workspace else path)
            resolved = resolved.resolve(strict=False)
        except Exception:
            return str(value)

        if workspace is not None:
            try:
                rel = resolved.relative_to(workspace)
                return "<workspace>" if not rel.parts else f"<workspace>/{rel.as_posix()}"
            except ValueError:
                pass
        return resolved.name if resolved.is_absolute() else str(value)

    def _sanitize_display_data(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                if self._looks_like_path_key(key):
                    sanitized[key] = self._display_path(item)
                else:
                    sanitized[key] = self._sanitize_display_data(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_display_data(item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_display_data(item) for item in value]
        if isinstance(value, str) and self._looks_like_path_value(value):
            return self._display_path(value)
        return value

    @staticmethod
    def _looks_like_path_key(key: str) -> bool:
        lowered = key.lower()
        return (
            lowered in {"path", "workspace", "store", "artifact_root", "state_file", "artifact_dir"}
            or lowered.endswith("_path")
            or lowered.endswith("_root")
            or lowered.endswith("_ref")
        )

    @staticmethod
    def _looks_like_path_value(value: str) -> bool:
        return value.startswith(("\\", "/")) or ":\\" in value or value.startswith("file:")

    @staticmethod
    def _format_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")

    @staticmethod
    def _format_bytes(size: int) -> str:
        units = ("B", "KB", "MB", "GB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    @staticmethod
    def _float_or_zero(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

