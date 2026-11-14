# 0007. Optional session evidence

- Status: accepted design, implemented locally
- Date: 2026-11-14
- Extends: [plugin design](0006-lost-sessions-plugin-design.md)
- Reference: [session evidence](../source/reference/session_evidence.md)

## Approved model

Store separate event and assessment records. Each record contains the fields
describing that occurrence or judgment. Calculate one combined summary on demand;
there is no independently editable summary record.

Recording is explicit. Ordinary discovery and recovery keep their existing
behavior. Reading never initializes an absent store. Installing the companion
skill does not enable hooks. Native agent transcripts remain untouched.

## Persistence

Use a separate local SQLite database beside the existing action history.
Transactions serialize concurrent appenders; new files use mode 0600.
The store generates a persistent machine identity. This version is local-only.
Events name the exact runtime and full session ID; optional runtime-instance IDs
must come from actual runtime evidence, never from the conversation ID.

Occurrence time and local receipt time are separate. Native `created` remains
the original creation time. First observation is the earliest receipt, which
can be much later. Reusing a UUID with identical event content is idempotent;
conflicting reuse fails. Corrections append with `supersedes`, restricted to
the same session and kind. Both versions remain in history.

Unknown database versions and malformed records produce visible read warnings.
Writers refuse unknown versions. Hook recording failures warn and return success
so the agent's main work can continue.

## Meanings

- An opening does not establish present liveness or task activity.
- An ending is a runtime observation, not user intent or proof that a session
  never crashed. Preserve its original reason.
- Closure intent is an explicit declaration. It neither stops a process nor
  changes a work assessment.
- Assessments carry scope, assessed-through turn, source, note, remaining work,
  and evidence references. Completion applies to that scope at that point.
- Turn classification is explicit. Research and failed attempts can count as
  work; a recap normally counts as orientation. Automatic classification is
  deferred.
- A recap does not invalidate a previous assessment. Later recorded work or
  unknown activity adds a warning. Missing later records prove nothing.
- Delayed ends from older instances cannot close newer openings. Missing
  instance identity yields an unmatched-end label; conflicts yield ambiguity.
- Coverage is always partial when records exist. Missing evidence never means
  crashed, complete, or explicitly closed.

## Adapters and compatibility

The first adapters accept Claude Code and Codex start/end notifications.
Compaction records a context refresh, not an opening. Turn-ending `Stop` events
are ignored. Standard payloads lack runtime-instance identity, so no such
identity is invented. Muse and OpenCode use explicit recording until automatic
adapters have validated lifecycle payloads. Brot is not a required dependency.

`inventory --evidence` adds summaries and warnings. Without that flag, the
existing inventory output remains byte-compatible. Selection, ordering, native
timestamps, and liveness continue using existing data. An unusable evidence
store cannot suppress discovered sessions.

## Verification and CLI conventions

Tests cover repeated openings, delayed endings, recap-only activity, corrections,
concurrent writes, missing/corrupt/future stores, input validation, hook failures,
and unchanged default output.

CLI Design Standard 1.4.14 checks used for this extension: structured input
(`R3.9`), no flag abbreviation (`R3.10`), JSON output (`R4.2`), validation-only
dry run (`R4.3`), state paths (`R5.3`), empty-list/not-found distinction (`R6.2`),
and structured errors (`R7.8`). The extension retains the repository's
command-local text/JSON convention; this is not a conformance audit of the
existing CLI's global options.
