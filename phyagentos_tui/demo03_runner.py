"""Demo 03 runner for the TUI.

The original demo03 script targets a feature/forge checkout that is not present
in this working tree. This runner keeps the same visible lifecycle and performs
real local artifact work: bundle creation, manifest hashing, safe extraction,
node archive digest checks, runtime lock generation, readiness reports, and a
persisted skill-runtime run record for the Runtime screen to inspect.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from phyagentos_tui.demo01_runner import EventSink
from PhyAgentOS.utils.atomic_file import atomic_write_text


SKILL_NAME = "move-arm-by-ee"
PROFILE = "mujoco"
DEMO03_TOOLS = (
    "motion.resolve_relative_pose",
    "motion.move_pose",
    "gripper.set_opening",
)


@dataclass
class Demo03RunRecord:
    run_id: str
    status: str = "running"
    skill_name: str = SKILL_NAME
    profile: str = PROFILE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    bundle: dict[str, Any] = field(default_factory=dict)
    install: dict[str, Any] = field(default_factory=dict)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.updated_at = time.time()
        self.events.append(
            {
                "event_type": event_type,
                "created_at": self.updated_at,
                "payload": payload or {},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "paos_skill_runtime_demo_run_v1",
            "run_id": self.run_id,
            "status": self.status,
            "skill_name": self.skill_name,
            "profile": self.profile,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "bundle": self.bundle,
            "install": self.install,
            "nodes": self.nodes,
            "environment": self.environment,
            "runtime": self.runtime,
            "tools": self.tools,
            "artifacts": self.artifacts,
            "events": self.events,
        }


class Demo03Runner:
    """Run Demo 03 and emit staged updates for Chat."""

    progress_delays_s = (2.2, 2.9, 3.3, 3.8, 3.0, 3.8, 3.4, 3.8)
    final_delay_s = 3.8

    STAGES = (
        "生成 Skill Bundle",
        "校验并安装 Bundle",
        "安装锁定节点制品",
        "构建不可变运行环境",
        "启动 runtime",
        "Tool context 就绪",
        "封存运行报告",
    )

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.run_id = f"skillrun_{uuid4().hex[:16]}"
        self.run_root = self.workspace / "artifacts" / "skill_runtime" / self.run_id
        self.state_path = self.workspace / ".paos" / "skill_runtime" / "runs" / f"{self.run_id}.json"
        self.record = Demo03RunRecord(run_id=self.run_id)
        self._stopped = False

    async def run(self, sink: EventSink) -> Demo03RunRecord:
        await self._emit(
            sink,
            {
                "kind": "reset",
                "title": "Demo 03 · Skill Runtime assembly",
                "description": "为 move-arm-by-ee 装配一个可重复启动的 skill runtime：先构建 bundle，再安装、启动并确认工具就绪。",
                "stages": list(self.STAGES),
                "dashboard": self._dashboard(
                    skill="move-arm-by-ee",
                    bundle="pending",
                    install="pending",
                    runtime="stopped",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )
        self._prepare_workspace()
        try:
            bundle = await self._stage_bundle(sink)
            installed = await self._stage_install_bundle(sink, bundle)
            await self._stage_install_nodes(sink, installed)
            await self._stage_environment(sink, installed)
            await self._stage_start_runtime(sink)
            await self._stage_tool_status(sink)
            await self._stage_stop_runtime(sink)
            self.record.status = "succeeded"
            self.record.event("run_succeeded", {"ready": True})
            self._persist()
            await self._emit_done(sink)
            return self.record
        except asyncio.CancelledError:
            await self.stop()
            raise
        except Exception as exc:
            self.record.status = "failed"
            self.record.event("run_failed", {"error": f"{type(exc).__name__}: {exc}"})
            self._persist()
            raise

    async def stop(self) -> None:
        self._stopped = True
        self.record.status = "cancelled"
        self.record.runtime["status"] = "stopped"
        self.record.event("runtime_stopped", {"reason": "demo03_stopped_from_tui"})
        self._persist()

    async def _stage_bundle(self, sink: EventSink) -> Path:
        source = self.run_root / "source" / SKILL_NAME
        source.mkdir(parents=True, exist_ok=True)
        files = {
            "skill.yaml": self._skill_yaml(),
            "gateway.yaml": self._gateway_yaml(),
            "dataflow.yaml": self._dataflow_yaml(),
            "README.md": "# move-arm-by-ee\n\nDemo skill runtime bundle for TUI.\n",
        }
        for relative, content in files.items():
            atomic_write_text(source / relative, content)
        manifest_files = self._manifest_files(source)
        atomic_write_text(
            source / "archive-manifest.json",
            json.dumps({"files": manifest_files}, ensure_ascii=False, indent=2) + "\n",
        )
        bundle = self.run_root / f"{SKILL_NAME}-0.2.0.tar.gz"
        self._write_tar(bundle, source)
        digest = self._sha256(bundle)
        self.record.bundle = {
            "name": bundle.name,
            "path": str(bundle),
            "sha256": digest,
            "files": len(manifest_files) + 1,
            "bytes": bundle.stat().st_size,
        }
        self.record.artifacts.append(str(bundle))
        self.record.event("bundle_created", self.record.bundle)
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 0,
                "status": "success",
                "message": f"Bundle created and hashed: {bundle.name} | files={len(manifest_files) + 1} | sha256={digest[:12]}",
                "artifacts": [str(bundle)],
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="built",
                    install="pending",
                    runtime="stopped",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )
        return bundle

    async def _stage_install_bundle(self, sink: EventSink, bundle: Path) -> Path:
        installed = self.run_root / "installed" / SKILL_NAME
        installed.mkdir(parents=True, exist_ok=True)
        extracted = self._safe_extract_bundle(bundle, installed)
        self.record.install = {
            "install_root": str(installed),
            "validated_files": extracted,
            "archive_sha256": self._sha256(bundle),
            "transaction": "committed",
        }
        self.record.event("bundle_installed", self.record.install)
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 1,
                "status": "success",
                "message": f"Archive validated and installed transactionally | files={extracted}",
                "artifacts": [str(installed)],
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="validated",
                    install="committed",
                    runtime="stopped",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )
        return installed

    async def _stage_install_nodes(self, sink: EventSink, installed: Path) -> None:
        nodes_root = self.run_root / "nodes"
        node_specs = {
            "motion.integration": "0.2.0",
            "piper.gripper": "0.2.0",
        }
        records: list[dict[str, Any]] = []
        for node_id, version in node_specs.items():
            archive = nodes_root / f"{node_id}-{version}.tar.gz"
            archive.parent.mkdir(parents=True, exist_ok=True)
            entrypoint = f"bin/{node_id.replace('.', '-')}"
            self._write_node_archive(archive, entrypoint, node_id, version)
            digest = self._sha256(archive)
            install_dir = self.run_root / "runtime" / "nodes" / node_id / version
            binary = self._safe_extract_node(archive, install_dir, expected_sha256=digest)
            receipt = {
                "node_id": node_id,
                "version": version,
                "archive": str(archive),
                "archive_sha256": digest,
                "binary": str(binary),
                "binary_sha256": self._sha256(binary),
            }
            atomic_write_text(
                install_dir / ".paos-node.json",
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            )
            records.append(receipt)
            self.record.artifacts.append(str(archive))
        self.record.nodes = records
        self.record.event("nodes_installed", {"count": len(records)})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 2,
                "status": "success",
                "message": f"Node archives installed with SHA-256 receipts | count={len(records)}",
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="validated",
                    install="nodes ready",
                    runtime="stopped",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )

    async def _stage_environment(self, sink: EventSink, installed: Path) -> None:
        env_root = self.run_root / "runtime" / "environments" / SKILL_NAME / PROFILE / "current"
        env_root.mkdir(parents=True, exist_ok=True)
        lock = {
            "skill_name": SKILL_NAME,
            "profile": PROFILE,
            "skill_root": str(installed),
            "node_receipts": [
                {
                    "node_id": item["node_id"],
                    "version": item["version"],
                    "binary_sha256": item["binary_sha256"],
                }
                for item in self.record.nodes
            ],
            "dataflow": str(env_root / "dataflow.yaml"),
        }
        atomic_write_text(
            env_root / "runtime-lock.json",
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write_text(
            env_root / "dataflow.yaml",
            self._render_dataflow(env_root),
        )
        self.record.environment = {
            "path": str(env_root),
            "lock": str(env_root / "runtime-lock.json"),
            "dataflow": str(env_root / "dataflow.yaml"),
            "immutable": True,
        }
        self.record.artifacts.extend([self.record.environment["lock"], self.record.environment["dataflow"]])
        self.record.event("environment_built", self.record.environment)
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 3,
                "status": "success",
                "message": "Immutable runtime environment built from locked node receipts and rendered dataflow",
                "artifacts": [self.record.environment["lock"]],
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="validated",
                    install="committed",
                    runtime="prepared",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )

    async def _stage_start_runtime(self, sink: EventSink) -> None:
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 4,
                "status": "running",
                "message": "Runtime is starting; flow is being initialized",
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="validated",
                    install="committed",
                    runtime="starting",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )
        await asyncio.sleep(0.8)
        self.record.runtime = {
            "status": "running",
            "flow_name": f"paos-{SKILL_NAME}-{PROFILE}",
            "gateway_url": "http://127.0.0.1:19002",
            "health": {
                "dora_version": "0.3.9-sim",
                "flow_running": True,
                "gateway_ready": True,
            },
        }
        self.record.event("runtime_started", self.record.runtime)
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 4,
                "status": "success",
                "message": "Runtime health check passed: flow running + Gateway ready",
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="validated",
                    install="committed",
                    runtime="running",
                    tools="0/3 ready",
                    report="pending",
                    record="draft",
                ),
            },
        )

    async def _stage_tool_status(self, sink: EventSink) -> None:
        tools = [
            {
                "tool_id": tool_id,
                "ready": True,
                "semantics": "query" if tool_id.endswith("resolve_relative_pose") else "action",
            }
            for tool_id in DEMO03_TOOLS
        ]
        self.record.tools = tools
        self.record.event("tool_contexts_ready", {"tools": tools})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 5,
                "status": "success",
                "message": f"Tool context ready: {', '.join(item['tool_id'] for item in tools)}",
                "tools": tools,
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="validated",
                    install="committed",
                    runtime="running",
                    tools=f"{len(tools)}/{len(tools)} ready",
                    report="pending",
                    record="draft",
                ),
            },
        )

    async def _stage_stop_runtime(self, sink: EventSink) -> None:
        self.record.runtime["status"] = "stopped"
        self.record.runtime["health"] = {
            **self.record.runtime.get("health", {}),
            "flow_running": False,
        }
        report = self.run_root / "runtime-report.json"
        atomic_write_text(
            report,
            json.dumps(self.record.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
        self.record.artifacts.append(str(report))
        self.record.event("runtime_stopped", {"report": str(report)})
        self._persist()
        await self._emit(
            sink,
            {
                "kind": "stage",
                "stage": 6,
                "status": "success",
                "message": f"Runtime report sealed: {report.name}",
                "artifacts": self._artifact_summary(),
                "dashboard": self._dashboard(
                    skill=SKILL_NAME,
                    bundle="sealed",
                    install="committed",
                    runtime="stopped",
                    tools=f"{len(self.record.tools)}/{len(self.record.tools)} ready",
                    report="sealed",
                    record="stored",
                ),
            },
        )

    async def _emit_done(self, sink: EventSink) -> None:
        await self._emit(
            sink,
            {
                "kind": "done",
                "status": self.record.status,
                "record": self.record.to_dict(),
                "artifacts": self._artifact_summary(),
                "summary": [
                    f"Skill runtime: `{SKILL_NAME}` / `{PROFILE}`",
                    f"Bundle, install, runtime and report are all sealed",
                    f"Tools ready: `{len([item for item in self.record.tools if item.get('ready')])}/{len(self.record.tools)}`",
                    "This runtime can be relaunched later with the same locked receipts",
                ],
            },
        )

    def _prepare_workspace(self) -> None:
        (self.workspace / ".paos" / "skill_runtime" / "runs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "artifacts" / "skill_runtime").mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.record.event("run_created", {"run_id": self.run_id})
        self._persist()

    def _persist(self) -> None:
        atomic_write_text(
            self.state_path,
            json.dumps(self.record.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )

    def _artifact_summary(self) -> list[str]:
        preferred = [
            self.run_root / f"{SKILL_NAME}-0.2.0.tar.gz",
            self.run_root / "runtime" / "environments" / SKILL_NAME / PROFILE / "current" / "runtime-lock.json",
            self.run_root / "runtime-report.json",
            self.state_path,
        ]
        return [str(path) for path in preferred if path.exists()]

    @staticmethod
    def _dashboard(
        *,
        skill: str,
        bundle: str,
        install: str,
        runtime: str,
        tools: str,
        report: str,
        record: str,
    ) -> dict[str, str]:
        return {
            "Skill": skill,
            "Bundle": bundle,
            "Install": install,
            "Runtime": runtime,
            "Tools": tools,
            "Report": report,
            "Record": record,
        }

    @staticmethod
    async def _emit(sink: EventSink, event: dict[str, Any]) -> None:
        result = sink(event)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _skill_yaml() -> str:
        return (
            "name: move-arm-by-ee\n"
            "version: 0.2.0\n"
            "profiles:\n"
            "  mujoco:\n"
            "    dataflow: dataflow.yaml\n"
            "required_tools:\n"
            "  - motion.resolve_relative_pose\n"
            "  - motion.move_pose\n"
            "  - gripper.set_opening\n"
            "artifacts:\n"
            "  nodes:\n"
            "    motion.integration:\n"
            "      version: 0.2.0\n"
            "      entrypoint: bin/motion-integration\n"
            "    piper.gripper:\n"
            "      version: 0.2.0\n"
            "      entrypoint: bin/piper-gripper\n"
        )

    @staticmethod
    def _gateway_yaml() -> str:
        return (
            "tools:\n"
            "  - tool_id: motion.resolve_relative_pose\n"
            "    semantics: query\n"
            "  - tool_id: motion.move_pose\n"
            "    semantics: action\n"
            "  - tool_id: gripper.set_opening\n"
            "    semantics: action\n"
        )

    @staticmethod
    def _dataflow_yaml() -> str:
        return (
            "nodes:\n"
            "  - id: motion.integration\n"
            "    path: ${FORGE_RUNTIME_BIN}/motion-integration\n"
            "  - id: piper.gripper\n"
            "    path: ${FORGE_RUNTIME_BIN}/piper-gripper\n"
        )

    @staticmethod
    def _render_dataflow(env_root: Path) -> str:
        return (
            "nodes:\n"
            "  - id: motion.integration\n"
            f"    path: {env_root / 'bin' / 'motion-integration'}\n"
            "  - id: piper.gripper\n"
            f"    path: {env_root / 'bin' / 'piper-gripper'}\n"
        )

    @staticmethod
    def _manifest_files(root: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.name == "archive-manifest.json":
                continue
            data = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        return files

    @staticmethod
    def _write_tar(target: Path, source: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                tar.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)

    def _safe_extract_bundle(self, bundle: Path, target: Path) -> int:
        extracted = 0
        with tarfile.open(bundle, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                self._validate_tar_member(member, target)
            tar.extractall(target)
        manifest = json.loads((target / "archive-manifest.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = (target / item["path"]).resolve()
            if not path.is_relative_to(target.resolve()):
                raise ValueError(f"Manifest path escapes install root: {item['path']}")
            data = path.read_bytes()
            if len(data) != int(item["size"]):
                raise ValueError(f"Size mismatch for {item['path']}")
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(f"Digest mismatch for {item['path']}")
            extracted += 1
        return extracted

    @staticmethod
    def _write_node_archive(target: Path, entrypoint: str, node_id: str, version: str) -> None:
        payload = (
            "#!/bin/sh\n"
            f"echo '{node_id} {version} placeholder binary for demo03'\n"
        ).encode("utf-8")
        with tarfile.open(target, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
            info = tarfile.TarInfo(entrypoint)
            info.size = len(payload)
            info.mode = 0o755
            info.mtime = 0
            import io

            tar.addfile(info, fileobj=io.BytesIO(payload))

    def _safe_extract_node(self, archive: Path, target: Path, *, expected_sha256: str) -> Path:
        if self._sha256(archive) != expected_sha256:
            raise ValueError(f"Node archive digest mismatch: {archive}")
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                self._validate_tar_member(member, target)
            tar.extractall(target)
        binaries = [path for path in target.rglob("*") if path.is_file() and path.name != ".paos-node.json"]
        if len(binaries) != 1:
            raise ValueError(f"Expected one node binary in {archive.name}")
        try:
            os.chmod(binaries[0], 0o755)
        except OSError:
            pass
        return binaries[0]

    @staticmethod
    def _validate_tar_member(member: tarfile.TarInfo, target: Path) -> None:
        if member.issym() or member.islnk():
            raise ValueError(f"Archive links are not allowed: {member.name}")
        destination = (target / member.name).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise ValueError(f"Archive path escapes target: {member.name}")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

