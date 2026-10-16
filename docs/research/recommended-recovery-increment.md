# Recommended attempt-recovery increment

I recommend replacing the global Actions-history admission check with a durable, per-update claim and retained judgment. This recommendation joins [the contract investigation](https://github.com/nisavid/typesafe-skills/issues/24) with [the design comparison](https://github.com/nisavid/typesafe-skills/issues/25). It is a proposal for the [human design decision](https://github.com/nisavid/typesafe-skills/issues/26), not an accepted operating procedure.

## What the investigations establish

The current guard requires complete history for every eligible run before comparing candidate bindings. Missing history on an unrelated eligible run therefore holds later candidates reaching that guard. Complete Actions history is the maintained mechanism, not the only design consistent with the governing single-judgment requirement. Current run 15 records do not prove either execution or non-execution.

The existing candidate commit dates are deterministic. A claim that wall-clock time alone changes the candidate identity would be incorrect. Preparation and finalization do independently fetch their inputs; input movement changes their binding and holds admission under the earlier job digest.

Daybreak's [design comparison](recoverable-single-judgment-design.md) recommends a durable claim with an uncertain-outcome hold. Its input was a frozen packet of public source and primary documentation. The returned report is preserved without edits. This is design research, not independent security approval of a final implementation.

## Proposed behavior

1. Register each eligible proposed update under an approved policy. Keep its identity separate from incidental commit metadata, workflow attempts, and record names. Ordinary scheduled updates should be registerable automatically under that standing policy; a human decision on every normal sync would defeat the intended workflow.
2. Bind the exact candidate, evaluated request, model, questions, relevant policy, adapter, and interpretation rules to that proposal. A changed binding invalidates reuse but does not itself grant another judgment entitlement.
3. Durably and atomically consume the entitlement before making the one outgoing request. Competing or repeated invocations cannot consume it again. Do not release a consumed entitlement after a timeout, cancellation, or restart.
4. Retain the validated response and its binding. If merge fails while that binding remains unchanged, reuse the recorded judgment without another request, and rerun the live source, review, CI, protection, and merge gates.
5. Hold a claimed update whose response is missing or indeterminate. A crash before delivery may waste an entitlement; a crash after delivery may lose a judgment. Neither permits an automatic resend. Missing, deleted, conflicting, or rolled-back journal state also holds.
6. Preserve legacy uncertainty through a reviewed cutover. Quarantine updates that might overlap old unknown attempts. A new workflow boundary, ledger namespace, candidate author, or policy digest cannot make the same update fresh.

The supported claim is **at most one application-level outgoing request attempt per admitted proposal revision**. It is not exactly-once provider execution. A durable local claim cannot determine whether an unanswered remote request executed, and it cannot recover a response the provider never returned. Provider-supported idempotency and retrieval remain a possible later extension; the inspected public TypeSafe documentation does not establish that contract.

## Storage recommendation and remaining decisions

Keep the controller logic behind a small conditional-write journal interface suitable for future Fork Ops reuse. Investigate a protected Git-backed journal using expected-old-SHA updates first, because the workflow already has a repository-limited App and guarded Git publication equipment. Do not provision another service yet.

That backend is a candidate, not a qualified guarantee. The accepted plan must establish concurrent-writer behavior, protection against deletion and rewrites, who can register or finalize records, credential boundaries, retention, and detection of stale restoration. GitHub REST `force:false` is a fast-forward check, not an expected-old-SHA compare-and-swap. If the repository cannot supply the required journal behavior, choose a conditional-write backend that can; do not weaken the claim to fit the store.

The human design decision must settle the automatic-registration rule, which semantic changes create a new proposal revision, legacy quarantine scope, reuse policy, and backend qualification plan. Security review must cover the controller and credential trust boundary: direct use of the TypeSafe credential outside the controller is not prevented by a journal.

The design report also raises destination-ref concurrency during merge. Preserve the existing strict branch protection and merge checks; determine whether an additional mechanism is necessary for this recovery increment rather than treating REST fast-forward behavior as proof of a new merge defect.

## Implementation and acceptance sequence

After the human decision, independently review the selected design and plan through [the recovery review](https://github.com/nisavid/typesafe-skills/issues/27). Implement only after that review and the applicable execution gates.

- Qualify the selected journal primitive in isolation with concurrent contenders, record deletion, unauthorized writes, outage, and stale restoration. Observing one successful create is insufficient.
- Use focused tests for proposal identity, binding changes, duplicate/conflicting finalization, legacy quarantine, and claim/result transitions.
- Use whole-command tests with disposable repositories and a controlled provider to interrupt execution before and after claim, delivery, response receipt, and result persistence. Assert the outgoing-call count and the resulting hold or reuse decision.
- Verify that result reuse still requires source parity, upstream ancestry, CI, normal CodeRabbit approval of the current commit, branch protection, and the pinned Jev acceptance rule.
- Update the maintained `syncing-upstream` skill and `docs/agents/upstream-sync.md` with the accepted method, cutover, rollback, and evidence requirements. Keep the source revision discoverable for downstream Fork Ops and Matt Pocock consumers.
- Review and adjudicate the final implementation independently, including security and the governing safety premises. Then separately authorize and run the nonempty supervised hosted validation on the dedicated branch.

No tests or hosted qualification were run for this proposal. No new Jev request, boundary change, credential change, Support contact, or activation was performed. Production remains off. Run 15 remains an unresolved legacy attempt; this recommendation does not clear it.
