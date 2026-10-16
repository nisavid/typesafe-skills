# Recover interrupted upstream-sync judgments

The controller will record one durable judgment attempt for each proposed upstream update and reuse a saved judgment when its evidence remains unchanged. An interrupted attempt without a saved judgment stays spent. This permits later, genuinely different updates to progress without treating missing Actions history as a global veto.

This is the accepted [recovery design and implementation/validation plan](https://github.com/nisavid/typesafe-skills/issues/26). [Independent review](https://github.com/nisavid/typesafe-skills/issues/27) is required before implementation. Acceptance does not change the installed controller or authorize provisioning, a hosted run, or production activation. Production stays off.

## Supported claim and scope

The supported claim is **at most one application-level outgoing Jev request attempt per admitted proposed update**. A claim can be consumed without a request being delivered. A delivered request can lose its response. This does not establish exactly-once execution inside the provider.

The initial scope is this mirror fork, its approved target and historical validation branch, admitted upstream files, bounded textual input, and existing fork obligations. Preserve upstream bytes and ancestry, ownership checks, CI, normal CodeRabbit approval of the current candidate, branch protection, and the pinned Jev question, model, and 0.96 acceptance threshold. Keep unsupported trees, ownership collisions, conflicting inputs, and malformed or oversized responses on the hold path.

The trusted boundary includes the reviewed controller, journal writer, request and response interpretation code, GitHub and its configured protection, and the approved credential environment. The journal governs calls made through the controller. It cannot prevent someone who already possesses the provider credential from calling the provider separately. Qualification must state this boundary and must not claim protection against a malicious administrator merely from branch protection.

## Update identity and judgment evidence

A proposed update brings one admitted fork branch from upstream revision A to upstream revision B. Workflow attempts, PR names, candidate merge metadata, and journal record names do not reset its attempt. Moving or renaming a validation fixture does not escape a prior uncertain attempt.

For a held starting revision A, a later proposal is new only if its actual upstream change set differs from every previously claimed proposal from A. Compare net file contents, paths, and executable modes deterministically; do not ask another model whether a change is substantial. A documentation correction counts. New commit identifiers, empty commits, or a return to an already-assessed change set do not count. A genuinely new proposal may include changes from an earlier held proposal; preserve both records. After a successful update advances the starting revision, ordinary history-only updates remain supported.

Keep this eligibility identity separate from the complete evidence binding. The binding must cover the selected base, upstream, candidate commit and tree, exact request and question, model, fork obligations, acceptance policy, and relevant adapter, canonicalization, and response-interpretation versions. A changed base, model, policy, question, or interpretation does not itself grant another attempt. It invalidates reuse of the old judgment.

Use the terms in [the glossary](../../GLOSSARY.md). The availability tradeoff is recorded in [the durable-claim decision](../adr/0001-durable-update-claims.md).

## Claim, record, and reuse

The trusted controller registers eligible updates under the accepted policy. Registration must consult the intact authoritative journal and the legacy exclusions; an absent individual record is not sufficient evidence of a fresh update.

1. Register an eligible, unattempted update and its complete evidence binding.
2. Atomically claim that registered update. Only one competing invocation can win. Give the judgment adapter its credential only after successful claim confirmation. Existing workflow serialization remains useful, but the durable transition owns request admission.
3. Make one outgoing request, with caching and client retries disabled. A restart, cancellation, timeout, or lost claim acknowledgment cannot authorize another send.
4. Persist the complete reusable judgment and its binding under the original claim. The stored representation must retain all validated decision inputs and provider precision needed to reproduce the acceptance decision. Credentials, headers, and unrelated provider metadata do not belong in it.
5. Repeated storage of the identical bound result may succeed without another request. A conflicting result, missing evidence, or interrupted claim without a retained result holds. There is no transition that resets a spent claim.
6. Reuse a saved judgment only when the entire binding is unchanged. Rerun every live source, CI, normal current-commit review, protection, and merge check. A retained passing judgment is never permission to skip those checks.

Result recovery is recovery of already retained evidence, not another provider request. A manual merge or a future policy exception is outside this automatic recovery path. Any such proposal needs its own explicit decision.

## Journal qualification

Investigate a protected Git-backed journal in the existing repository first, behind a small interface for registration, conditional claim, result finalization, and observation. This selects an investigation direction, not a deployed backend.

Before selection, establish with evidence:

- One winner under competing writers, including lost acknowledgments and restarts. Fast-forward movement alone is not proof of an expected-old-value conditional write.
- Authenticated writes with the minimum required credential access. Ordinary workflow credentials cannot delete or rewrite authoritative history. If additional App permissions or protection settings are needed, present the concrete changes for approval.
- Detection of missing, conflicting, truncated, or stale-restored records. Restoring an older backup cannot silently enable a second request. Distinguish ordinary writer protections, operator restoration procedures, and assumptions about the storage provider.
- Retention of claims and reusable judgments for the repository lifetime, without automatic expiry, garbage collection, or reset. Retiring or migrating the repository must preserve the spent identities before any replacement can resume.
- Complete, bounded, secret-free result storage appropriate to the repository's visibility. Derived indexes must not turn missing authoritative evidence into permission.
- Hold behavior during outage or uncertainty, and an explicit recovery procedure that restores evidence without resetting attempts.

If the Git backend cannot meet these requirements within the agreed trust boundary, return with another backend choice before provisioning it. Do not weaken the requirements to fit Git. Keep provider idempotency and result retrieval as a possible later extension requiring an established provider contract.

## Legacy cutover and rollback

Run 15's historical effects remain unknown. Preserve its original records and all prior run evidence. Before cutover, use the old workflow revisions, policy, retained observations, and upstream history to conservatively identify every proposal that an uncertain old attempt could have assessed. Mark those proposals spent; known consumed attempts also remain spent. Missing jobs are not evidence that a request never happened.

Reconcile old execution before admitting new requests. If the affected scope cannot be bounded, keep that branch held. A changed workflow boundary, policy digest, branch name, or fixture cannot clear the old uncertainty. Genuinely different proposals may proceed only after the exclusion scope and registration rule establish their eligibility.

Keep production off during cutover. Install the reviewed journal, legacy records, controller, and procedure as one consistent admitted revision before selecting validation mode. Record the actual source and journal revisions used. Preserve the previous controller and evidence for diagnosis.

Rollback first returns sync to off and preserves all journal data and legacy exclusions. An older controller that ignores those records cannot safely resume merely because its code was restored. Any replacement must honor the existing spent attempts before execution resumes.

## Implementation increments and acceptance

The implementation starts only after the accepted plan receives independent review. Use `tdd` and the combined test boundary: whole-command behavior tests, focused intricate rule tests, and separately approved hosted qualification.

| Increment | Completion evidence |
| --- | --- |
| Qualify storage and bound legacy uncertainty | Concurrent-writer, interruption, protection, retention, missing-record, and stale-restore evidence; a reviewed legacy exclusion set or a precisely scoped hold. Hosted experiments use a separately approved disposable surface and controlled provider, without a Jev request. |
| Implement identity, claim, and reuse | Focused tests show stable identity, deterministic change-set comparison, exact evidence binding, one winning claim, duplicate-result handling, conflicting-result holds, and no reset after interruption. |
| Integrate the whole command and cutover | Disposable-repository tests count outgoing calls across competing commands and interruption before claim, after claim, before and after delivery, after response receipt, and during persistence. Restart yields either reuse or hold without resend. Test base/input drift, legacy exclusions, rollback, storage loss, and all existing approval and merge gates on both first-use and reuse paths. |
| Capture and review the procedure | Update `.agents/skills/syncing-upstream/SKILL.md` and `docs/agents/upstream-sync.md`, their discovery and evaluation cases, and the exact fork-owned inventory. Independent Tricritical review and adjudication, including the required security route, must be clean on the final revision and its relevant dependencies. |
| Qualify the hosted workflow | Obtain approval for the concrete controller, journal, fixture, credentials/protection changes, and environment gates. Complete a genuinely eligible nonempty real upstream update on the dedicated validation branch, plus the required history-only publication/review case. Verify tree parity, unchanged fork-owned entries, ancestry, CI, normal current-commit CodeRabbit approval, retained Jev binding, and the authenticated merge. Return mode to off. |

During design review, examine destination movement between the last observation and merge. Preserve the existing strict protection and final checks; do not describe a fast-forward API as expected-old-SHA comparison. Any additional merge mechanism found necessary becomes an explicit, reviewed part of the implementation before claiming the safety argument complete.

The current historical fixture is not automatically eligible for another judgment. Select a concrete genuinely different real update only after the legacy scope is established, and present it with the hosted validation plan. If no suitable historical case exists, report that limitation; controlled tests and a no-op do not substitute for the nonempty hosted result.

The design documents can be published for review on their planning branch. Before landing them into an executing controller revision, admit their paths through the reviewed fork-owned inventory change. Their publication alone changes neither that inventory nor the operating contract.

## Procedure handoff and later work

Use `capturing-agent-procedures` to make the repaired method executable by the next agent. Capture supported inputs, registration and claim steps, result reuse, refusal cases, legacy cutover, restoration and rollback, credential boundaries, and observable completion evidence. Evaluate positive and negative discovery plus success, failure, and no-op application; fixture definitions alone are not passed evaluations.

The Matt Pocock consumer and future Provingkit Fork Ops work must locate the reviewed producer revision and its hosted result before dependent adoption. They must establish their own ownership, obligations, credentials, protection, and validation; this mirror-fork plan does not qualify transformed or adapted forks. Keep independent work unblocked and preserve the existing dependency on TypeSafe qualification.

Production activation, provider-side exactly-once guarantees, a provider retry facility, generalized transformation rules, and migration into generic Fork Ops remain separate work. No Support inquiry is needed to decide or implement this recovery method.

## Evidence

- [Contract and uncertain-attempt investigation](https://github.com/nisavid/typesafe-skills/blob/12f1a9d4a3e357e9f87ec65838d2111ca3a6fb3f/docs/research/single-judgment-contract.md).
- [Independent recovery-design comparison](https://github.com/nisavid/typesafe-skills/blob/2e7b213a456869d11a3c3e087561f9ca82aeb952/docs/research/recoverable-single-judgment-design.md).
- [Joined recommendation](https://github.com/nisavid/typesafe-skills/blob/2e7b213a456869d11a3c3e087561f9ca82aeb952/docs/research/recommended-recovery-increment.md).
- [Source examined for this plan](https://github.com/nisavid/typesafe-skills/tree/00b05e553d7c39287c93c9db23a9a2eae0551718).

These are design and source evidence. They are not storage qualification, implementation tests, or a successful hosted recovery.
