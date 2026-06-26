# Runtime Targets — BEHAVIOR-1K

```yaml
version: runtime_target_registry_v1
targets:
  - id: behavior1k_r1pro_sim
    target_class: remote
    target_kind: simulation
    enabled: true
    workspace: b1k_integration/workspaces/behavior1k_eval
    supported_skillruntimes:
      - behavior1k_vla
      - behavior1k_pi0_openpi
    runtime:
      target_runtime: Behavior1KRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9004
      target_adapter: target_adapter://behavior1k_openpi_adapter
      runtime_contract_ref: configs/runtime/contracts/behavior1k_r1pro.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      task_name: turning_on_radio
      instance_id: 0
      action_dim: 23
      max_chunk_size: 50
      max_steps: 200
      chunk_size: 1
      headless: false
```
