# Optional session evidence

Session evidence adds local events and work assessments to existing discovery.
It is optional: ordinary commands retain their behavior, and reading an absent
evidence store creates nothing.

## Commands

| Command | Purpose |
|---|---|
| `lost-sessions evidence record --file record.json --json` | Append an event or assessment and return its receipt |
| `lost-sessions evidence record --file record.json --dry-run --json` | Validate input without writing; store-dependent conflicts are checked on append |
| `lost-sessions evidence list --tool codex --session ID --json` | Read records for the exact full session ID |
| `lost-sessions evidence view --tool codex --session ID --json` | Join native facts with the derived summary |
| `lost-sessions inventory --evidence --json` | Enrich the normal inventory without changing selection or order |

Use the full session ID when reading evidence records.

`ID` comes from the runtime or `lost-sessions inventory --json`; never identify
a session by its directory or assume the newest session is the intended one.
`--file -` reads stdin and is the default. JSON input is limited to 1 MiB and a
stored event to 64 KiB. Timestamps must include a timezone.

`--output json` and `-o json` are aliases for JSON formatting. Text is the
default. Empty history lists exit 0; a view with neither native nor recorded
session data exits 3. Invalid input exits 2; storage and partial-read failures
exit 1. JSON errors are one `error` object on stderr.

The companion skill's [recording guide](session_evidence_records.md)
defines the input schema and examples. Preserve both `record_id` and
`occurred_at` when retrying a write. An identical retry returns the original
receipt; conflicting reuse is rejected. The receipt also includes `recorded_at`,
the local receipt time, and `machine_id`, the store's persistent identity.

## Summary

The `session` object in `evidence view --json` retains native creation/update
timestamps and liveness. The separate `evidence` object includes:

| Field | Meaning |
|---|---|
| `first_observed_at` | Earliest local receipt, not original creation |
| `last_opened_at`, `last_ended_at` | Latest recorded lifecycle event times |
| `last_interaction_at`, `last_work_at` | Latest classified turn and latest turn classified as task-directed work |
| `assessment` | Latest assessment, including its scope, source, note, and references |
| `assessment_currency` | Whether recorded work or unknown activity occurred after the assessment |
| `close_intent` | Latest explicit closure declaration |
| `closure` | Relationship between recorded openings and endings |
| `coverage` | `not-recorded` or `partial`; never complete coverage |

Closure values are `no-end-recorded`, `reopened-after-end`, `end-observed`,
`end-observed-unmatched`, and `ambiguous`. These describe evidence only.
An unmatched end lacks runtime-instance correlation. Ambiguity includes
conflicting instances or equal start/end timestamps. Present liveness still
comes from the existing scanner.

An assessment marked `as-recorded` has no later recorded work or unknown turn;
it is not proof that the assessment remains correct. Orientation-only recaps
leave it intact. Later work produces `work-since-assessment`; unknown activity
produces `unclassified-activity-since-assessment`.
When the assessed-through turn has a recorded timestamp, that timestamp is the
comparison point. Otherwise the assessment's occurrence time is used. Keep the
covered turn reference even when its timestamp is unavailable.

## Storage and failures

Records live at
`${XDG_STATE_HOME:-~/.local/state}/lost-sessions/evidence.sqlite3`.
The existing `history.jsonl` continues recording recovery actions separately.
Corrections append records. Native stores remain untouched, and this version
does not synchronize evidence across machines.
New files use mode 0600 on POSIX. On Windows, access follows the containing
directory's access-control rules. Explicit writes wait up to five seconds for
a busy database; hook writes wait up to 250 milliseconds.

Unreadable optional evidence produces `evidence_warnings` in enriched inventory
JSON while discovery retains its sessions and normal exit status. Explicit
evidence queries report incomplete reads with exit 1. An older writer never
modifies a database carrying a newer version.

## Optional skill and hooks

The optional companion plugin provides the recording workflow. From a local
checkout, add the checkout's absolute path as a marketplace, then install
`lost-sessions@lost-sessions`:

- Claude Code: `/plugin marketplace add PATH`, then
  `/plugin install lost-sessions@lost-sessions`.
- Codex: `codex plugin marketplace add PATH`, then
  `codex plugin add lost-sessions@lost-sessions`.

`PATH` is the checkout's absolute path, obtained by running `pwd` from its root.
The Python CLI and companion plugin are separate installs.
Skill installation alone enables no hooks.
The separate templates call `lost-sessions evidence hook --tool claude` or
`--tool codex` with the original payload on stdin. Failures warn and exit 0;
the templates ignore a missing CLI.

Only `SessionStart` and `SessionEnd` are recorded. Compaction is a context
refresh; `Stop` is ignored. Hooks do not assess completion, infer user closure
intent, or label crashes. Other runtimes can use explicit records until their
automatic adapters are validated.
