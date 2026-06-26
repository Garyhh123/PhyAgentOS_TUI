# Runtime Lessons

```yaml
version: runtime_lessons_v1
updated_at: '2026-06-14T09:16:53.939675+00:00'
lessons:
- id: lesson_sess_piper_language_nav_1
  timestamp: '2026-06-14T09:15:47.326565+00:00'
  session_id: sess_piper_language_nav
  phase: preflight_checking
  error_code: RUNTIME_PREFLIGHT_FAILED
  target_id: pipergo2_isaac_remote
  skillruntime_id: pipergo2_command_sim
  summary: 'EMPTY_OBSERVATION_INVALID: TARGETS.md targets[].observation expected explicit
    empty observation allowed, found multimodal'
  metadata:
    verdict: rejected
    session_id: sess_piper_language_nav
    target_id: pipergo2_isaac_remote
    skillruntime_id: pipergo2_command_sim
    runner_type: SessionRunner
    skill_runtime_kind: builtin
    execution_mode: builtin_command_loop
    missing_items:
    - code: EMPTY_OBSERVATION_INVALID
      field: TARGETS.md targets[].observation
      expected: explicit empty observation allowed
      found: multimodal
      triggered_by: sess_piper_language_nav
      fix: Declare empty observation on target.
    warnings: []
- id: lesson_sess_piper_language_nav_2
  timestamp: '2026-06-14T09:16:53.939661+00:00'
  session_id: sess_piper_language_nav
  phase: preflight_checking
  error_code: RUNTIME_PREFLIGHT_FAILED
  target_id: pipergo2_isaac_remote
  skillruntime_id: pipergo2_command_sim
  summary: 'EMPTY_OBSERVATION_INVALID: TARGETS.md targets[].observation expected explicit
    empty observation allowed, found multimodal'
  metadata:
    verdict: rejected
    session_id: sess_piper_language_nav
    target_id: pipergo2_isaac_remote
    skillruntime_id: pipergo2_command_sim
    runner_type: SessionRunner
    skill_runtime_kind: builtin
    execution_mode: builtin_command_loop
    missing_items:
    - code: EMPTY_OBSERVATION_INVALID
      field: TARGETS.md targets[].observation
      expected: explicit empty observation allowed
      found: multimodal
      triggered_by: sess_piper_language_nav
      fix: Declare empty observation on target.
    warnings: []
```
