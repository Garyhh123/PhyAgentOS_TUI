# Runtime Targets — PiperGo2 Isaac Sim

```yaml
version: runtime_target_registry_v1
targets:
  - id: pipergo2_isaac_remote
    target_class: remote
    target_kind: simulation
    enabled: true
    workspace: workspaces/pipergo2_isaac_sim
    supported_skillruntimes:
      - pipergo2_isaac_vla
      - pipergo2_command_sim
    runtime:
      target_runtime: IsaacSimRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9003
      target_adapter: target_adapter://isaacsim_adapter
      runtime_contract_ref: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      robot_id: ""
      rollout_reset_each_session: false
      action_dim: 8
      max_chunk_size: 50
      max_steps: 600
      image_size: 224
      state_dim: 8
      image_key: camera1
      wrist_image_key: camera2
      third_image_key: camera3
      action:
        action_dim: 8
        action_name: arm_joint_controller
        control_wrap: list
        chunk_size: 4
```
