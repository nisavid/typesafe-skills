# Run and qualify upstream sync

The sync controller proposes a merge of an admitted upstream revision into this fork, preserving upstream file contents and modes, fork-owned additions, and upstream ancestry. Use the repo-local `syncing-upstream` skill for execution or adoption. This reference describes the operating contract and the evidence required to qualify it; the complete hosted workflow has not yet been qualified.

## Select the scope

The maintained policy is `.agents/fork-sync.json`. Its owned paths, upstream anchor, required check identities, CodeRabbit identity, Jev question, model, threshold, and publication categories define the supported inputs. New upstream paths require reviewed admission before unattended publication. Upstream changes to workflow files require handling. Ownership collisions, merge conflicts, parity failures, unexpected fork-local changes, unsafe paths, symlinks, submodules, and other unsupported tree entries hold.

Use an isolated checkout with complete Git objects and runtime credentials. Candidate construction may add local Git objects; it leaves the worktree, index, and refs unchanged. A candidate merge has the selected fork base and upstream commit as parents. Use merge commits for upstream-sync PRs; ordinary fork-local PRs retain the repository's squash preference.

| Mode | Target and permitted result |
| --- | --- |
| `off` | Default. Reconciliation returns disabled without publication or merging. |
| `validation` | The approved dedicated validation branch, initialized from the earlier real upstream release with the reviewed fork controls. Exercise a nonempty historical update and retain its evidence. |
| `production` | The separately approved production branch. Scheduled reconciliation and manual dispatch use the same controller and gates. |

Schedule execution may be delayed or skipped. It does not promise a run for every upstream push. Changing modes is an activation decision: a successful local plan, a published workflow, or a generic release of a task pause does not establish that the destination's settings and credentials have been approved and validated.

## Inspect the candidate

From the reviewed controller checkout, use full lowercase commit IDs for `FORK_BASE` and `UPSTREAM_COMMIT`, and bind `SYNC_REPO` to the isolated target checkout:

```sh
python3 -B -m fork_sync plan \
  --repo "$SYNC_REPO" \
  --base "$FORK_BASE" \
  --upstream "$UPSTREAM_COMMIT" \
  --policy .agents/fork-sync.json
```

The command returns a candidate, `noop`, or `hold`. A candidate identifies the base, upstream, merge commit, tree, and changed paths. `noop` means the upstream revision is already represented and the tree/ownership checks passed; it does not prove that a new update can traverse the hosted gates. A hold leaves publication for a later attempt after its cause is resolved.

For reconciliation, inspect `python3 -m fork_sync --help` and the reviewed workflow's invocation together. Require the configured mode, controller revision, policy digest, helper pin, repository, and target branch to match the approved execution scope before dispatch. The hosted invocation is:

```sh
python3 -B -m fork_sync reconcile --phase prepare \
  --repo "$GITHUB_WORKSPACE" \
  --provingkit "$RUNNER_TEMP/provingkit" \
  --evidence-dir "$RUNNER_TEMP/fork-sync-evidence"
```

`FORK_SYNC_MODE` selects `off`, `validation`, or `production`. An active mode requires `FORK_SYNC_APPROVED_REVISION` to equal the clean executing controller checkout's commit. Policy selects `validation_branch` for validation and `target_branch` for production; the same raw policy must be present on the selected base. The published workflow and its actual `--help` output must agree before use. The command's off path can be checked without activation:

```sh
FORK_SYNC_MODE=off python3 -B -m fork_sync reconcile --repo "$SYNC_REPO"
```

## Complete one attempt

