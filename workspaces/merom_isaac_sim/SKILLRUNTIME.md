# Runtime Skillruntimes — Merom Isaac Sim

```yaml
version: runtime_skill_registry_v1
skillruntimes:
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
