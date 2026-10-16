---
status: accepted
---

# Durable claims for upstream-update judgments

Reserve one durable attempt for each proposed upstream update before requesting its judgment. A claimed attempt stays spent after interruption, including a crash before request delivery. This sacrifices some opportunities to obtain a judgment while preventing an automatic resend after an uncertain outcome.

Keep update identity separate from the exact assessment evidence. Reuse a retained judgment only while the candidate and every assessment input remain unchanged and the current merge requirements pass. A genuinely different upstream change set may receive its own attempt; preserve earlier spent records and legacy uncertainty.

Retain claims and reusable judgments for the repository lifetime. Missing or stale-restored records hold recovery rather than resetting an attempt. Qualify a protected Git-backed journal first; choose another backend if it cannot meet these requirements. The accepted [recovery plan](../research/attempt-recovery-plan.md) defines the change-set rule, legacy cutover, storage qualification, review, and validation gates. Production stays off.
