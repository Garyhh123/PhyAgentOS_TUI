# Runtime Skillruntimes — PiperGo2 Isaac Sim

```yaml
version: runtime_skill_registry_v1
skillruntimes:
  - id: pipergo2_isaac_vla
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
    policy:
      policy_client: openpi
      policy_adapter: policy_adapter://pipergo2_isaac_openpi_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 4
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: false
    output_contract:
      action:
        action_space_id: pipergo2_isaac_joint_v1
        shape:
          - T
          - 8
        dtype: float32
        chunk:
          default_T: 4
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden: []
  - id: pipergo2_command_sim
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - simulation
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    target_tool_policy:
      expose:
        - execute_step
      forbidden: []
    supports_chunk: false
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: false
    adapter_requirements:
      allowed_bridges: []
      forbidden: []
```
