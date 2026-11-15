---
name: lost-sessions
description: Recover agent sessions lost after a reboot or terminal failure, and record or inspect optional session evidence using the lost-sessions CLI. Use for "recover my lost sessions", "record this session as probably done", "record that I am closing this session", or "show this session's recorded history". Generic recaps, progress reports, and cleanup remain with session-recap, session-status, and session-loose-ends when available.
allowed-tools: Bash, Read, Write
---

# lost-sessions

Find resumable agent sessions and preserve optional observations about their
lifecycle and work.

## Workflow

1. Check that `lost-sessions` is available with `command -v lost-sessions`.
   If it is missing, report that the CLI is required. Do not install software
   or create a substitute record store without a request to do so.
2. Choose the requested operation:
   - **Recover:** run `lost-sessions list` to find recovery candidates, or
     `lost-sessions inventory --json` for the full local inventory. Use
     `lost-sessions open --help` for supported destinations. Show the selected
     session identity and destination before opening it. A request to open an
     identified session already authorizes that opening.
   - **Inspect evidence:** run `lost-sessions evidence view --tool TOOL
     --session SESSION_ID --json` for one session, or
     `lost-sessions inventory --evidence --json` for enriched discovery. Resolve
     `TOOL` and `SESSION_ID` from the inventory or authoritative runtime context.
     Inspection does not require recording a new event.
   - **Record:** follow [the record guide](references/records.md) when the user
     explicitly requests a record or an established user preference enables it.
     Record only the relevant event or assessment. Skill installation alone
     does not enable automatic recording.
3. For writes, identify the exact runtime and full session ID from runtime
   context, a user-supplied ID, or an unambiguous inventory result. A working
   directory, title, short ID prefix, or newest-session guess is insufficient.
   If identity remains ambiguous, ask for that missing identity before writing.
4. Keep the assessment tied to this session's agreed work. If an existing
   session skill already produced a close-out assessment, reuse its scope,
   evidence, and remaining items. Reading a recap does not imply that work
   resumed. A failed investigation can still be task-directed activity.
5. Submit the JSON with `lost-sessions evidence record --file PATH --json`,
   where `PATH` is the JSON file just prepared. Read the command's response
   and then `evidence view` to confirm the stored result. A failed write is
   reported as a failed write; continue the user's main task.

## Interpreting the result

- Runtime opening, runtime ending, intention to close, and work completion are
  separate claims. An assessment never proves that a process stopped.
- "Done for today" normally means paused. "Main work probably complete" is
  an assessment. "Handed off" means responsibility moved, not that all work
  finished.
- Preserve who supplied a claim and what supports it. An agent's judgment uses
  `source: "agent"`; use `source: "user"` for the user's explicit statement,
  not for an agent's inference about what the user meant.
- An end event provides evidence about one ending. No later reopening
  recorded does not prove that none occurred. Missing events do not establish
  a crash. Current liveness still comes from discovery.
- Keep original creation time, latest reopening, and latest interaction
  distinct. Classify a turn only when requested or enabled by user preference;
  use `unknown` when the available context does not support a classification.
- Preserve prior assessments. A correction records which earlier record it
  supersedes; it does not rewrite history.

## Optional integration

For a user-requested lifecycle integration, read
[the hook guide](references/hooks.md). Hook templates are examples outside the
plugin's automatic hook location. This skill does not install or enable them.

For an optional user instruction that records wrap-up assessments, use
[the integration example](references/records.md#optional-user-instruction).
Apply such an instruction only when the user elects to enable it.
