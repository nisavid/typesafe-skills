# Upstream sync

This context describes an upstream update proposed for a fork and the judgment used to assess it.

## Language

**Proposed update**:
Bringing one logical fork branch from an upstream revision A to a selected upstream revision B, within its durable recovery scope. Workflow reruns, PR names, and rebuilt merge-commit metadata do not change its identity.

**Recovery scope**:
The durable identity of a logical fork branch, independent of its current ref, workflow, fixture, or journal record names. Renamed or rebuilt surfaces must establish continuity with this scope before registering updates; they inherit its claims and legacy uncertainty.

**Assessment evidence**:
The exact candidate and evaluation inputs to which a judgment applies. Changed evidence can make a judgment unusable without creating another attempt for the same proposed update.

**Judgment attempt**:
The single opportunity reserved for requesting a judgment about a proposed update. Once claimed, it remains spent even if execution stops before the request reaches the provider.

**Retained judgment**:
A saved judgment and the complete evidence binding to which it applies. It can support a later merge attempt only while that binding remains unchanged and the current merge requirements pass.

**Upstream change set**:
The net changes to upstream file contents, paths, and executable modes from a starting upstream revision to a selected revision. Commit identifiers and metadata are not part of the change set.

**Legacy uncertainty**:
An earlier judgment attempt whose possible effects cannot be established. It makes every proposed update that it could have assessed ineligible for another attempt.
