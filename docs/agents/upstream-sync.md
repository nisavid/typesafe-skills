# Run and qualify upstream sync

The sync controller proposes a merge of an admitted upstream revision into this fork, preserving upstream file contents and modes, fork-owned additions, and upstream ancestry. Use the repo-local `syncing-upstream` skill for execution or adoption. This reference describes the operating contract and the evidence required to qualify it; the complete hosted workflow has not yet been qualified.

## Select the scope

The maintained policy is `.agents/fork-sync.json`. Its owned paths, upstream anchor, required check identities, CodeRabbit identity, Jev question, model, threshold, and publication categories define the supported inputs. New upstream paths require reviewed admission before unattended publication. Upstream changes to workflow files require handling. Ownership collisions, merge conflicts, parity failures, unexpected fork-local changes, unsafe paths, symlinks, submodules, and other unsupported tree entries hold.

Use an isolated checkout with complete Git objects and runtime credentials. Candidate construction may add local Git objects; it leaves the worktree, index, and refs unchanged. A candidate merge has the selected fork base and upstream commit as parents. Use merge commits for upstream-sync PRs; ordinary fork-local PRs retain the repository's squash preference.

| Mode | Target and permitted result |
| --- | --- |
| `off` | Default. Reconciliation returns disabled without publication or merging. |
| `validation` | The approved dedicated validation branch, initialized from the earlier real upstream revision with the reviewed fork controls. Exercise a nonempty historical update and retain its evidence. |
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

New upstream history with unchanged files remains a candidate. An empty commit or a change followed by its reversal must preserve ancestry through publication and the ordinary merge gates. The publisher observes the complete new commit list, proves the fork base is an ancestor of the candidate and their trees match, and uses Mergecraft's history-only manifest. The PR shows zero changed files with links to commits and the immutable comparison. Missing history or rendered commit links holds; an empty file diff alone never establishes a no-op or approval.

For reconciliation, inspect `python3 -m fork_sync --help` and the reviewed workflow's invocation together. Require the configured mode, controller revision, policy digest, helper pin, repository, and target branch to match the approved execution scope before dispatch. Run from the approved controller checkout, which the hosted workflow places in `$GITHUB_WORKSPACE/controller`:

```sh
cd "$GITHUB_WORKSPACE/controller"
python3 -B -m fork_sync reconcile --phase prepare \
  --repo "$PWD" \
  --provingkit "$RUNNER_TEMP/provingkit" \
  --evidence-dir "$RUNNER_TEMP/sync-prepare"
```

`FORK_SYNC_MODE` selects `off`, `validation`, or `production`. An active mode requires `FORK_SYNC_APPROVED_REVISION` to equal the clean executing controller checkout's commit. Policy selects `validation_branch` for validation and `target_branch` for production; the same raw policy must be present on the selected base. The published workflow and its actual `--help` output must agree before use. The command's off path can be checked without activation:

```sh
FORK_SYNC_MODE=off python3 -B -m fork_sync reconcile --repo "$SYNC_REPO"
```

## Complete one attempt

1. Verify source parity and ownership before publication. Every declared fork-owned file must be present in both the target base and merged tree before returning a candidate or verified no-op; a missing file holds. The candidate must contain exactly the selected upstream entries plus the unchanged admitted fork-owned entries.
2. Publish one immutable candidate branch with Versionkeeping's reviewed plan and exact lease. A disposable repository materializes the candidate for the publication helpers; the executing controller checkout stays unchanged. Candidate content is data and is not executed. Mergecraft validates the generated PR body and publishes it as a draft. Verify live navigation and file anchors for changed files, or complete commit links for a history-only candidate, before marking it ready. Existing candidate branches or PRs are reused only when their identities and authored content match; drift holds.
3. Collect the configured successful checks for the current candidate, strict branch protection enforcing those checks for administrators, confirmed clean mergeability, no unresolved review threads, and CodeRabbit's current-commit approval. After complete page and raw-count validation, repeated check results count once when their normalized name, app ID, head, status, and conclusion are identical, including JSON types. Different app identities remain distinct; conflicting results for one identity hold. A skipped CodeRabbit content review is not itself an approval.
4. Preparation returns `awaiting_judgment` and a digest of the candidate binding only after the preceding gates pass. A dedicated Actions job named `Jev <digest>` invokes the same command with `--phase finalize`. Finalization rechecks the candidate and hosted gates, verifies that this visible job is its first judgment attempt, and makes one uncached Jev request with client retries disabled. Accept only the pinned answer and threshold below. Hold malformed, incomplete, stale, failed, oversized, binary, or otherwise unsupported input and responses.
5. Reobserve the live base, head, checks, review, and protection before the merge attempt. The server's strict required checks remain necessary against concurrent base movement. Use the merge method that preserves ancestry and verify the resulting commit and parents. An uncertain write outcome requires observation; never retry it blindly.

