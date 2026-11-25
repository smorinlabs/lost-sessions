# Optional lifecycle hooks

Installing the skill does not install lifecycle hooks. The three JSON examples
beside this guide are opt-in configuration fragments for Claude Code, Codex, and
Antigravity (`agy`):
[Claude fragment](claude-hooks.json), [Codex fragment](codex-hooks.json), and
[Antigravity fragment](antigravity-hooks.json).

When the user requests hook installation, merge the matching fragment into the
runtime's existing hook configuration. Preserve unrelated entries. Follow the
runtime's normal enable and trust flow. Do not replace a whole configuration
file or bypass hook trust.

For Antigravity (`agy`), merge [antigravity-hooks.json](antigravity-hooks.json)
into `~/.gemini/config/hooks.json` (global) or `.agents/hooks.json` (workspace)
— **not** `~/.gemini/antigravity-cli/settings.json`, where hooks are ignored.
Antigravity uses a named-hook object with a flat handler array under
`SessionStart`, sends camelCase JSON payloads (`conversationId`,
`hookEventName`, `cwd`, `workspacePaths`, `transcriptPath`), and expects a JSON
object on stdout (`lost-sessions evidence hook --tool agy` writes `{}`).

The executable `lost-sessions` must resolve in the hook process's `PATH`.
The command guard lets sessions continue if that executable is absent. If it
is present, the hook command validates the payload and records locally. Unknown
events and failures do not block the session. A failed record is not evidence
that the event never occurred.

## Mapping

| Runtime event | Recorded meaning |
|---|---|
| `SessionStart` with `source: "compact"` | `context-refreshed`; compaction is not a reopening |
| Other supported `SessionStart` payloads | `opened`, preserving the original source or reason if present |
| `SessionEnd` (Claude Code, Codex) | `ended`, preserving the original reason |
| `Stop` (all runtimes, including Antigravity) | Ignored — fires after every turn, not only at session close |

These commands use the runtime's payload session ID (`session_id` for Claude
Code and Codex; `conversationId` for Antigravity). They never infer identity
from the working directory, transcript filename, or most recent session.

An `ended` record means the runtime emitted an ending event. It does not mean
the user explicitly closed the session, all work finished, or no crash ever
occurred. Codex can emit this event after an unattended idle timeout. A Claude
ending may result from clearing or switching sessions. Antigravity has no
`SessionEnd` hook — its `Stop` hook fires at the end of every turn, so `Stop` is
explicitly ignored and never mapped to `ended`. Missing records remain unknown
because hooks may be disabled, unsupported, interrupted, or unable to write.

This version supplies lifecycle adapters for Claude Code, Codex, and Antigravity
(`agy`). Muse and OpenCode can still use explicit evidence records; their
lifecycle adapters need separate payload validation. No automatic turn
classifier runs in these hooks.

## Check a proposed integration

Before enabling it for normal sessions, feed a captured non-sensitive payload
to `lost-sessions evidence hook --tool claude`, `--tool codex`, or `--tool agy`
in an isolated state directory. Check the resulting records with
`evidence list`. Verify a normal opening, a resumption, compaction (where
supported), an ending (where supported), and that `Stop` writes no record. For
`--tool agy`, also confirm stdout is `{}`. Fixture validation confirms mapping;
a real runtime event confirms that the installed hook actually fires.
