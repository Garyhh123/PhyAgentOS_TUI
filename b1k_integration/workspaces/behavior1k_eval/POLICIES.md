# Benchmark Policies

策略注册表：`status=available` 可直接评测；`status=reserved` 预留接口（权重未下载）。

```yaml
version: benchmark_policies_v1
policies:
  - id: dummy_baseline
    name: Dummy demo-motion baseline (TargetWS wiggle)
    status: available
    policy_endpoint: dummy://local
    adapter: behavior1k_openpi_adapter
    action_dim: 23
    chunk_size: 1
    hydra_policy: local
    hydra_overrides:
      model._target_: b1k_integration.eval_compat.demo_wiggle_policy.DemoWigglePolicy
      policy_name: demo_wiggle
    notes: Runtime watchdog path uses b1k_dummy_policy_adapter (gentle periodic motion). Legacy behavior1k_native still uses eval.py + eval_compat.

  - id: b1k_websocket
    name: B1K pi0 OpenPI policy server (serve_b1k)
    status: available
    policy_endpoint: b1k-ws://127.0.0.1:8000
    adapter: behavior1k_openpi_adapter
    action_dim: 23
    chunk_size: 1
    notes: Start b1k_integration/scripts/start_b1k_openpi_policy_server.sh with CHECKPOINT_DIR set. Uses OmniGibson WebsocketPolicyServer protocol.

  - id: openpi_r1pro
    name: OpenPI R1Pro checkpoint (reserved)
    status: reserved
    policy_endpoint: reserved://openpi_r1pro?notes=Download+checkpoint+and+register+endpoint
    adapter: behavior1k_openpi_adapter
    action_dim: 23
    chunk_size: 8
    notes: Placeholder — download OpenPI / b1k-baselines weights and set policy_endpoint to openpi://HOST:PORT or b1k-ws://HOST:PORT.

  - id: openvla_r1pro
    name: OpenVLA R1Pro (reserved)
    status: reserved
    policy_endpoint: reserved://openvla_r1pro
    adapter: behavior1k_openpi_adapter
    action_dim: 23
    notes: Placeholder for OpenVLA baseline integration.

  - id: custom_http
    name: Custom HTTP policy (reserved)
    status: reserved
    policy_endpoint: reserved://custom_http
    adapter: behavior1k_openpi_adapter
    notes: Extend PhyAgentOS.runtime.policy.factory with your HTTP client scheme.
```
