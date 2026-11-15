#!/usr/bin/env python3
"""Temporary SYNTHETIC ACCEPTANCE input; production triage gates are unchanged."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

REPOSITORY = "smorinlabs/lost-sessions"
FIXTURE = "docs/source/_muse_triage_acceptance.md"
BAD_URL = "https://example.com/muse-triage-acceptance-not-found"
LABEL = "SYNTHETIC ACCEPTANCE"
FIXTURE_TEXT = (
    "---\norphan: true\n---\n\n# Synthetic triage acceptance fixture\n\n"
    "Temporary test data, not an actual weekly-audit failure. Never merge this PR.\n\n"
    f"[Public example domain]({BAD_URL})\n"
)
FIXTURE_LOG = (
    f"{FIXTURE}:9: (line    9) broken {BAD_URL} - SYNTHETIC ACCEPTANCE 404 fixture\n"
)


def check_caller(environ: Mapping[str, str], event: dict[str, Any]) -> tuple[str, str]:
    """Bind the fixture to the real human/default-branch invocation before mocks."""
    repository = event.get("repository", {})
    owner = repository.get("owner", {})
    sender = event.get("sender", {})
    default = repository.get("default_branch", "")
    if (
        environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or repository.get("full_name") != REPOSITORY
        or owner.get("type") != "Organization"
        or owner.get("login") != "smorinlabs"
        or sender.get("type") != "User"
        or sender.get("login") != "smorin"
        or environ.get("GITHUB_ACTOR") != "smorin"
        or environ.get("MUSE_TRIGGERING_ACTOR") != "smorin"
        or not default
        or environ.get("GITHUB_REF") != f"refs/heads/{default}"
        or event.get("ref") not in (default, f"refs/heads/{default}")
    ):
        raise ValueError(
            "SYNTHETIC ACCEPTANCE requires the approved human on the default branch"
        )
    run_id, sha = (
        environ.get("GITHUB_RUN_ID", ""),
        environ.get("MUSE_TRIAGE_TRUSTED_SHA", ""),
    )
    if not re.fullmatch(r"[1-9][0-9]*", run_id) or not re.fullmatch(
        r"[0-9a-f]{40}", sha
    ):
        raise ValueError(
            "SYNTHETIC ACCEPTANCE requires the actual run id and trusted checkout SHA"
        )
    return run_id, sha


def fixture_api(api_class: type[Any], run_id: str, sha: str, default: str) -> type[Any]:
    """Mock only this run/job lookup; preserve real duplicate and write APIs."""

    class FixtureAPI(api_class):
        def get(self, path: str) -> object:
            if path == f"repos/{REPOSITORY}/actions/runs/{run_id}":
                return {
                    "id": int(run_id),
                    "name": "weekly-audit",
                    "conclusion": "failure",
                    "event": "workflow_dispatch",
                    "head_branch": default,
                    "head_sha": sha,
                }
            if path == f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100":
                return {
                    "jobs": [
                        {
                            "id": int(run_id),
                            "name": "docs-linkcheck",
                            "conclusion": "failure",
                        }
                    ]
                }
            return super().get(path)

    return FixtureAPI


def actions_outputs(path: Path) -> dict[str, str]:
    """Read only the real helper's delimited outputs for a labeled prompt."""
    result = {}
    lines = iter(path.read_text().splitlines())
    for line in lines:
        if "<<" not in line:
            continue
        key, delimiter = line.split("<<", 1)
        value = []
        for item in lines:
            if item == delimiter:
                break
            value.append(item)
        result[key] = "\n".join(value)
    return result


def load_helper(root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "acceptance_triage", root / ".github/scripts/muse_audit_triage.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("SYNTHETIC ACCEPTANCE cannot load the real triage helper")
    helper = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(helper)
    finally:
        sys.dont_write_bytecode = previous
    return helper


def prepare(environ: Mapping[str, str] = os.environ) -> None:
    original = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text())
    run_id, sha = check_caller(environ, original)
    root = Path(environ["GITHUB_WORKSPACE"]).resolve()
    fixture = root / FIXTURE
    if fixture.exists() or fixture.is_symlink():
        raise ValueError("SYNTHETIC ACCEPTANCE fixture path already exists")
    if any(parent.is_symlink() for parent in (root / "docs", root / "docs/source")):
        raise ValueError("SYNTHETIC ACCEPTANCE fixture must not traverse symlinks")
    helper = load_helper(root)
    helper.GitHub = fixture_api(
        helper.GitHub, run_id, sha, original["repository"]["default_branch"]
    )
    real_download = helper.download_logs
    fixture_log_url = (
        f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{run_id}/logs"
    )

    def download(url: str, token: str, size_cap: int = 2_000_000) -> str:
        return (
            FIXTURE_LOG
            if url == fixture_log_url
            else real_download(url, token, size_cap)
        )

    helper.download_logs = download
    event = copy.deepcopy(original)
    event["inputs"] = {**(event.get("inputs") or {}), "run_id": run_id}
    print(
        "SYNTHETIC ACCEPTANCE: failed-run metadata and log input are fixtures; Action, Muse, validation and PR APIs are real. Never merge the generated PR."
    )
    with tempfile.TemporaryDirectory(
        prefix="muse-acceptance-", dir=environ["RUNNER_TEMP"]
    ) as temporary:
        event_path = Path(temporary) / "event.json"
        event_path.write_text(json.dumps(event))
        helper.prepare({**environ, "GITHUB_EVENT_PATH": str(event_path)})
    values = actions_outputs(Path(environ["GITHUB_OUTPUT"]))
    if values.get("should_run") != "true":
        raise ValueError("SYNTHETIC ACCEPTANCE helper did not prepare a repair")
    # This is intentionally after real prepare's clean-checkout/freeze guards.
    # Only the final repaired addition may appear on the never-merge test PR.
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(FIXTURE_TEXT)
    prompt = (
        "SYNTHETIC ACCEPTANCE, not an actual weekly-audit failure. Repair only "
        f"the temporary fixture {FIXTURE}; its public example-domain link should "
        "use the stable https://example.com/ page. Never merge this test PR.\n"
        + values["prompt"]
    )
    helper.output(environ["GITHUB_OUTPUT"], "prompt", prompt)


def validate_fixture(environ: Mapping[str, str] = os.environ) -> None:
    """A model no-op must not publish the pre-injected broken test document."""
    root = Path(environ["GITHUB_WORKSPACE"]).resolve()
    fixture = root / FIXTURE
    if (
        any(
            parent.is_symlink()
            for parent in (root / "docs", root / "docs/source", fixture)
        )
        or not fixture.is_file()
    ):
        raise ValueError("SYNTHETIC ACCEPTANCE fixture must remain a regular file")
    text = fixture.read_text()
    if text == FIXTURE_TEXT or BAD_URL in text or "https://example.com/" not in text:
        raise ValueError(
            "SYNTHETIC ACCEPTANCE model did not repair the injected fixture"
        )
    print(
        "SYNTHETIC ACCEPTANCE: the fixture changed and its broken URL was replaced; production scope/URL validation follows."
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["validate-fixture"]:
        validate_fixture()
    elif not sys.argv[1:]:
        prepare()
    else:
        raise SystemExit("SYNTHETIC ACCEPTANCE: unsupported command")
