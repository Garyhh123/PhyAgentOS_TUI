# Runtime Targets — Merom multi-robot

同一 TargetWS 服务、同一 Isaac 场景；**`robot_id`** 区分机器人。

```yaml
version: runtime_target_registry_v1
targets:
  - id: pipergo2_merom_sim
    target_class: remote
    target_kind: simulation
    enabled: true
    workspace: workspaces/merom_isaac_sim
    supported_skillruntimes:
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_merom_pipergo2.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: pipergo2
      rollout_reset_each_session: false
      action_dim: 8
      observation:
        image_size: 224
        state_dim: 8
      action:
        action_dim: 8
        action_name: arm_joint_controller
        control_wrap: list
  - id: g1_merom_sim
    target_class: remote
    target_kind: simulation
    enabled: true
    workspace: workspaces/merom_isaac_sim
    supported_skillruntimes:
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_merom_g1.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: g1
      rollout_reset_each_session: false
      action_dim: 8
      observation:
        image_size: 224
        state_dim: 8
      action:
        pass_through_control: true
  - id: franka_merom_sim
    target_class: remote
    target_kind: simulation
    enabled: true
    workspace: workspaces/merom_isaac_sim
    supported_skillruntimes:
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_merom_franka.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: franka
      rollout_reset_each_session: false
      action_dim: 8
      observation:
        image_size: 224
        state_dim: 8
      action:
        pass_through_control: true
```
