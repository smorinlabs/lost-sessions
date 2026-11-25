# lost-sessions skill

The optional [companion plugin](../../plugins/lost-sessions/README.md) ships the
[lost-sessions skill](../../plugins/lost-sessions/skills/lost-sessions/SKILL.md).
It helps an agent recover a lost session, inspect recorded evidence, or append
an explicitly requested event or work assessment.

The Python CLI is the prerequisite. Installing the plugin does not install the
CLI, enable hooks, change agent transcripts, or authorize automatic recording.
The plugin ships native manifests for Antigravity, Claude Code, and Codex.

## Records and summaries

The skill writes one record per event or assessment. A work assessment keeps
its scope, assessed-through turn, main-work state, remaining items, and evidence
together. The CLI retains prior records and derives a combined session summary
when requested. Existing session discovery and recovery behavior remains
available without these records.

See [the record guide](../../plugins/lost-sessions/skills/lost-sessions/references/records.md)
for the schema, an assessment example, and optional user-level agent guidance.
The user guidance delegates recording after an explicit wrap-up request; it
does not turn every recap into a write operation.

## Boundaries

Generic recap, status, and cleanup skills continue to own their existing work.
The companion can preserve their completed assessment when recording is
requested. It does not rerun their policy, perform cleanup, close a process, or
conclude that a session crashed merely because no end record exists.

Lifecycle recording is a separate opt-in. The
[hook guide](../../plugins/lost-sessions/skills/lost-sessions/references/hooks.md)
supplies Antigravity (`agy`), Claude Code, and Codex configuration fragments.
They are stored as examples rather than automatic plugin hooks. Muse and
OpenCode remain usable through explicit records while their lifecycle adapters
await payload validation. Automatic turn classification is not part of this
version.
