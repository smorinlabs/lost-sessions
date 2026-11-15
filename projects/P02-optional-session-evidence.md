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
- Specification: `docs/superpowers/specs/2026-11-14-optional-session-evidence.md`
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
- [x] [P02-TS04] Verify authenticated Claude Code and Codex skill workflows
  with isolated evidence stores and independent record readback.
- [x] [P02-TS05] Verify actual Claude Code startup/end hooks in a temporary session.
- [x] [P02-T05] Prepare storage/CLI PR #29 and dependent companion/docs PR #28
  for review.
- [ ] [P02-T06] Merge and release after review; not part of local implementation.

### Validation boundaries

Tests use isolated state. No hook is enabled in the user's live configuration.
Claude Code's actual startup/end callbacks were verified with invocation-local
settings and a temporary evidence store. Codex recognizes both hook definitions
but marks them untrusted in a clean configuration. Its actual lifecycle-hook
test remains pending the normal hook-trust approval; trust is not bypassed.

Local validation on 2026-11-14 after updating onto current `main`:
`just check` passed with 432 tests passing,
3 skipped, and 3 deselected. Whole-tree formatting, the Sphinx build with
warnings as errors, and the package build passed. The built wheel completed an
isolated evidence record/read round trip.

| Skill-quality layer | Result |
|---|---|
| Structure and metadata | Passed frontmatter, manifests, links, and opt-in hook checks |
| Safety, trigger fit, and documentation | Reviewed; no automatic recording or cleanup |
| Harness generation | Not applicable to this repository plugin |
| Tool verification | Claude/Codex loaders passed; isolated Codex marketplace installation passed |
| Authenticated workflow smoke | Passed for Claude and Codex; each wrote exactly one fixture assessment, independently verified |
| Runtime lifecycle hooks | Claude startup/end passed; Codex definitions load but require normal trust approval |

Overall: local implementation, plugin loading, and authenticated skill workflows
are verified. Claude runtime lifecycle callbacks are verified; Codex hook firing
remains unverified pending trust approval.
The successful workflow checks used existing runtime authentication without
copying credentials or changing live configuration. Evidence stayed in temporary
stores. Earlier isolated-login and network failures are superseded by these
successful checks.
