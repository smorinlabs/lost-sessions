# lost-sessions companion skill

This optional plugin helps agents recover lost sessions and record or inspect
session evidence with the `lost-sessions` CLI. The CLI must already be installed.

The plugin exposes one skill, **lost-sessions**. It keeps runtime lifecycle
observations separate from assessments such as "main work probably complete."
It does not enable hooks or record data merely because it is installed.

From a local checkout, add the checkout's absolute path as a marketplace in the
runtime, then install `lost-sessions@lost-sessions`:

- Claude Code: `/plugin marketplace add PATH`, then
  `/plugin install lost-sessions@lost-sessions`.
- Codex: `codex plugin marketplace add PATH`, then
  `codex plugin add lost-sessions@lost-sessions`.

Here `PATH` is the absolute path to the repository checkout, obtained by running
`pwd` from its root. The Python package and this plugin are separate installs.

Read [the skill](skills/lost-sessions/SKILL.md) for its workflow,
[the record guide](skills/lost-sessions/references/records.md) for the record
format, and [the hook guide](skills/lost-sessions/references/hooks.md) for
optional lifecycle recording. The plugin has no automatic hook declaration.
