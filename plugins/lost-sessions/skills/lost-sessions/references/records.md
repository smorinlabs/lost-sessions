# Recording session evidence

Each JSON document describes one event or assessment. Related fields belong in
that record. The CLI appends it to its optional local store and derives a
combined summary when requested. Existing discovery and agent transcripts are
unchanged.

## Commands

Use `lost-sessions evidence record --file PATH --dry-run --json` to validate a
prepared document without storing it. `PATH` is the JSON file prepared for
this operation. Use `--file -` to read the document from stdin.

Remove `--dry-run` to append the record. Use
`lost-sessions evidence list --tool TOOL --session SESSION_ID --json` to inspect
the records, and `evidence view` with the same identity to read the derived
summary. Obtain `TOOL` and the full `SESSION_ID` from runtime context, the user,
or `lost-sessions inventory --json`.

## Record fields

| Field | Meaning |
|---|---|
| `tool` | Required runtime name, matching discovery, such as `claude`, `codex`, `muse`, or `opencode` |
| `session_id` | Required full runtime session ID |
| `kind` | Required: `opened`, `ended`, `close-intent`, `assessment`, `turn`, or `context-refreshed` |
| `source` | Required: `user`, `agent`, `hook`, or `import`; names the source of the claim |
| `occurred_at` | Event time with a timezone; defaults to the current time |
| `record_id` | Optional UUID retained across retries of the same record |
| `run_id` | Optional identity of a particular runtime instance; omit when unknown |
| `native_event` | Original runtime event name when recording a lifecycle observation |
| `reason` | Original runtime reason or explicit reason for the event |
| `note` | Explanation; required for `assessment`, `close-intent`, and `turn` |
| `scope` | What work was assessed; required for `assessment` |
| `work_state` | Required for `assessment`: `incomplete`, `probably-complete`, `complete`, `paused`, `blocked`, or `handed-off` |
| `remaining` | List of remaining items |
| `references` | List of evidence or handoff references |
| `through_turn` | Last turn covered by an assessment; required for `assessment` |
| `turn_id` | Turn being classified; required for `turn` |
| `activity` | Turn category: `work`, `orientation`, `administrative`, or `unknown`; required for `turn` |
| `supersedes` | Earlier record ID corrected by this record; must identify the same session and kind |

Assessment fields belong only on `assessment` records. Turn fields belong only
on `turn` records. A turn correction must identify the same `turn_id`. Keep the
actual turn time; change it only to correct an inaccurate timestamp.
Hooks supply lifecycle observations, not semantic
assessments, turn classifications, or a user's closure intent.

Keep generated record IDs and returned recording timestamps from the CLI's
response. Do not claim that a user or hook supplied evidence that the agent
inferred. A runtime instance ID must come from an actual runtime identity, not
the session ID reused under another name.

## Example assessment

This illustrative document records an agent's assessment of the main task.
Replace the example session and turn IDs with the actual identity and evidence
before submitting it.

```json
{
  "tool": "codex",
  "session_id": "0198ae46-65b1-7f62-96d6-d11eb7bdb6e1",
  "kind": "assessment",
  "source": "agent",
  "scope": "Implement the CSV export command",
  "work_state": "probably-complete",
  "through_turn": "turn-7",
  "note": "Implementation and local checks are complete; release verification remains.",
  "remaining": ["Verify the published package after release"],
  "references": []
}
```

This record says nothing about whether the runtime ended. If the user separately
declares that the session is being closed, record a `close-intent` with that
statement in `note`. Let a runtime hook record an `ended` observation when
available.

## Turn classification

`work` means the turn addressed the session's task; it does not assert success.
Research, design decisions, and failed debugging attempts can qualify. A recap
normally uses `orientation`, but a recap that leads to new task work can use
`work` with a note explaining the mixed turn. Tool calls, file edits, and message
length alone do not determine the category.

Use the actual turn time as `occurred_at` when recording an older turn. Do not
make an old task look recently active by using the assessment's current time.

## Optional user instruction

A user can elect to add this guidance to their user-level agent instructions:

> When I explicitly say that this session is done or that I am closing it,
> preserve the existing session close-out assessment with the lost-sessions
> skill if its CLI is available. Record the exact session identity, scope,
> assessed-through turn, source, supporting evidence, and remaining work. Treat
> "done for today" as paused unless the context establishes that the main work
> is complete. Record closure intent separately from work completion. Do not
> enable hooks, close a process, or perform cleanup as part of recording. If
> recording fails, tell me and continue the main task.

This preference authorizes the described records. It does not make a generic
recap request a write request and does not enable lifecycle hooks.
