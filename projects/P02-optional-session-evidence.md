## [~] Project P02: Optional session evidence

**Goal/Requirement**: Add optional lifecycle observations and work assessments
to existing session discovery so users can inspect what was recorded without
confusing reopening, present liveness, closure intent, and work completion.

**Scope**
- Separate event and assessment records in an optional local store.
- One derived summary with occurrence time, receipt time, provenance, and
  explicit uncertainty. Native creation time and liveness remain separate.
- Explicit recording and inspection commands; optional inventory enrichment.
- A companion skill and opt-in Claude Code/Codex hook examples.

**Out of Scope**
- Automatic turn classification and automatic cleanup.
- Cross-machine synchronization and native transcript modification.
- Automatic Muse/OpenCode lifecycle adapters pending payload validation.
- Installing hooks or instructions into the user's live configuration.

**Decisions**
- Steve approved the optional enhancement on 2026-11-14 after design assessment.
- Store separate records for occurrences and judgments. Derive the combined
  summary rather than maintaining an independently editable snapshot.
- A recap can update the latest classified interaction without changing the
  latest task-directed turn or an earlier work-completion assessment.
- Missing evidence never proves a crash, completion, or explicit closure.

**References**
- Design: `docs/design/0007-optional-session-evidence.md`
- User reference: `docs/source/reference/session_evidence.md`
- Skill: `plugins/lost-sessions/skills/lost-sessions/SKILL.md`

### Tests & Tasks
- [x] [P02-T01] Implement validated append-only storage and derived summaries.
- [x] [P02-T02] Add explicit evidence commands and optional inventory enrichment.
- [x] [P02-T03] Add lifecycle adapters that preserve runtime event meanings.
- [x] [P02-T04] Package and document the opt-in companion skill and hook examples.
- [x] [P02-TS01] Cover correction history, concurrency, lifecycle ambiguity,
  assessment currency, absent/corrupt stores, and unchanged default inventory.
- [x] [P02-TS02] Verify skill loading in isolated Claude Code and Codex sessions.
- [x] [P02-TS03] Complete the final full checks and package verification.
- [x] [P02-T05] Prepare `feat/session-evidence` for review.
- [ ] [P02-T06] Merge and release after review; not part of local implementation.

### Validation boundaries

Tests use isolated state. No hook is enabled in the user's live configuration.
Fixture mapping and skill loading do not establish that an installed hook fires
in a real runtime lifecycle; that check belongs to the chosen integration.

Local validation on 2026-11-14: `just check` passed with 411 tests passing,
3 skipped, and 3 deselected. Whole-tree formatting, the Sphinx build with
warnings as errors, and the package build passed. The built wheel completed an
isolated evidence record/read round trip.

| Skill-quality layer | Result |
|---|---|
| Structure and metadata | Passed frontmatter, manifests, links, and opt-in hook checks |
| Safety, trigger fit, and documentation | Reviewed; no automatic recording or cleanup |
| Harness generation | Not applicable to this repository plugin |
| Tool verification | Claude/Codex loaders passed; isolated Codex marketplace installation passed |
| Authenticated workflow smoke | Unverified: isolated Claude lacked login; Codex encountered DNS failures |

Overall: local implementation and plugin loading are verified. Authenticated
workflow and actual installed lifecycle-hook firing remain unverified. The
isolated workflow attempts created no evidence records.
