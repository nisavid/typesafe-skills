# Recoverable single-judgment designs

This report compares recovery designs for [issue 25](https://github.com/nisavid/typesafe-skills/issues/25). It recommends a durable per-update claim plus a fail-closed recovery hold. This is a design recommendation, not approval, implementation, qualification, or activation.

## Established source facts

At [`00b05e5`](https://github.com/nisavid/typesafe-skills/tree/00b05e553d7c39287c93c9db23a9a2eae0551718), the controller checks source state, CI, review, and protection before permitting one Jev call, then reobserves the candidate before merge. Its binding covers `base`, `upstream`, `head`, `tree`, `policy_sha256`, and `questions_sha256`.

The adapter submits `ask` with model `jev-1.13.0`, `cache:false`, and `maxRetries:0`; binds the question, state, and response digests; and retains no durable provider request identifier. The inspected [TypeSafe API](https://docs.typesafe.ai/api.md) and [JavaScript SDK](https://docs.typesafe.ai/sdk/javascript.md) documentation contains no idempotency-key or prior-result retrieval contract. That bounded absence does not prove none exists.

Public [run 15](https://github.com/nisavid/typesafe-skills/actions/runs/38399857514) is completed/cancelled, attempt 1, at controller `74f958b`; its current attempt jobs inventory is empty. This does not establish that no matching job or provider execution existed historically.

GitHub documents create-ref and update-ref operations in its [Git references API](https://docs.github.com/en/rest/git/refs). `PATCH` with `force:false` enforces fast-forward movement but has no expected-old-SHA parameter. Documented status codes for create-ref do not, by themselves, qualify its collision behavior as a linearizable claim primitive.

## Comparison

| Design | Simultaneous contenders | Failure and recovery | Retention, reuse, and cost | Assessment |
|---|---|---|---|---|
| **A. Whole-history guard** | Matching visible, non-skipped jobs are treated as spent, but the read-and-decide sequence is not an atomic election at the outgoing-request boundary. | Visible cancellation or failure remains spent; missing, deleted, or expired history holds. A lost response cannot be recovered. | Depends on complete Actions history and repeated run/job enumeration. It stores no reusable judgment. | Conservative but operationally expensive and permanently coupled to history completeness. Run 15 shows why an empty current inventory cannot prove non-execution. |
| **B. Durable per-update claim** | An atomic `ready → claimed` transition elects one sender. All losers hold or reuse an already finalized result. | Once claimed, cancellation, runner failure, timeout, or a lost response consumes the attempt. A bound response may finalize to `result`; otherwise the record becomes terminal `uncertain`. | Constant-size lookup per proposal, small durable storage, and exact-binding result reuse. It sacrifices some judgments after failures to preserve the one-attempt rule. | Smallest viable reusable foundation, provided the store’s atomicity, non-deletion, authentication, and retention are qualified. |
| **C. Provider idempotency and retrieval** | A stable key could allow safe retries and retrieval despite concurrent callers. | Could close the external request/result gap if the provider guarantees one execution per key, rejects changed payloads, retains results long enough, and documents retry/error behavior. | Best recovery and potentially less human intervention. Billing and retention semantics also need a contract. | Not currently available from the inspected public contract. Keep as a conditional extension to B, not a present dependency. |
| **D. Serialization or human hold** | Serialization reduces ordinary overlap but does not durably consume an attempt across cancellation, restart, bypass, or record loss. | A human hold safely prevents another sample but cannot recover a lost result. | Low implementation cost, high operational blocking cost, and no automatic reuse. | Serialization alone is insufficient. An explicit hold is the correct fallback for B’s uncertain and legacy states. |

## Recommended minimum design

Provision one durable record for each explicitly authorized proposal revision before it can become eligible. Do not let a runner interpret a missing record as permission to create a fresh sample.

The record binds:

- A stable proposal identifier and explicit revision.
- The six existing binding fields.
- Canonical request bytes or their digest, model, adapter/canonicalizer versions, and gate configuration.
- Claim identity, fencing token, timestamps, terminal state, and authenticated audit data.
- For success, the exact response bytes or reusable normalized judgment plus the existing response digest.

Use this state machine:

1. `ready`: registered and never attempted.
2. Atomically compare-and-set `ready → claimed` before exposing the provider credential or calling the adapter.
3. Atomically finalize `claimed → result` when the exact bound response is durably stored.
4. Finalize an interrupted or indeterminate claim as `uncertain`. Never reset `claimed` or `uncertain` to `ready`.
5. Treat repeated finalization with the same response digest as idempotent. A conflicting digest, missing record, deletion, unauthorized change, expired retention, or store outage produces a hold.

This creates at most one application-level outgoing request attempt per registered revision. It does **not** atomically commit the external request with the local claim:

- **Outgoing client request:** at most one call crosses the local send boundary.
- **Provider execution:** unproven; the call may produce zero, one, or more internal executions without a provider contract.
- **Returned judgment:** zero or one response is accepted and durably bound locally; delivery may be lost after provider execution.
- **Reuse:** the stored judgment may be reused without another Jev request only for the exact immutable binding.

Changing any bound field invalidates reuse. It must not automatically create eligibility for another sample. A new judgment requires an explicitly registered revision under the eventual operator policy; changing incidental commit metadata, a workflow boundary, or a record name cannot clear a hold.

After a successful judgment but failed merge, rerun source parity, upstream ancestry, current-commit CodeRabbit approval, CI, branch protection, the pinned Jev 0.96 gate, and merge preconditions. Reuse the stored result when the binding remains exact. If the base or another bound field changed, hold pending an explicitly authorized revision.

Keep exact-old-SHA compare-and-swap separate from fast-forward validation. `force:false` answers whether the proposed ref update is fast-forward from the then-current ref; it does not establish that the ref still equals the previously observed SHA.

## Guarantee and trust boundaries

The guarantee depends on a qualified atomic conditional-write store, durable non-reusable proposal identities, deletion detection, authenticated append/finalization, and retention for as long as a proposal could reappear. Garbage collection is safe only after the proposal identifier is permanently ineligible; deletion must never make it look fresh.

The controller, record writer, canonicalization code, and credential boundary are trusted. Anyone able to call TypeSafe directly with the provider credential can bypass the claim. Anyone able to delete or rewrite records can defeat absence-based recovery unless deletion is independently detectable. Tokens and credentials must never enter the record; stored requests and responses need access controls matching their content.

The provider remains trusted for execution and answer integrity. Without a documented idempotency and retrieval contract, local durability cannot prove how many provider executions occurred or recover an executed response that was never returned.

## Legacy-attempt cutover

Keep production mode off during cutover.

Create terminal legacy records for every old binding known to have a prior non-skipped matching job. Classify incomplete, deleted, expired, or ambiguous history as `legacy-uncertain`, not `ready`. Run 15 belongs in this uncertain set unless stronger public evidence resolves it.

Establish a cutover epoch and allow claims only for explicitly registered post-cutover proposal revisions. Old unknown attempts must remain ineligible; shifting the Actions boundary, recreating the workflow, or assigning the same candidate a fresh incidental identifier must not permit another sample.

Before any separate activation decision, reconcile active old jobs, legacy tombstones, record-store durability, access controls, and backup restoration. The new guard replaces history as the future authority only after cutover; history remains evidence for constructing the legacy deny set.

## Exact unresolved decisions

1. Which backend supplies qualified linearizable conditional writes, immutable audit history, deletion detection, and required retention. GitHub create-ref is only a candidate until its concurrent collision semantics and protection model are qualified.
2. Which authority registers a proposal revision and which candidate changes constitute a new proposed update. The rule must exclude incidental metadata while requiring a new binding for changed evaluated content, policy, or questions.
3. Whether `policy_sha256` already commits to every model, adapter, canonicalizer, and Jev-gate input needed for safe reuse; otherwise those values need explicit binding.
4. How long records and reusable response content remain available, where backups live, and what sensitivity controls apply.
5. The exact legacy deny-set scope when old Actions history cannot enumerate a binding. The safe default is the full affected pre-cutover epoch.
6. Which mechanism supplies expected-old-SHA CAS for merge actuation. REST `force:false` alone does not.
7. Whether TypeSafe can provide a documented idempotency/retrieval contract covering concurrent identical keys, changed-payload conflicts, expiry, errors, retries, and billing. If verified, C may extend B; it does not change proposal authorization.

## Validation cases

**Focused tests**

- Race many contenders on one `ready` record; exactly one receives the fencing token and the outbound-call counter never exceeds one.
- Inject cancellation or failure before claim, after claim, before socket delivery, after delivery, after response receipt, and during finalization.
- Exercise duplicate identical finalization, conflicting finalization, missing/deleted records, unauthorized modification, expired retention, and store outage.
- Change each bound field independently; reject reuse and do not create a new eligible revision. Change incidental metadata; preserve the existing spent state.
- Reuse a stored result after merge CAS failure with an unchanged binding; reject reuse after base or policy change.

**Whole-command tests**

- Run two complete sync commands concurrently against a controlled store and fake provider; observe one application-level call.
- Terminate the winning process at each send/finalization boundary, restart the command, and verify `result` reuse or an `uncertain` hold without resend.
- Move the destination ref between observation and merge. Verify the exact-old-SHA CAS fails independently of the fast-forward result.
- Confirm source parity, ancestry, current-commit approval, CI, protection, and the pinned Jev gate still run on initial judgment and reuse paths.

**Hosted tests**

- In a disposable GitHub repository, race create operations for the proposed record backend and verify collision, visibility, protection, deletion, and restoration behavior from audit evidence.
- Cancel hosted jobs before and after a fake endpoint acknowledges delivery; verify no second call on rerun.
- Move a hosted branch between observation and `force:false` update, then repeat with the selected expected-old-SHA CAS mechanism to demonstrate the distinction.
- Dry-run cutover with synthetic complete, missing, and empty job histories, including the shape of run 15; every ambiguous legacy case must become terminal uncertain.
- Make no production Jev request during this qualification. Any future provider idempotency test requires separate authorization and a documented contract.
