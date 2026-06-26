"""Benchmark registry and evaluation report schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BenchmarkSuiteSpec(BaseModel):
    id: str
    title: str = ""
    task_source: str = "challenge50"
    task_names: list[str] = Field(default_factory=list)
    default_instance_ids: list[int] = Field(default_factory=lambda: [0])


class BenchmarkSpec(BaseModel):
    id: str
    title: str = ""
    enabled: bool = True
    behavior1k_root: str | None = None
    eval_script: str = "OmniGibson/omnigibson/learning/eval.py"
    execution_backend: Literal["behavior1k_native", "runtime_watchdog"] = "behavior1k_native"
    default_target_ref: str = "target://behavior1k_r1pro_sim"
    default_skillruntime_ref: str = "skillruntime://behavior1k_vla"
    default_skill_ref: str = "skillruntime://behavior1k_vla"
    default_adapter: str = "behavior1k_openpi_adapter"
    workspace: str = "b1k_integration/workspaces/behavior1k_eval"
    suites: list[BenchmarkSuiteSpec] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class BenchmarksDocument(BaseModel):
    version: Literal["benchmark_registry_v1"] = "benchmark_registry_v1"
    benchmarks: list[BenchmarkSpec] = Field(default_factory=list)


class BenchmarkPolicySpec(BaseModel):
    id: str
    name: str = ""
    status: Literal["available", "reserved", "disabled"] = "available"
    policy_endpoint: str
    adapter: str = "behavior1k_openpi_adapter"
    action_dim: int = 23
    chunk_size: int = 1
    notes: str = ""
    hydra_policy: str | None = None
    hydra_overrides: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class PoliciesDocument(BaseModel):
    version: Literal["benchmark_policies_v1"] = "benchmark_policies_v1"
    policies: list[BenchmarkPolicySpec] = Field(default_factory=list)


class BenchmarkTaskSpec(BaseModel):
    name: str
    index: int | None = None
    instruction: str = ""


class BenchmarkEpisodeResult(BaseModel):
    task_name: str
    task_index: int | None = None
    instance_id: int
    success: bool | None = None
    q_score: float | None = None
    num_steps: int | None = None
    log_path: str | None = None
    metrics_path: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkRunReport(BaseModel):
    run_id: str
    benchmark_id: str
    suite_id: str
    policy_id: str
    backend: str
    tasks_total: int = 0
    episodes_total: int = 0
    episodes_succeeded: int = 0
    success_rate: float | None = None
    mean_q_score: float | None = None
    episodes: list[BenchmarkEpisodeResult] = Field(default_factory=list)
    summary_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
