"""`install` / `uninstall`: add or remove plugins (design 0006, Section 7.4).

The installed plugins are the distributions in this environment that declare a
`lost_sessions` entry point. In a `uv tool` environment the command reinstalls
the tool with the new plugin list (`uv tool install lost-sessions --with ...`);
it never runs pip, because a pip-installed plugin is lost on the next
`uv tool upgrade` (simonw/llm #575). Each requirement keeps where the package
came from (PEP 610 `direct_url.json`): PyPI, a local wheel, git, or an
editable checkout.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess  # nosec B404 - fixed argv lists, never a shell
import sys
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from pydantic import BaseModel

from lost_sessions.plugins import ENTRY_POINT_GROUP

TOOL = "lost-sessions"
_PRE_RELEASE = re.compile(r"(a|b|rc|dev)\d*", re.I)


def normalized(name: str) -> str:
    """PEP 503 name normalization: lost_sessions.Alpha == lost-sessions-alpha."""
    return re.sub(r"[-_.]+", "-", name).lower()


def name_of(dist: Any) -> str:  # noqa: ANN401 - an importlib Distribution
    return str(dist.metadata["Name"])


def installed_plugins() -> list[Any]:
    """Distributions in this environment with a lost_sessions entry point."""
    found = {}
    for dist in metadata.distributions():
        name = name_of(dist)
        if normalized(name) == normalized(TOOL):
            continue
        if any(ep.group == ENTRY_POINT_GROUP for ep in dist.entry_points):
            found.setdefault(normalized(name), dist)
    return [found[key] for key in sorted(found)]


class Source(BaseModel):
    """Where an installed distribution came from."""

    kind: Literal["index", "url", "vcs", "editable"]
    spec: str  # what to pass to uv: a requirement, or a path for editable


def source_of(dist: Any) -> Source:  # noqa: ANN401 - an importlib Distribution
    name = name_of(dist)
    raw = dist.read_text("direct_url.json")
    if not raw:
        version = str(dist.version)
        if _PRE_RELEASE.search(version):  # a resolver would skip it: keep it pinned
            return Source(kind="index", spec=f"{name}=={version}")
        return Source(kind="index", spec=name)
    info = json.loads(raw)
    url = str(info.get("url", ""))
    if (info.get("dir_info") or {}).get("editable"):
        return Source(kind="editable", spec=unquote(urlparse(url).path))
    vcs = info.get("vcs_info")
    if vcs:
        commit = vcs.get("commit_id") or vcs.get("requested_revision") or ""
        ref = f"@{commit}" if commit else ""
        return Source(kind="vcs", spec=f"{name} @ {vcs.get('vcs', 'git')}+{url}{ref}")
    return Source(kind="url", spec=f"{name} @ {url}")


def with_args(dist: Any) -> list[str]:  # noqa: ANN401 - an importlib Distribution
    source = source_of(dist)
    if source.kind == "editable":
        return ["--with-editable", source.spec]
    return ["--with", source.spec]


def tool_args(dist: Any) -> list[str]:  # noqa: ANN401 - an importlib Distribution
    source = source_of(dist)
    if source.kind == "editable":
        return ["--editable", source.spec]
    return [source.spec]


def in_uv_tool() -> bool:
    """A `uv tool` environment: uv writes uv-receipt.toml into its prefix.

    Only the file's existence is checked; it is never parsed."""
    return Path(sys.prefix, "uv-receipt.toml").is_file()


class Commands(BaseModel):
    uv: list[str]
    pip: list[str]
    applies: Literal["uv", "pip"]


def commands(
    action: Literal["install", "uninstall"], packages: Sequence[str]
) -> Commands:
    plugins = installed_plugins()
    if action == "uninstall":
        drop = {normalized(p) for p in packages}
        plugins = [d for d in plugins if normalized(name_of(d)) not in drop]
    try:
        tool = tool_args(metadata.distribution(TOOL))
    except metadata.PackageNotFoundError:
        tool = [TOOL]
    uv = ["uv", "tool", "install", *tool]
    for d in plugins:
        uv += with_args(d)
    if action == "install":
        for p in packages:
            uv += ["--with", p]
    pip = [sys.executable, "-m", "pip", action, *packages]
    return Commands(uv=uv, pip=pip, applies="uv" if in_uv_tool() else "pip")


def run(
    action: Literal["install", "uninstall"], packages: Sequence[str], print_only: bool
) -> int:
    from lost_sessions.core import error, warn

    if action == "uninstall":
        installed = {normalized(name_of(d)) for d in installed_plugins()}
        missing = [p for p in packages if normalized(p) not in installed]
        if missing:
            error(f"not installed as lost-sessions plugins: {', '.join(missing)}")
            return 1
    cmds = commands(action, packages)
    print(f"uv:   {shlex.join(cmds.uv)}")
    print(f"pip:  {shlex.join(cmds.pip)}")
    print(f"applies here: {cmds.applies}")
    if print_only:
        return 0
    if cmds.applies != "uv":
        error(
            "not a `uv tool` environment, so nothing was run; run the pip line "
            "above yourself if this environment is yours to change"
        )
        return 1
    uv = shutil.which("uv")
    if uv is None:
        error("uv is not on PATH; run the uv line above once uv is installed")
        return 1
    warn(
        "this reinstalls lost-sessions with only its plugins: packages added with "
        "--with that are not plugins, and a version pin on lost-sessions, are dropped"
    )
    proc = subprocess.run([uv, *cmds.uv[1:]], check=False)  # noqa: S603  # nosec B603 - fixed argv
    return 0 if proc.returncode == 0 else 1