Runtime credentials belong in the approved environment and secret store. Checkout authentication must not leave repository-local credential settings that conflict with Versionkeeping. The adapter uses `GH_READ_TOKEN` for its read-only GitHub calls when supplied, `GH_TOKEN` for publication helpers, and `TYPESAFE_API_KEY` for Jev. The reviewed workflow owns their permissions and lifecycle. Do not place token values in arguments, files, PRs, or logs.

Publication receipts remain private to the runner. An ephemeral run can establish canonical publication and audit its result; a later run reobserves and reconciles without claiming retained canonical history. Report `reconciled-unreceipted` as such. Uploading private receipts is not the evidence-retention route.

The attempt guard reads the pinned workflow's complete run and job history, including rerun attempts. `FORK_SYNC_WORKFLOW_ID` and `FORK_SYNC_FIRST_RUN_NUMBER` are approved activation settings; the initial run boundary is 1. Any previous non-skipped job for the same binding consumes the attempt, including a timeout, cancellation, negative judgment, or accepted judgment followed by a failed merge. Deleted, expired, missing, or inconsistent history holds. Do not move the boundary forward or recreate the workflow to bypass a hold. A maintainer must review recovery; this first version does not automatically reuse a prior judgment or retry it. Artifact expiry never permits another sample.

Per-run history reads use at most four workers, each reading one run and its attempts in sequence. Permission requires every eligible run and rerun to pass the complete history and snapshot checks; concurrency adds no history cutoff or retry. This reduces the serial wait but leaves total API volume growing with retained history and reruns. Rate limits, expired history, and the finalization job's 20-minute timeout can still prevent completion. A caught unavailable read holds; a runner timeout can terminate the job before it returns a hold. Neither outcome permits another sample.

Workflow-wide concurrency has cancellation disabled. The workflow invokes finalization only once in the bound job. Manually calling finalization again inside that same running job would not create another Actions attempt record and is outside the supported execution procedure.

## Apply the Jev rule

Use `jev-1.13.0` and the exact approved `additional_handling` choice question in policy. Its three outcomes are `no_additional_handling`, `additional_handling`, and `insufficient_context`. Jev's gate passes only when its selected answer is `no_additional_handling` and that option's raw probability is at least **0.96**. Both other answers hold, as does a lower probability. The CLI's convenience confidence bands are not the acceptance rule.

The state includes the complete bounded upstream diff and explicit fork obligations. Source text is material to assess, not instructions to follow. Bind the response to base, upstream, head, tree, policy digest, question digest, and submitted-state digest. Model, question, threshold, or relevant obligation changes require fresh qualification. Jev is an additional hold gate; it does not replace tree verification, authorization, CI, review, or branch protection.

The repo-owned `tools/jev/judge.mjs` runner uses the locked Jev evaluator with `cache: false` and `maxRetries: 0`. A failed or timed-out transport holds without another request. The runner preserves provider precision in its structured evidence; display rounding cannot change the controller's comparison with the raw response or its threshold decision. It does not change the approved question, model, or threshold. Response-cache bypass does not disable Jev's local alias and usage metadata writes.

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
| App registration | Operator-owned GitHub App installed only on `nisavid/typesafe-skills`. Contents and Pull requests write; Checks, Actions, and Administration read; required Metadata read. No Workflows write, organization permissions, or protection bypass. Webhooks are disabled; scheduling remains in Actions. |
| App identity | In `upstream-sync`, set `FORK_SYNC_APP_CLIENT_ID`, `FORK_SYNC_APP_INSTALLATION_ID`, and `FORK_SYNC_APP_SLUG` from the approved registration and installation. Both token actions must report that installation ID and slug before the controller runs. |
| App private key | Store `FORK_SYNC_APP_PRIVATE_KEY` only in the approved environment. The pinned token action consumes it; controller and Jev process environments do not receive it. The key grants the App's full installed authority, so expanding installation access requires a separate decision. |
| Publication credential | Each job generates a repository-limited installation token with Contents and Pull requests write, supplied to publication as `GH_TOKEN`. |
| Observation credential | Each job generates a separate repository-limited installation token with Contents, Pull requests, Checks, Actions, and Administration read, supplied as `GH_READ_TOKEN`. Branch-protection observation requires Administration read. |
| Judgment credential | `TYPESAFE_API_KEY`, available only to the finalization command. Jev's subprocess receives its own key without forge or runner credentials. |
| Target protection | Require `sync-ci` from GitHub Actions, strict up-to-date checks, and enforcement for administrators. Permit ancestry-preserving merge commits. Verify the live rule before running. |

