"""Temporary synthetic inputs stay separate from real runtime/publication APIs."""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "triage_acceptance", ROOT / ".github/scripts/muse_triage_acceptance.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def caller():
    event = {
        "ref": "refs/heads/main",
        "inputs": None,
        "repository": {
            "full_name": acceptance.REPOSITORY,
            "default_branch": "main",
            "owner": {"login": "smorinlabs", "type": "Organization"},
        },
        "sender": {"login": "smorin", "type": "User"},
    }
    env = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": acceptance.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_ACTOR": "smorin",
        "MUSE_TRIGGERING_ACTOR": "smorin",
        "GITHUB_RUN_ID": "123",
        "MUSE_TRIAGE_TRUSTED_SHA": "a" * 40,
    }
    return env, event


@pytest.mark.parametrize(
    "field,value",
    [
        ("GITHUB_ACTOR", "other"),
        ("MUSE_TRIGGERING_ACTOR", "other"),
        ("GITHUB_EVENT_NAME", "workflow_run"),
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_REPOSITORY", "other/repo"),
        ("GITHUB_RUN_ID", "0"),
        ("MUSE_TRIAGE_TRUSTED_SHA", "invalid"),
    ],
)
def test_real_caller_refused_before_loading_or_mocking(
    tmp_path, monkeypatch, field, value
):
    env, event = caller()
    env[field] = value
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    env["GITHUB_EVENT_PATH"] = str(path)
    monkeypatch.setattr(
        acceptance, "load_helper", lambda *args: pytest.fail("must not load helper")
    )
    with pytest.raises(ValueError, match="SYNTHETIC ACCEPTANCE"):
        acceptance.prepare(env)


def test_fake_target_routing_keeps_real_duplicate_and_publication_apis():
    calls = []

    class RealAPI:
        def get(self, path):
            calls.append(("GET", path))
            return "real"

        def post(self, path, data):
            calls.append(("POST", path, data))
            return "posted"

    api = acceptance.fixture_api(RealAPI, "123", "a" * 40, "main")()
    target = api.get(f"repos/{acceptance.REPOSITORY}/actions/runs/123")
    assert target["id"] == 123 and target["head_sha"] == "a" * 40
    assert target["event"] == "workflow_dispatch" and target["conclusion"] == "failure"
    assert (
        api.get(f"repos/{acceptance.REPOSITORY}/actions/runs/123/jobs?per_page=100")[
            "jobs"
        ][0]["name"]
        == "docs-linkcheck"
    )
    assert api.get("repos/other/repo/actions/runs/123") == "real"
    assert (
        api.get(
            "repos/smorinlabs/lost-sessions/pulls?head=smorinlabs:bot/weekly-audit-123&state=open"
        )
        == "real"
    )
    assert (
        api.post(
            "repos/smorinlabs/lost-sessions/pulls", {"title": "SYNTHETIC ACCEPTANCE"}
        )
        == "posted"
    )
    assert [call[0] for call in calls] == ["GET", "GET", "POST"]


