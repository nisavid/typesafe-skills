# Issue tracker

Issues and specs live in GitHub Issues for `nisavid/typesafe-skills`.

Use `gh-axi` for supported GitHub operations. Pass `--repo nisavid/typesafe-skills` explicitly; an upstream remote can change the CLI's inferred repository. Use `gh` with that explicit repository or the GitHub API with `repos/nisavid/typesafe-skills` endpoints for an operation the wrapper does not expose. Upstream writes require separate authorization. Read the live command help before relying on syntax. Draft multiline bodies in a file and pass `--body-file`.

Create, read, list, comment, edit, and resolve issues in this repository. Assign active work to `nisavid`; that assignment is the claim. Preserve other people's checklists and claims. Read operator-owned work-contract checklists and update authorized items as their work completes.

## Pull requests as a triage surface

PRs as a request surface: no.

## Skill conventions

“Publish to the issue tracker” means create a GitHub issue. “Fetch the relevant ticket” means read its full body, labels, relationships, and relevant comments.

## Wayfinding operations

Use `wayfinder:map` for the map and `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task` for a child. Wayfinder tickets carry only Wayfinder labels. Create a missing Wayfinder label when its type is needed.

The map holds Destination, Notes, Decisions so far, Not yet specified, and Out of scope. Tickets are native GitHub sub-issues. Native issue dependencies record blocking relationships; use the blocker's database ID, not its issue number, when the API requires an ID.

The frontier is the map's open children with no open blockers and no assignee. Claim a ticket by assigning `nisavid` before working it. Resolve with a comment containing the answer and evidence, close it, and append a named link and one-line gist to the map's Decisions so far. Use ticket titles in prose and links.

Create all child issues before wiring their relationships. Use body fallbacks only if GitHub reports that native sub-issues or dependencies are unavailable. Read the current graph before concurrent writes and preserve other sessions' changes.
