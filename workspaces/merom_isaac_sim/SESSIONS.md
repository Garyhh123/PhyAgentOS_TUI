# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: sess_merom_piper_nav
  goal_id: goal_merom_piper_nav
  target_ref: target://pipergo2_merom_sim
  skillruntime_ref: skillruntime://pipergo2_command_sim
  task_description: piper navigate to desk
  status: pending
  priority: high
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9003
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 4
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - text: go to desk
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default_simulation
    stop_on_policy_timeout: true
  result:
    metadata: {}
- session_id: sess_merom_franka_pick_place
  goal_id: goal_merom_franka_pick_place
  target_ref: target://franka_merom_sim
  skillruntime_ref: skillruntime://pipergo2_command_sim
  task_description: franka pick and place
  status: rejected
  priority: normal
  updated_at: '2026-06-14T09:17:05.125933Z'
  claimed_by: runtime-watchdog@server
  claim_token: d183ed3d55a2495abe9b7ec972e8309c
  timeouts:
    queue_timeout_s: 30.0
    preflight_timeout_s: 20.0
    execute_timeout_s: 300.0
    policy_timeout_s: 5.0
  retry:
    max_retries: 0
    attempted: 0
  depends_on: []
  routing:
    target_endpoint: targetws://127.0.0.1:9003
    policy_endpoint: dummy://local
    adapter_resolution: strict_auto
  execution:
    max_steps: 8
    replan_every: 8
    action_chunk_mode: chunk_buffer
    chunk_switch_mode: hard_switch
    steps:
    - command: franka_pick_place
      params: {}
  runtime_hints:
    perception_queries: []
    force_environment_refresh: false
  safety_profile:
    profile: default_simulation
    stop_on_policy_timeout: true
  result:
    status: rejected
    success: false
    error_code: RUNTIME_PREFLIGHT_FAILED
    error_message: 'TARGET_RUNTIME_CONTRACT_INVALID: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
      expected franka_merom_sim, found pipergo2_isaac_remote; EMPTY_OBSERVATION_INVALID:
      TARGETS.md targets[].observation expected explicit empty observation allowed,
      found multimodal'
    metadata:
      preflight:
        verdict: rejected
        session_id: sess_merom_franka_pick_place
        target_id: franka_merom_sim
        skillruntime_id: pipergo2_command_sim
        runner_type: SessionRunner
        skill_runtime_kind: builtin
        execution_mode: builtin_command_loop
        missing_items:
        - code: TARGET_RUNTIME_CONTRACT_INVALID
          field: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
          expected: franka_merom_sim
          found: pipergo2_isaac_remote
          triggered_by: sess_merom_franka_pick_place
          fix: Use a contract with matching target_id.
        - code: EMPTY_OBSERVATION_INVALID
          field: TARGETS.md targets[].observation
          expected: explicit empty observation allowed
          found: multimodal
          triggered_by: sess_merom_franka_pick_place
          fix: Declare empty observation on target.
        warnings: []
```
