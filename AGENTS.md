# TypeSafe skills fork

This repository mirrors `typesafe-ai/skills`. Keep every upstream-owned file byte-identical to the selected upstream revision. Fork-local policy and automation are explicit additions. If upstream introduces one of those paths, stop and resolve ownership before syncing.

`AGENTS.md` is the maintained repository instruction source. This upstream does not provide a `CLAUDE.md`.

## Fork operations

Use `fork-ops` and read `.agents/fork-ops.toml` before fork work. Verify its capability report before selecting an operation. The installed foundation supplies config inspection and guarded config creation; it does not implement broad upstream sync.

The fork-owned paths are `AGENTS.md`, `.agents/fork-ops.toml`, `.coderabbit.yaml`, `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, and `docs/agents/domain.md`. Add another fork-local surface only with a reviewed task decision. Preserve the upstream marketplace and skill files.

CodeRabbit reviews fork-owned changes and uses normal automatic approval. Do not force approval or bulk thread resolution. Its upstream path filters define review scope; they do not establish source parity. Sync merges require independent tree and ownership verification plus the other approved gates. The historical validation branch tests review behavior without qualifying the complete sync workflow.

Track sync policy and qualification through the Wayfinder map, “Qualify deterministic upstream sync for TypeSafe skills”: https://github.com/nisavid/typesafe-skills/issues/1. Use its child issues and native dependencies to claim work and identify prerequisites. A workflow, fixture, or no-op result does not establish a successful real sync.

## Development and publication

Use the standing skills that fit the work: `grilling` with `domain-modeling` for unresolved decisions, `tdd` for implementation, and `capturing-agent-procedures` for reusable methods. Read tracking instructions before ticket operations.

Preserve unrelated state and commit only task-owned changes using the host Git identity. Use `checkpointing-and-publishing-git-work` at intake, clean checkpoints, and stopping points. Use the `nisavid/` prefix for new branches and Conventional Commits. Prefer squash merging unless the reviewed sync policy selects a different method.

Review code, configuration, and agent instructions on the final commit before pushing. Use independent Tricritical critics and adjudication; substantive changes require its top-level review-and-revise loop until clean. Changed candidates invalidate affected reviews. Use `publishing-reviewable-prs` and `writing-reviewable-pr-descriptions` for PR publication and keep PRs draft until their review is clean.

Ordinary task-owned commits and publication are expected completion steps within the active authorization. Hold changes with unresolved ownership, identity, destination, permissions, conflicts, required checks, or reviews. Account, billing, secrets, branch protection, and automatic merge activation require their applicable approval. Preserve remote work.

## Agent skills

### Issue tracker

Track work in GitHub Issues for `nisavid/typesafe-skills`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-role triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Use a single domain context. See `docs/agents/domain.md`.
