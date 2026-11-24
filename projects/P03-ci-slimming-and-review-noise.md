## [~] Project P03: CI slimming and review-bot noise

**References**
- **Trunk:** [PROJECTS.md](../PROJECTS.md)
- **Template source:** smorinlabs/py-launch-blueprint PR #612 (`ci: cut pr job count without changing required checks`)
- **CI reference:** [CI/CD with GitHub Actions](../docs/source/tasks/using_ci_cd.md)

**Goal/Requirement**: Remove pull-request CI noise and port the template's
CI slimming without changing which checks report.
- Delete the unconfigured `Claude Code Review` workflow; Muse is the reviewer.
- Port the template's `changes` detector: release-please fast path,
  `release_tooling` gate for `release-generation`, and no `grep -q` under
  `pipefail`.
- Merge the small static `ci.yml` jobs into `lint` and `typecheck`.
- PR-only concurrency for `dependency-review.yml`.
- Path-filter CodeQL on pull requests (no `code_scanning` rule exists).

**Out of Scope**
- The `Muse PR review` startup failure on bot PRs. Its cause is the
  repository Actions policy `muse-review: smorin pull_request only`, which
  admits only one actor; no workflow edit can change it. Owner decision.
- `lint.yml` consolidation, `merge_group` triggers, the stale
  `difftree-pr-comment` workflow registration.

**Decisions**
- No required status checks exist (no branch protection; the only ruleset is
  the org `merge-methods: no squash`), so job merges cannot strand a check.
- Job-level `if:` only; no workflow-level filters on `ci.yml`.

### Tests & Tasks
- [x] [P03-T01] Delete `claude-code-review.yml`, its test and setup doc
- [x] [P03-T02] Port the `changes` detector and gate `release-generation`
- [x] [P03-T03] Merge `lint`/`toml-format`/`shellcheck`/`docs` and `typecheck`/`import-boundaries`
- [x] [P03-T04] PR-only concurrency on `dependency-review.yml`
- [x] [P03-T05] CodeQL `pull_request` path filter
- [x] [P03-TS01] `tests/meta/test_ci_change_detection.py` covers the detector and job shape
- [ ] [P03-TS02] PR CI green; job count measured against the ~24-job baseline

### Automated Verification
- `just check` passes; `uv run pytest tests/meta` passes.
