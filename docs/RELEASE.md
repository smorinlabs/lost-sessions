# Release process

Release flow per ADR-05 + ADR-06 + ADR-07. See
`analysis/synthesis/items/ITM-060` for the full sequencing.

## Default flow (release-please)

1. Merge `feat:` / `fix:` / `perf:` commits to `main`.
2. The `release-please` workflow opens (or updates) a release PR
   proposing the next semver bump + a `CHANGELOG.md` entry. Its generated
   commit updates `pyproject.toml` and the editable root entry in `uv.lock`
   atomically, so the PR is internally consistent from its first revision.
3. Merge the release PR. release-please pushes a `v*` tag and publishes a
   GitHub Release.
4. The `publish` workflow fires on the tag:
   - `build` job: tag-reachability + version-matches-tag, then `uv build`.
   - `publish-testpypi`: OIDC upload to TestPyPI (env `testpypi`).
   - `publish-pypi`: OIDC upload to PyPI (env `pypi`).

## Complete commit selection and preview

`scripts/release_please.cjs` runs release-please `17.11.2` with the Bun version
in `.bun-version`. `scripts/release_commits.cjs` supplies all non-merge commits
reachable from the source revision but absent from the previous release's
ancestry. Branch commits authored before that release remain included if they
were merged afterward. Merge bodies cannot contribute duplicate release notes.
Separate commits with identical subjects remain separate changes.

The plugin runs before upstream parsing and version calculation. Full commit
messages, breaking-change trailers, release overrides, and changed paths are
retained. Configured path exclusions still apply. `build(deps)` and
`build(deps-dev)` join the existing dependency scopes in the Dependencies section;
ordinary builds and chores remain hidden. Only one package at path `.` is
supported. A multi-package configuration fails explicitly.

The cutoff is the configured `last-release-sha`, otherwise the release found by
upstream discovery, otherwise `bootstrap-sha` for a first release. With no
cutoff, all local history is considered. Annotated tags resolve to their commits.
The checkout must contain full history and tags. An explicitly configured cutoff
that is missing or outside the source revision's ancestry stops generation.
Discovery ignores releases, tags, and merged release PRs whose commits are
outside the pinned source's ancestry. A later release therefore cannot become
the cutoff for an older preview. The upstream discovery scan retains its search
limit; the plugin's final commit selection always covers the complete range.

From the repository root, after `just setup`, preview the committed `HEAD`:

```bash
GITHUB_REPOSITORY="$(gh repo view --json nameWithOwner --jq .nameWithOwner)" \
RELEASE_PLEASE_TOKEN="$(gh auth token)" \
RELEASE_PLEASE_APPLY=0 \
bun scripts/release_please.cjs > /tmp/release-preview.json
```

The preview makes no GitHub writes. JSON on standard output contains the source
commit, cutoff, selected commits, proposed version, title, notes, rendered files,
and any merged releases awaiting publication. Diagnostics go to standard error.
When a merged release awaits publication, the preview uses that release as the
baseline for the next PR. This models the publication order without creating a
tag or release. The pending release's own changes are not proposed again, and
an obsolete first-release bootstrap cutoff is not consulted. An invalid explicit
`last-release-sha` still stops the preview or apply operation before any writes.
The preview reads committed files; commit local changes before inspecting them.
`RELEASE_PLEASE_SOURCE` selects another locally available revision, and
`RELEASE_PLEASE_BRANCH` selects the target branch. Their defaults are `GITHUB_SHA`
or `HEAD`, and the GitHub repository's default branch, respectively.

Only `RELEASE_PLEASE_APPLY=1` enables writes. The workflow installs frozen
dependencies before supplying its App/PAT credential as `RELEASE_PLEASE_TOKEN`.
It publishes already-merged release PRs first, loads a fresh manifest, then
creates or updates the next PR using upstream branch names, labels, and atomic
file updates. Each write checks that the target branch still matches the pinned
source revision. A branch move during an upstream API operation is still
possible; the workflow's serialized runs and subsequent source checks limit
that race rather than making a multi-request operation transactional.

If history is shallow, fetch it with `git fetch --unshallow --tags`. If a cutoff
is missing or unrelated, verify it against this repository's history and correct
the configuration before retrying. If the source is stale, let the newer push
run or rerun from its revision. Do not manually remove notes to conceal a
generator defect. Run `just test-release` for the offline regression suite;
`just check` and the required `ci-ok` check include it.

## Disabling release-please (downstream projects)

If a generated project doesn't want PR-driven version proposals:

```bash
# Rename to disable:
mv .github/workflows/release-please.yml .github/workflows/release-please.yml.disabled
# Then bump [project] version manually before tagging:
$EDITOR pyproject.toml
uv lock
$EDITOR .release-please-manifest.json
git tag -a v1.2.3 -m "v1.2.3"
git push origin v1.2.3
```

The `publish` workflow still fires on the tag and uploads to PyPI.
Keep the package, lockfile, and release manifest versions consistent before
committing and tagging.

## Token setup

release-please must authenticate with a token that can **both** open PRs and
trigger downstream workflows (so merging the release PR fires `publish.yml`).
`GITHUB_TOKEN` does neither reliably — it never re-triggers other workflows, and
org policy can block it from opening PRs — so it is **not** used. Configure one
of these two mechanisms instead:

1. **GitHub App (preferred).** Create a GitHub App with **Contents** and
   **Pull requests: write**, install it on this repo, then add two secrets:
   - `RELEASE_PLEASE_CLIENT_ID` — the App's Client ID (e.g. `Iv23li...`)
   - `RELEASE_PLEASE_PRIVATE_KEY` — the App's private key (`.pem` contents)

   The workflow mints a short-lived installation token from these.

2. **Fallback PAT.** Create a fine-grained Personal Access Token scoped to this
   repo with **Contents** and **Pull requests: write**, stored as the
   `RELEASE_PLEASE_APP_TOKEN` secret.

With neither configured, release-please fails fast rather than silently
producing a release that can't publish.

## First-release cutover (one-time)

Template generation starts `pyproject.toml`, the editable `uv.lock` entry, and
`.release-please-manifest.json` at `0.1.0`. It removes the source repository's
`bootstrap-sha` from `release-please-config.json`: a fresh repository has its
own commit history, so it must not inherit another repository's release cutoff.

Configure the release credentials above before enabling publication. After the
initialization PR lands, release-please considers this repository's commits and
proposes the next version when it finds releasable changes. Initializing the
version files does not itself publish a release.

For an existing project adopting release-please, seed the manifest with that
project's current version. Set an optional `bootstrap-sha` only when you need
to exclude older commits, and choose a full commit ID from that repository.
See the [release-please bootstrap reference](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md#bootstrapping).