### Provision and validate App authentication

Create the registration and installation only after approval of the concrete access request. Record the App client ID, numeric App ID, slug, installation ID, selected repository, granted permissions, and bot login. Verify the environment remains restricted to `main`, its reviewer requirement matches the approved validation plan, and sync is `off` before saving the private key. Keep credential values out of chat, commands, files in this repository, and retained evidence.

The GitHub actor for publication and merges is `<app-slug>[bot]`; the operator explicitly authorizes that actor for this workflow. Candidate commits retain the configured Git author and committer identity, `Ivan D Vasin <ivan@nisavid.io>`; App authentication does not change Git authorship or provide commit signing. Upstream authorship and ancestry remain preserved.

The runner supplies Git publication authentication through the in-memory Git credential cache, using one explicit socket under `$RUNNER_TEMP/sync-git-credentials`, with a 20-minute lifetime and an always-run shutdown of that socket. This binding remains the same when the helper removes `XDG_CACHE_HOME` from Git subprocesses. The pinned Versionkeeping helper removes token environment variables before invoking Git, so `gh auth setup-git` alone is insufficient on a fresh runner. The cache receives the publication token through standard input; it does not store the token in a file. This cache is shared by processes of the runner user and is not a sandbox boundary.

Dependency installation finishes before token generation. Tokens are issued separately in each job, expire after one hour, and the pinned action attempts revocation when the job ends. Keep its default revocation enabled. Both tokens are available to the trusted controller process; this is permission separation, not process isolation. A failed issuance or installation/slug mismatch stops before controller execution. After token expiry, cancellation, or an uncertain write, reobserve the existing candidate and attempt history before any recovery; issuance of a fresh token does not authorize another Jev sample or a repeated write.

The first hosted validation must show the App-authored PR, CI triggered by that PR, normal CodeRabbit approval of its current commit, successful observation of protected-branch settings, and the authenticated merge actor. Verify token cleanup in the job's post steps. Missing evidence holds qualification. A local test using controlled GitHub responses does not prove installation permissions or bot-review behavior.

Keep the App private key confined to the TypeSafe validation environment. Other forks need their own reviewed access and qualification. Before sharing one App across repositories, decide how its private key is isolated: separate Apps or a protected issuer that grants bounded tokens. The controller's read/publication interfaces accept runtime tokens; reuse elsewhere does not require personal tokens or these environment variable names.

The validation branch must contain the earlier real upstream revision plus the same reviewed fork-owned files as the controller. Do not rewind main. The workflow must be registered on the default branch for manual dispatch; installing inert controls on main is part of the separately reviewed publication/activation sequence. Record every actual revision rather than treating the older CodeRabbit trial branch as the current validation fixture.

Run whole-command tests against disposable repositories and controlled hosted responses, focused tests for intricate gate rules, and the real hosted historical update. Local fixtures and actual helper tests with a fake GitHub executable establish their stated local contracts only.

Before declaring the TypeSafe producer qualified, retain a successful nonempty hosted validation with the controller/procedure revisions, policy and question digests, base/upstream/candidate/merge commits, PR and run URLs, successful required checks, authenticated current-commit CodeRabbit approval, uncached Jev response binding, final tree parity, unchanged owned entries, and preserved ancestry. Record cleanup and any retained validation branches. The dedicated-branch result does not establish a future nonempty production-branch update until one is observed.

Also exercise a history-only PR on the dedicated validation branch. Observe GitHub accepting the zero-file candidate and normal CodeRabbit approval of that commit before claiming this branch of automatic sync is qualified. Missing approval holds without override commands. This case complements the required nonempty historical update.

Procedure completion also requires a published discovery pointer, clean independent review of the final equipment, and observed positive/negative discovery plus success/failure/no-op applications. The scenarios in `tests/procedure/scenarios.json` are evaluation inputs, not evidence that those evaluations passed.

A consumer fork loads the reviewed `syncing-upstream` revision and requires the TypeSafe producer's hosted result before dependent adoption. It reestablishes its own ownership map, upstream anchor, review scope, obligations, permissions, required checks, and branch protection, then runs its own nonempty validation. Copying a workflow or inheriting TypeSafe's result alone does not qualify that fork. Record the consumed source revision and send useful corrections back to the producer.