def git(root, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.check_output(
        ["git", "-C", str(root), "-c", "core.hooksPath=/dev/null", *args],
        env=env,
        text=True,
    ).strip()


def test_real_prepare_freezes_clean_tree_before_fixture_and_preserves_original_event(
    tmp_path, monkeypatch
):
    root = tmp_path / "checkout"
    root.mkdir()
    for name in (
        ".github/scripts/muse_audit_triage.py",
        ".github/muse-audit-triage/runtime.py",
        ".github/muse-audit-triage/policy.json",
        ".github/muse-audit-triage/triage-settings.json",
    ):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    (root / "docs/source").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", sha)
    env, event = caller()
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    original = event_path.read_bytes()
    runner = tmp_path / "runner"
    runner.mkdir()
    output, envfile = tmp_path / "output", tmp_path / "env"
    output.touch()
    envfile.touch()
    env.update(
        GITHUB_EVENT_PATH=str(event_path),
        GITHUB_WORKSPACE=str(root),
        RUNNER_TEMP=str(runner),
        MUSE_TRIAGE_TRUSTED_SHA=sha,
        GITHUB_OUTPUT=str(output),
        GITHUB_ENV=str(envfile),
        GH_TOKEN="fake",
    )
    original_env = copy.deepcopy(env)
    previous_bytecode = sys.dont_write_bytecode
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    helper = acceptance.load_helper(root)
    assert sys.dont_write_bytecode is False
    monkeypatch.setattr(sys, "dont_write_bytecode", previous_bytecode)
    assert not list((root / ".github").rglob("__pycache__"))
    calls, downloads = [], []

    class RealAPI:
        def __init__(self, token):
            pass

        def get(self, path):
            calls.append(path)
            return []

    helper.GitHub = RealAPI
    helper.download_logs = lambda *args: downloads.append(args) or "real log"
    monkeypatch.setattr(acceptance, "load_helper", lambda *args: helper)
    acceptance.prepare(env)
    assert event_path.read_bytes() == original and env == original_env
    assert len(calls) == 1 and "/pulls?head=" in calls[0]
    assert downloads == []
    assert helper.download_logs("https://other.invalid/log", "fake") == "real log"
    values = acceptance.actions_outputs(output)
    assert values["should_run"] == "true"
    assert values["base"] == sha and git(root, "rev-parse", "HEAD") == sha
    assert values["prompt"].startswith("SYNTHETIC ACCEPTANCE")
    assert acceptance.BAD_URL in values["prompt"]
    assert (root / acceptance.FIXTURE).read_text() == acceptance.FIXTURE_TEXT
    assert git(root, "ls-files", "--", acceptance.FIXTURE) == ""
    assert "GITHUB_EVENT_PATH" not in envfile.read_text()


@pytest.mark.parametrize(
    "changed",
    [
        None,
        acceptance.FIXTURE_TEXT,
        "No link remains",
        acceptance.FIXTURE_TEXT + "\nChanged.",
    ],
)
def test_unrepaired_or_removed_fixture_is_not_publication_evidence(tmp_path, changed):
    fixture = tmp_path / acceptance.FIXTURE
    fixture.parent.mkdir(parents=True)
    if changed is not None:
        fixture.write_text(changed)
    with pytest.raises(ValueError, match="SYNTHETIC ACCEPTANCE"):
        acceptance.validate_fixture({"GITHUB_WORKSPACE": str(tmp_path)})


def test_repaired_regular_fixture_passes_acceptance_preflight(tmp_path):
    fixture = tmp_path / acceptance.FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        acceptance.FIXTURE_TEXT.replace(acceptance.BAD_URL, "https://example.com/")
    )
    acceptance.validate_fixture({"GITHUB_WORKSPACE": str(tmp_path)})


def test_acceptance_workflow_is_manual_and_keeps_production_action_scope():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/muse-triage-acceptance.yml").read_text()
    )
    production = yaml.safe_load(
        (ROOT / ".github/workflows/audit-triage.yml").read_text()
    )
    assert set(workflow.get("on", workflow.get(True))) == {"workflow_dispatch"}
    job = workflow["jobs"]["triage"]
    assert (
        "github.actor == 'smorin'" in job["if"]
        and "github.triggering_actor == 'smorin'" in job["if"]
    )
    assert "vars.MUSE_AUDIT_TRIAGE_ENABLED == 'true'" in job["if"]
    assert (
        "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
        in job["if"]
    )
    action = next(step for step in job["steps"] if step.get("id") == "muse")
    actual = next(
        step
        for step in production["jobs"]["triage"]["steps"]
        if step.get("id") == "muse"
    )
    assert action == actual
    create = next(step for step in job["steps"] if step.get("id") == "create-pr")
    assert "SYNTHETIC ACCEPTANCE" in create["run"] and "Never merge" in create["run"]
    validate = next(step for step in job["steps"] if step.get("id") == "validate")
    assert validate["run"].splitlines() == [
        "python3 .github/scripts/muse_triage_acceptance.py validate-fixture",
        'python3 "$MUSE_TRIAGE_HELPER" validate triage',
    ]
