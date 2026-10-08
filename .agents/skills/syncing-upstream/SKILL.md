---
name: syncing-upstream
description: Use when planning, running, diagnosing, or qualifying this TypeSafe fork's upstream sync, or adopting its reviewed sync procedure in another fork. Do not use for ordinary fork-local edits, upstream product usage, or unrelated PR reviews.
---

# Syncing upstream

Reconcile an admitted upstream revision while preserving upstream bytes, fork-owned additions, and upstream ancestry. This is repo-owned equipment for the TypeSafe producer; adoption elsewhere requires the producer evidence and destination-specific checks below.

## Establish the run

1. Read [the operating reference](../../../docs/agents/upstream-sync.md), the repository's `AGENTS.md`, `.agents/fork-sync.json`, and `.agents/fork-ops.toml`. Record the procedure and controller revisions, policy digest, repository, target branch, and selected mode. Verify the active authorization before any external action; loading this skill grants none.
2. Use `fork-ops` for its supported inspection/configuration operations and `checkpointing-and-publishing-git-work` for Git work. Resolve the full base and upstream commit IDs in a complete isolated checkout. Continue only when the configured upstream anchor belongs to both histories and the ownership policy covers every fork addition.
3. For implementation or policy changes, use `tdd`; review the final authored commit through Tricritical before publication. For recurring verified upstream-only changes, apply the approved recurring-sync exception: the maintained controls receive Tricritical review, while every candidate still needs source verification, CI, Jev, and normal current-commit CodeRabbit approval.

## Reconcile or diagnose

4. Invoke the command for the selected mode in the operating reference. Use the reviewed controller and pinned helper dependency. `off` ends disabled; planning can construct local objects but publishes nothing. Validation targets the dedicated historical branch; production targets the separately approved branch.
5. Read the structured result. A verified `noop` ends without a new PR or merge. A `hold` identifies unmet evidence or an unsupported input: investigate that cause, preserve the candidate, and rerun only after the cause changes. An `unknown` outcome requires live observation before any further write. Do not turn missing evidence into success, change gates to obtain a pass, or retry a model call until it accepts.
6. Let Versionkeeping publish the immutable candidate branch and Mergecraft create its PR and mark it ready. Reuse only the same candidate with preserved authored text; collisions or text drift hold. Live HTML checks establish navigation structure and file anchors for changed files, or complete commit links for history-only candidates. They do not establish visual layout. Keep private publication receipts out of repository files and uploaded artifacts; report reconciliation honestly when a later run lacks canonical receipts.
7. Accept Jev only under the pinned policy described in the operating reference. Wait for normal CodeRabbit approval and resolved findings. Never issue forced approval or bulk-resolution commands. Fresh policy, base, head, or question bytes require fresh affected evidence. Merge only through the reviewed controller after its final live checks, preserving upstream ancestry.

## Qualify and hand back

8. For producer qualification, run the combined test suite and the real nonempty historical update on the dedicated validation branch. Verify the merged tree, both histories, unchanged fork-owned entries, required CI, Jev response binding, and CodeRabbit approval of the reviewed candidate. Also verify GitHub accepts a history-only PR and CodeRabbit approves its current commit normally. Retain the run and PR links with the actual commit IDs. Local fixtures, a no-op, and the earlier CodeRabbit-only trial do not complete this step.
9. For another fork, first require the TypeSafe producer's reviewed, published procedure and successful hosted result. Record the exact source revision consumed. Reestablish destination ownership, upstream anchor, credentials, required checks, branch protection, review filters, fork obligations, and activation authority. Make its own nonempty hosted validation pass before enabling scheduled production; TypeSafe evidence alone is not destination qualification.
10. Report the mode, input/candidate/merge IDs, result, evidence links, and remaining holds. Procedure capture completes only after its maintained source and discovery pointer are published, independent review and behavior evaluation are current, and the consumer can locate the reviewed revision. Return useful corrections to this source through the owning task.