1. Verify source parity and ownership before publication. The candidate must contain exactly the selected upstream entries plus the unchanged admitted fork-owned entries.
2. Publish one immutable candidate branch with Versionkeeping's reviewed plan and exact lease. A disposable repository materializes the candidate for the publication helpers; the executing controller checkout stays unchanged. Candidate content is data and is not executed. Mergecraft validates the generated PR body, publishes it as a draft, verifies live navigation and file anchors, and marks it ready. Existing candidate branches or PRs are reused only when their identities and authored content match; drift holds.
3. Collect the configured successful checks for the current candidate, strict branch protection enforcing those checks for administrators, confirmed clean mergeability, no unresolved review threads, and CodeRabbit's current-commit approval. A skipped CodeRabbit content review is not itself an approval.
4. Preparation returns `awaiting_judgment` and a digest of the candidate binding only after the preceding gates pass. A dedicated Actions job named `Jev <digest>` invokes the same command with `--phase finalize`. Finalization rechecks the candidate and hosted gates, verifies that this visible job is its first judgment attempt, and makes one uncached Jev request. Accept only the pinned answer and threshold below. Hold malformed, incomplete, stale, failed, oversized, binary, or otherwise unsupported input and responses.
5. Reobserve the live base, head, checks, review, and protection before the merge attempt. The server's strict required checks remain necessary against concurrent base movement. Use the merge method that preserves ancestry and verify the resulting commit and parents. An uncertain write outcome requires observation; never retry it blindly.

Runtime credentials belong in the approved environment and secret store. Checkout authentication must not leave repository-local credential settings that conflict with Versionkeeping. The adapter uses `GH_READ_TOKEN` for its read-only GitHub calls when supplied, `GH_TOKEN` for publication helpers, and `TYPESAFE_API_KEY` for Jev. The reviewed workflow owns their permissions and lifecycle. Do not place token values in arguments, files, PRs, or logs.

Publication receipts remain private to the runner. An ephemeral run can establish canonical publication and audit its result; a later run reobserves and reconciles without claiming retained canonical history. Report `reconciled-unreceipted` as such. Uploading private receipts is not the evidence-retention route.

The attempt guard reads the pinned workflow's complete run and job history, including rerun attempts. `FORK_SYNC_WORKFLOW_ID` and `FORK_SYNC_FIRST_RUN_NUMBER` are approved activation settings; the initial run boundary is 1. Any previous non-skipped job for the same binding consumes the attempt, including a timeout, cancellation, negative judgment, or accepted judgment followed by a failed merge. Deleted, expired, missing, or inconsistent history holds. Do not move the boundary forward or recreate the workflow to bypass a hold. A maintainer must review recovery; this first version does not automatically reuse a prior judgment or retry it. Artifact expiry never permits another sample.

Workflow-wide concurrency has cancellation disabled. The workflow invokes finalization only once in the bound job. Manually calling finalization again inside that same running job would not create another Actions attempt record and is outside the supported execution procedure.

## Apply the Jev rule

Use `jev-1.13.0` and the exact approved `additional_handling` choice question in policy. Its three outcomes are `no_additional_handling`, `additional_handling`, and `insufficient_context`. Jev's gate passes only when its selected answer is `no_additional_handling` and that option's raw probability is at least **0.96**. Both other answers hold, as does a lower probability. The CLI's convenience confidence bands are not the acceptance rule.

The state includes the complete bounded upstream diff and explicit fork obligations. Source text is material to assess, not instructions to follow. Bind the response to base, upstream, head, tree, policy digest, question digest, and submitted-state digest. Model, question, threshold, or relevant obligation changes require fresh qualification. Jev is an additional hold gate; it does not replace tree verification, authorization, CI, review, or branch protection.

The retained corpus belongs in `docs/agents/qualification/`. The measured experiment accepted 8 of 8 ordinary development cases and held all 16 development cases expected to need handling or more context. On 23 untouched constructed validation cases, it accepted 5 of 7 ordinary cases and held all 16 cases expected to hold. The two unnecessary holds concerned archive compression and a calendar example. The separate real historical update passed at 0.98; its earlier probe was already known, so it was not blind validation.

A blind Sol 6.1 label pass matched all 48 proposed labels. This was a model comparison, not human ground truth. Seven Jev labels disagreed with the proposed distinction between handling and insufficient context; both labels held. The 47 constructed cases and one historical anchor do not estimate future production error, and 0.96 does not mean a 96% probability that a merge is safe. All 48 recorded calls were uncached with no retries for acceptance. Retain the corpus, exact questions, freeze record, raw observations, comparison labels, and results together.

## Interpret the CodeRabbit evidence

