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
    assert (plugin / ".codex-plugin" / "plugin.json").resolve() == (
        plugin / ".claude-plugin" / "plugin.json"
    ).resolve()
    catalog = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    entry = next(p for p in catalog["plugins"] if p["name"] == "lost-sessions")
    assert entry["policy"]["installation"] == "AVAILABLE"
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
