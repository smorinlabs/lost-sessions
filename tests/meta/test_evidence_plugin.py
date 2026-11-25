"""Installing the companion skill must not enable recording hooks."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_evidence_plugin_is_optional_and_keeps_hooks_separate():
    plugin = ROOT / "plugins" / "lost-sessions"
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "lost-sessions"
    assert manifest["skills"] == "./skills/"
    assert "hooks" not in manifest
    assert not (plugin / "hooks" / "hooks.json").exists()
    assert not (plugin / "hooks.json").exists()
    agy_manifest = plugin / ".antigravity-plugin" / "plugin.json"
    assert not agy_manifest.is_symlink()
    agy_data = json.loads(agy_manifest.read_text())
    assert agy_data["$schema"] == "https://antigravity.google/schemas/v1/plugin.json"
    assert agy_data["name"] == manifest["name"]
    assert agy_data["version"] == manifest["version"]
    assert agy_data["description"] == manifest["description"]
    assert "_generated" not in agy_data
    assert "hooks" not in agy_data
    codex_manifest = plugin / ".codex-plugin" / "plugin.json"
    assert not codex_manifest.is_symlink()
    assert json.loads(codex_manifest.read_text()) == manifest
    catalog = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    entries = [p for p in catalog["plugins"] if p["name"] == "lost-sessions"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["policy"]["installation"] == "AVAILABLE"
    assert entry["source"] == {"source": "local", "path": "./plugins/lost-sessions"}
    claude_catalog = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )
    claude_entries = [
        p for p in claude_catalog["plugins"] if p["name"] == "lost-sessions"
    ]
    assert len(claude_entries) == 1
    assert claude_entries[0]["source"] == "./plugins/lost-sessions"
    for item in (entry, claude_entries[0]):
        assert item["version"] == manifest["version"]
        assert item["description"] == manifest["description"]
    for tool in ("claude", "codex"):
        template = json.loads(
            (
                plugin
                / "skills"
                / "lost-sessions"
                / "references"
                / f"{tool}-hooks.json"
            ).read_text()
        )
        assert set(template["hooks"]) == {"SessionStart", "SessionEnd"}
    agy_template = json.loads(
        (
            plugin
            / "skills"
            / "lost-sessions"
            / "references"
            / "antigravity-hooks.json"
        ).read_text()
    )
    assert set(agy_template["lost-sessions-evidence"]) == {"SessionStart"}
