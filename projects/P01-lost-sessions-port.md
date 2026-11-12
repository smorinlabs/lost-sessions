## [~] Project P01: Port lost-sessions into a pluggable package (v0.2.0)
**Goal/Requirement**: Move `lost-sessions` out of `smorin/smorin-bootstrap` into this
package, with agents and session managers as pluggy plugins, as in `simonw/llm`.
- Behavior matches the original script per the Section 8 contract of design 0006
  (commands, flags, defaults, exit codes, stdout data, history format).
- Session discovery moves in: four built-in agent plugins (Claude Code, Codex, Muse,
  OpenCode) and two built-in session-manager plugins (Herdr, Rex).
- New commands: `inventory --json`, `plugins`, `install`, `uninstall`.

**Out of Scope**
- The `smorin-bootstrap` change that installs this package (separate PR in that repo).
- Muse review install (T8). Switching the skill's `session-inventory` to this library.

**References**
- Design: `docs/design/0006-lost-sessions-plugin-design.md`
- Research: `docs/research/0001-llm-plugin-pattern.md`
- Port sources: `smorin/smorin-bootstrap` `713e443`; `smorinlabs/smorinlabs-skills` `cf83bf1`

### Tests & Tasks
- [x] [P01-T01] Initialize the repo from py-launch-blueprint with Template Press (PR #7)
- [~] [P01-T02] Remove the template's example CLI, web service and container; add the plugin skeleton (PR 1)
- [x] [P01-TS01] Test mode blocks third-party entry points; built-ins still load (TS-1)
- [x] [P01-TS02] Fake agent and manager plugins register and unregister through the hooks (TS-2)
- [ ] [P01-T03] Port the four scanners from `session-inventory` into agent plugins; add `inventory` (PR 2)
- [ ] [P01-TS04] Scanner tests ported from `tests/test_session_inventory.py` (TS-4)
- [ ] [P01-TS06] `inventory --json` matches `session-inventory list --json` on fixture stores (TS-6)
- [ ] [P01-T04] Port core, the Herdr and Rex plugins, and the click CLI (PR 3)
- [ ] [P01-TS03] Contract suite runs against every registered agent and manager (TS-3)
- [ ] [P01-TS05] The 118 original tests port under the Section 8 contract (TS-5)
- [ ] [P01-TS10] Live test passes against real Herdr and Rex (TS-10)
- [ ] [P01-TS11] Stored-data compatibility fixtures for history and listing (TS-11)
- [ ] [P01-T05] Add `plugins`, `install`, `uninstall` (PR 4)
- [ ] [P01-TS07] Wheel installs into a clean `uv tool` env; built-ins and a fake plugin are listed (TS-7)
- [ ] [P01-TS08] `install --print` for `uv tool` and virtualenv; plugin survives `uv tool upgrade --reinstall` (TS-8)
- [ ] [P01-TS09] `uv-receipt.toml` detection signal still exists (TS-9)
- [ ] [P01-T06] Plugin-author docs (PR 5)
- [ ] Regression Test Status

### Deliverable
```bash
$ lost-sessions list
$ lost-sessions inventory --json
$ lost-sessions plugins --all
```

### Automated Verification
- `just check` passes; `press verify` passes; CI `ci-ok` is green.

### Manual Verification
- After a reboot, `lost-sessions recover` lists and reopens dropped sessions in Herdr and Rex.
