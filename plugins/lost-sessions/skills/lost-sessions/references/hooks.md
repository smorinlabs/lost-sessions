# Optional lifecycle hooks

Installing the skill does not install lifecycle hooks. The two JSON examples
beside this guide are opt-in configuration fragments for Claude Code and Codex:
[Claude fragment](claude-hooks.json) and [Codex fragment](codex-hooks.json).

When the user requests hook installation, merge the matching fragment into the
runtime's existing hook configuration. Preserve unrelated entries. Follow the
runtime's normal enable and trust flow. Do not replace a whole configuration
file or bypass hook trust.

The executable `lost-sessions` must resolve in the hook process's `PATH`.
The command guard lets sessions continue if that executable is absent. If it
is present, the hook command validates the payload and records locally. Unknown
events and failures do not block the session. A failed record is not evidence
that the event never occurred.

## Mapping

| Runtime event | Recorded meaning |
|---|---|
| `SessionStart` with `source: "compact"` | `context-refreshed`; compaction is not a reopening |
| Other supported `SessionStart` payloads | `opened`, preserving the original source as the reason |
| `SessionEnd` | `ended`, preserving the original reason |

These commands use the runtime's payload session ID. They never infer identity
from the working directory, transcript filename, or most recent session.

An `ended` record means the runtime emitted an ending event. It does not mean
the user explicitly closed the session, all work finished, or no crash ever
occurred. Codex can emit this event after an unattended idle timeout. A Claude
ending may result from clearing or switching sessions. Missing records remain
unknown because hooks may be disabled, unsupported, interrupted, or unable to
write.

This version supplies lifecycle adapters for Claude Code and Codex. Muse and
OpenCode can still use explicit evidence records; their lifecycle adapters need
separate payload validation. No automatic turn classifier runs in these hooks.

## Check a proposed integration

Before enabling it for normal sessions, feed a captured non-sensitive payload
to `lost-sessions evidence hook --tool claude` or `--tool codex` in an isolated
state directory. Check the resulting records with `evidence list`. Verify a
normal opening, a resumption, compaction, and an ending separately. Fixture
validation confirms mapping; a real runtime event confirms that the installed
hook actually fires.
