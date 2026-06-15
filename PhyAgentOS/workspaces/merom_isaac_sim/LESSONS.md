# Runtime Lessons

```yaml
version: runtime_lessons_v1
updated_at: '2026-06-14T09:17:05.119975+00:00'
lessons:
- id: lesson_sess_merom_franka_pick_place_1
  timestamp: '2026-06-14T09:17:05.119964+00:00'
  session_id: sess_merom_franka_pick_place
  phase: preflight_checking
  error_code: RUNTIME_PREFLIGHT_FAILED
  target_id: franka_merom_sim
  skillruntime_id: pipergo2_command_sim
  summary: 'TARGET_RUNTIME_CONTRACT_INVALID: configs/runtime/contracts/isaacsim_pipergo2.runtime.yaml
    expected franka_merom_sim, found pipergo2_isaac_remote; EMPTY_OBSERVATION_INVALID:
    TARGETS.md targets[].observation expected explicit empty observation allowed,
    found multimodal'
  metadata:
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