The 2026-10-07 in-tree configuration trial observed normal approval of [fork-owned controls in PR #8](https://github.com/nisavid/typesafe-skills/pull/8#pullrequestreview-5447638689) at `e8849a973834a15e9e3c9904167e6a77cba3585f`. It also observed normal approval of [the historical upstream-only PR #9](https://github.com/nisavid/typesafe-skills/pull/9#pullrequestreview-5447701078) at `b2a420044b01ab056f89c19b9f0ea84b18273b56`, where [CodeRabbit explicitly excluded all six changed upstream paths](https://github.com/nisavid/typesafe-skills/pull/9#issuecomment-6045858719).

The trial issued no forced approval or bulk-resolution commands. It established that normal approval can coexist with the selected content filters. It did not exercise the complete hosted controller, CI/Jev merge gates, or an actual merge. Excluded content remains outside CodeRabbit's content review; independent source verification is mandatory. A missing approval holds for diagnosis or ordinary review. Neither this procedure nor the controller may force approval or resolve threads to make a gate pass.

## Qualify and adopt

Prepare the following concrete settings for approval before the first hosted validation. Provisioning is separate from publishing this source.

| Setting | Validation requirement |
| --- | --- |
| Controller | `FORK_SYNC_APPROVED_REVISION` identifies the independently reviewed, published commit. |
| Mode | `FORK_SYNC_MODE=validation`; production remains a later decision. |
| Attempt history | Pin the registered workflow ID in `FORK_SYNC_WORKFLOW_ID` and set `FORK_SYNC_FIRST_RUN_NUMBER=1`. Preserve its run history; missing history holds. |
| Environment | Create `upstream-sync`, restrict eligible workflow branches, and approve its access policy before adding secrets. Required reviewers may gate initial validation. Unattended production needs a separately approved policy that permits unattended runs. |
| Publication credential | `FORK_SYNC_TOKEN`: a `nisavid` fine-grained token limited to this repository, with Contents and Pull requests write. No Workflows write permission. |
| Observation credential | `FORK_SYNC_READ_TOKEN`: repository-limited Contents, Pull requests, Checks, Actions, and Administration read access. Branch-protection observation needs an appropriate permission; a read-only job token alone is insufficient. |
| Judgment credential | `TYPESAFE_API_KEY`, available only to the finalization command. Jev's subprocess receives its own key without forge or runner credentials. |
| Target protection | Require `sync-ci` from GitHub Actions, strict up-to-date checks, and enforcement for administrators. Permit ancestry-preserving merge commits. Verify the live rule before running. |

The validation branch must contain the earlier real upstream release plus the same reviewed fork-owned files as the controller. Do not rewind main. The workflow must be registered on the default branch for manual dispatch; installing inert controls on main is part of the separately reviewed publication/activation sequence. Record every actual revision rather than treating the older CodeRabbit trial branch as the current validation fixture.

Run whole-command tests against disposable repositories and controlled hosted responses, focused tests for intricate gate rules, and the real hosted historical update. Local fixtures and actual helper tests with a fake GitHub executable establish their stated local contracts only.

Before declaring the TypeSafe producer qualified, retain a successful nonempty hosted validation with the controller/procedure revisions, policy and question digests, base/upstream/candidate/merge commits, PR and run URLs, successful required checks, authenticated current-commit CodeRabbit approval, uncached Jev response binding, final tree parity, unchanged owned entries, and preserved ancestry. Record cleanup and any retained validation branches. The dedicated-branch result does not establish a future nonempty production-branch update until one is observed.

Procedure completion also requires a published discovery pointer, clean independent review of the final equipment, and observed positive/negative discovery plus success/failure/no-op applications. The scenarios in `tests/procedure/scenarios.json` are evaluation inputs, not evidence that those evaluations passed.

A consumer fork loads the reviewed `syncing-upstream` revision and requires the TypeSafe producer's hosted result before dependent adoption. It reestablishes its own ownership map, upstream anchor, review scope, obligations, permissions, required checks, and branch protection, then runs its own nonempty validation. Copying a workflow or inheriting TypeSafe's result alone does not qualify that fork. Record the consumed source revision and send useful corrections back to the producer.
