# Single-judgment contract and uncertain attempts

The current controller holds every candidate that reaches judgment admission when any eligible workflow attempt lacks complete job history. That behavior is an implementation choice supporting the single-judgment rule; it is not the only recovery design permitted by the specification.

## Sources and scope

Controller and procedure source: [`00b05e553d7c39287c93c9db23a9a2eae0551718`](https://github.com/nisavid/typesafe-skills/tree/00b05e553d7c39287c93c9db23a9a2eae0551718). All nine prepared manifest entries matched their recorded sizes and SHA-256 digests. Supplemental construction and request code was read from that immutable public revision.

Requirements: [specification #10](https://github.com/nisavid/typesafe-skills/issues/10) and [research question #24](https://github.com/nisavid/typesafe-skills/issues/24). Live public run/job/check-suite records were read on 2026-10-16. Earlier publication outcomes and assessment inputs were inspected as retained evidence, without repeating their executions or publishing private receipts.

This is source and requirement investigation. No tests, Jev requests, workflow dispatches, or live-system changes were performed.

## Requirement, observation, and inference

| Class | What the evidence establishes | Limit or implication |
| --- | --- | --- |
| Governing requirement | The [specification](https://github.com/nisavid/typesafe-skills/issues/10) binds evidence to candidate inputs, output, and relevant policy; uncertainty holds; unknown remote outcomes must not be blindly retried. | It does not prescribe complete Actions history as the sole permissible implementation. |
| Maintained operating contract | The [procedure](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/docs/agents/upstream-sync.md#L59-L83) permits one uncached request, disables client retries, treats earlier non-skipped jobs for the same binding as consumed, and holds missing history. | These rules govern current execution. Investigation does not authorize changing them or obtaining another judgment. |
| Implementation choice | [`attempts.permit`](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/attempts.py#L86-L137) requires complete eligible run/attempt inventories before identifying previously consumed bindings. | Missing history on an unrelated eligible run blocks admission for every candidate reaching this guard. It does not block earlier no-op, disabled, or preliminary-hold paths. |
| Current observation | [Run 15](https://github.com/nisavid/typesafe-skills/actions/runs/38399857514) is completed/cancelled, attempt 1, at source `74f958b038d246087326759c89be236f01a64ad6`. Its current all-job, attempt-1-job, and bound-suite check-run inventories each contain zero records. | These are current inventories, not affirmative historical non-execution evidence. |
| Retained observation | Run 14’s retained result reports publication hold with `POST_PUSH_STATE_UNKNOWN` and `PUSH_FAILED`; its current job inventory shows preparation completed and finalization skipped. | Run success does not establish successful sync or Jev execution. The publication execution was not independently repeated. |
| Unsupported inference | Empty inventories, overlapping run times, or a cancelled conclusion prove run 15 never executed or issued a request. | None of the inspected evidence establishes that historical claim. It also does not prove a request occurred. |
| Bounded assessment input | Earlier Daybreak requests required preserving the single-request **and full-history** contracts; their results were `NEEDS_CONTEXT`. | Their conclusions concern recovery under those frozen premises. They are neither a clean review of another recovery design nor a requirement to contact Support. |

## Decisive traces

### Candidate and request binding

1. Each CLI invocation independently fetches and resolves the configured target base and upstream revision. The controller checks that the raw policy matches the selected base, hashes that policy and the question bytes, and constructs the candidate. [CLI](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/__main__.py#L83-L94), [controller](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/controller.py#L55-L77).
2. Candidate construction verifies admitted ownership and upstream tree parity. It fixes commit dates to one second after the later parent timestamp; commit identity therefore does not vary merely with wall-clock execution time. Author and committer identity still depend on Git configuration or permitted identity variables. The maintained workflow sets the same identity in both jobs. [Construction](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/git_candidate.py#L23-L33), [commit creation](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/git_candidate.py#L114-L121), [workflow](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/.github/workflows/upstream-sync.yml#L221-L249).
3. Only after publication and preliminary hosted gates pass does preparation return the SHA-256 digest of `{base, upstream, head, tree, policy_sha256, questions_sha256}`. Finalization independently reconstructs this binding and requires its current Actions job to be named `Jev <digest>`. [Controller](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/controller.py#L78-L97), [guard](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/attempts.py#L64-L85).

Thus preparation does not freeze base/upstream inputs for finalization. Movement between phases changes the reconstructed binding; the current job-name check then prevents admission under the earlier digest. This is a source-derived failure path, not a newly executed test.

The judgment adapter validates the pinned model/question, rejects binary or oversized state, and submits the complete bounded diff plus explicit obligations. Its runner makes one evaluator invocation with `cache: false` and `maxRetries: 0`. Transport and response-validation failures hold; a lost response does not establish whether the remote request executed. [Adapter](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/jev.py#L19-L88), [runner](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/tools/jev/judge.mjs#L1-L27).

### Cancellation, rerun, and recovery

`permit` verifies the current workflow/run/job, contiguous run numbers from the approved boundary, every eligible rerun, and agreement between all-job and per-attempt snapshots. An empty attempt list raises `attempt_history_incomplete` before candidate-binding comparison; caught failures become `jev_attempt_unconfirmed`. A previous matching job other than completed/skipped yields `jev_attempt_consumed`. [Guard](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/fork_sync/attempts.py#L86-L137).

Consequently, run 15’s empty attempt inventory produces the unconfirmed path under the current implementation. It does **not** classify run 15 as consumed. A later candidate with a different binding still encounters the same incomplete-history condition.

A previous non-skipped matching job consumes admission even if it failed before the request, timed out, was cancelled, returned a negative judgment, or accepted before a failed merge. Current recovery deliberately favors conservative consumption over proving exactly where execution stopped. It does not reuse prior judgment evidence. Repeating finalization inside the same running job is outside the supported procedure and would not create another Actions attempt record. [Operating contract](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/docs/agents/upstream-sync.md#L71-L75).

## Unresolved facts and recovery implications

- Run 15’s historical request effects remain unknown. The fresh empty inventories preserve that uncertainty.
- The earlier concurrency assessment lacked continuous historical evidence that run 15 remained pending, or that another run continuously excluded it. Point observations and overlapping timestamps did not close that gap.
- Recovery must define which proposed updates share one judgment entitlement. Current identity includes the candidate commit and complete raw policy digest; identical content alone is insufficient. Changes to identity configuration or policy bytes can change that binding.
- Supported inputs remain the admitted mirror-fork ownership, anchor, paths, bounded textual diff, obligations, pinned question/model, and hosted gates. Findings do not extend to arbitrary forks, unsupported content, or out-of-band requests. [Supported scope](https://github.com/nisavid/typesafe-skills/blob/00b05e553d7c39287c93c9db23a9a2eae0551718/docs/agents/upstream-sync.md#L5-L17).
- The separate human decision can reconsider how admission and uncertain attempts are recorded. It must preserve original evidence and unknown effects, define any changed safety claim explicitly, and obtain independent review and validation of the selected design. The previous assessment prompts cannot substitute for that decision.
