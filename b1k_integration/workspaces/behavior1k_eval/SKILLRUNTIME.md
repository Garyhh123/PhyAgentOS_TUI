# Runtime Skill Runtimes — BEHAVIOR-1K

```yaml
version: runtime_skill_registry_v1
skillruntimes:
  - id: behavior1k_vla
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
    policy:
      policy_client: dummy
      policy_adapter: policy_adapter://b1k_dummy_policy_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: true
    input_contract:
      images:
        - observation/head_rgb
        - observation/left_wrist_rgb
        - observation/right_wrist_rgb
      state: observation/state
      prompt: prompt
    output_contract:
      action:
        action_space_id: behavior1k_r1pro_joint_v1
        tensor_key: actions
        shape:
          - T
          - 23
        dtype: float32
        normalized: false
        representation: joint_position
        frame: robot
        chunk:
          variable_T: true
          default_T: 1
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden: []
  - id: behavior1k_pi0_openpi
    runtime: OpenPISkillRuntime
    runtime_kind: policy
    loop_mode: policy_closed_loop
    agent_exposure: none
    supported_target_kinds:
      - simulation
    policy:
      policy_client: openpi
      policy_adapter: policy_adapter://b1k_openpi_policy_adapter
      supports_chunk: true
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    supports_chunk: true
    default_replan_every: 1
    requires:
      sensors: []
      environment_outputs: []
      strict_environment_contract: true
    output_contract:
      action:
        action_space_id: behavior1k_r1pro_joint_v1
        tensor_key: actions
        shape:
          - T
          - 23
        dtype: float32
        normalized: false
        representation: joint_position
        frame: robot
        chunk:
          variable_T: true
          default_T: 1
          policy_hz: 20
    adapter_requirements:
      allowed_bridges:
        - bridge://safety_clamp
      forbidden: []
```
