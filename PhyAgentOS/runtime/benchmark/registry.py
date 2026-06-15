"""Load BENCHMARKS.md and POLICIES.md registries."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from PhyAgentOS.runtime.benchmark.schemas import (
    BenchmarkPolicySpec,
    BenchmarkSpec,
    BenchmarksDocument,
    PoliciesDocument,
)
from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block
from PhyAgentOS.runtime.watchdog.errors import SchemaValidationError


class BenchmarkRegistry:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.path = self.workspace / "BENCHMARKS.md"

    def load(self) -> BenchmarksDocument:
        if not self.path.is_file():
            raise FileNotFoundError(f"benchmark registry not found: {self.path}")
        try:
            return BenchmarksDocument.model_validate(read_yaml_block(self.path))
        except ValidationError as exc:
            raise SchemaValidationError(str(exc)) from exc

    def get(self, benchmark_id: str) -> BenchmarkSpec:
        doc = self.load()
        for item in doc.benchmarks:
            if item.id == benchmark_id and item.enabled:
                return item
        raise SchemaValidationError(f"enabled benchmark not found: {benchmark_id}")


class PolicyRegistry:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.path = self.workspace / "POLICIES.md"

    def load(self) -> PoliciesDocument:
        if not self.path.is_file():
            raise FileNotFoundError(f"policy registry not found: {self.path}")
        try:
            return PoliciesDocument.model_validate(read_yaml_block(self.path))
        except ValidationError as exc:
            raise SchemaValidationError(str(exc)) from exc

    def get(self, policy_id: str) -> BenchmarkPolicySpec:
        doc = self.load()
        for item in doc.policies:
            if item.id == policy_id:
                if item.status == "disabled":
                    raise SchemaValidationError(f"policy is disabled: {policy_id}")
                return item
        raise SchemaValidationError(f"policy not found: {policy_id}")

    def list_available(self) -> list[BenchmarkPolicySpec]:
        return [p for p in self.load().policies if p.status != "disabled"]
