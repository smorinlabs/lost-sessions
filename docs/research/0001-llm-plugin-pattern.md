# 0001. The `simonw/llm` plugin pattern, and how `lost-sessions` should copy it

**Purpose.** Research only: how `simonw/llm` does plugins, with sources. The decided `lost-sessions` design is [design 0006](../design/0006-lost-sessions-plugin-design.md). T6 (`lost-sessions`, Python) will copy `llm`'s plugin library and technique exactly, with Herdr and Rex shipped as built-in plugins. T3 (`brot`, Rust) will adapt the idea later. This document records how `llm` actually does it, from source, and proposes the `lost-sessions` mapping. It decides nothing for the Rust case.

**Sources and pinning.**
- Code excerpts come from `simonw/llm` `main` at commit `8b475ffdfc2d33aa86c9518baff3ac94bcea409e` (2026-11-11, `version = "0.37.2"`). Code links below are pinned to that commit: `L@` = `https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/`.
- Doc links point to the published *stable* docs (https://llm.datasette.io/en/stable/plugins/). They can drift from the pinned code.
- Issue numbers are `simonw/llm` issues, read through the GitHub API on 2026-11-12.
- Load and call order was **verified by running** `llm==0.37.2` with `pluggy 1.7.0` (`uv run --with llm==0.37.2`), not taken from memory.

**Status labels used below.** **Fact** = read in source, docs, or an issue, or observed by running code. **Inference** = my reading of the facts. **Proposal** = a recommendation for T6, not yet agreed.

---

## 1. Summary (the pattern in ten lines)

1. The library is **`pluggy`** (the plugin system from pytest), a declared dependency of `llm`.
2. One module, `llm/hookspecs.py`, declares six hooks. **Every hook is a `register_*(register)` callback**: core passes a `register` function, and each plugin calls it with objects (models, tools, loaders) or attaches commands to the click group.
3. One module-level `PluginManager("llm")` lives in `llm/plugins.py`.
4. Third-party plugins are found through the Python entry-point group **`llm`**, declared in each plugin's `pyproject.toml`.
5. Built-in plugins live in `llm/default_plugins/*.py`. They use **the same `@llm.hookimpl` hooks**, but they are **not** entry points: `llm` imports them by module path and registers them with `pm.register(...)`.
6. `LLM_LOAD_PLUGINS` limits which *third-party* plugins load (`''` = none). Built-ins always load.
7. `llm plugins` lists plugins as JSON. It hides built-ins unless `--all` is passed. `llm install` / `llm uninstall` wrap `pip` in `llm`'s own environment.
8. Tests stop entry-point loading by setting `sys._called_from_test`, then register throwaway plugin *classes* with `pm.register(...)` and remove them with `pm.unregister(...)`.
9. Third-party packages are named `llm-<name>` and start from the cookiecutter template `simonw/llm-plugin`.
10. The main pain points in issues: a broken or slow plugin breaks or slows every command; `uv tool upgrade` drops pip-installed plugins; built-ins cannot be disabled.

---

## 2. Q1 — Library: `pluggy`, hookspecs, plugin manager, `@hookimpl`

**Fact.** `pluggy` is a runtime dependency (`pyproject.toml` line 37: `"pluggy",`).

**Fact.** The hook specification module ([`llm/hookspecs.py` L1–34](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/hookspecs.py#L1-L34)), abridged:

```python
from pluggy import HookimplMarker, HookspecMarker

hookspec = HookspecMarker("llm")
hookimpl = HookimplMarker("llm")


@hookspec
def register_commands(cli):
    """Register additional CLI commands, e.g. 'llm mycommand ...'"""


@hookspec
def register_models(register, model_aliases):
    "Register additional model instances representing LLM models that can be called"


# ... register_embedding_models(register), register_template_loaders(register),
#     register_fragment_loaders(register), register_tools(register)
```

- `HookspecMarker("llm")` and `HookimplMarker("llm")` must use the **same project name** as `PluginManager("llm")`. That name is how pluggy matches implementations to specs.
- **Fact.** `hookimpl` is re-exported, so plugins write `@llm.hookimpl` (checked at runtime: `llm.hookimpl is llm.hookspecs.hookimpl` → `True`).

**Fact.** The plugin manager ([`llm/plugins.py` L15–16](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/plugins.py#L15-L16)):

```python
pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)
```

**Fact.** How core calls a hook: core builds a local `register` closure, then fires the hook once. Example, models ([`llm/__init__.py` L127–136](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/__init__.py#L127-L136)):

```python
def register(model, async_model=None, aliases=None):
    alias_list = list(aliases or [])
    if model.model_id in extra_model_aliases:
        alias_list.extend(extra_model_aliases[model.model_id])
    model_aliases.append(ModelWithAliases(model, async_model, alias_list))


load_plugins()
pm.hook.register_models(register=register, model_aliases=model_aliases)
```

**Inference — the key design point.** `llm` uses pluggy only as a **registration bus**. No hook returns a value that core consumes. The real contract is the *object* a plugin registers: a `llm.Model` subclass, an `llm.Tool`, a loader callable. Behavior lives on those objects, not in per-operation hooks. That keeps the hookspec list short and stable (six hooks in three years) while the object APIs evolve.

**Fact.** Name collisions are resolved by core inside `register`, not by pluggy. Loaders get a numeric suffix (`_get_loaders`, [`llm/__init__.py` L139–152](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/__init__.py#L139-L152)):

```python
    def register(prefix, loader):
        suffix = 0
        prefix_to_try = prefix
        while prefix_to_try in loaders:
            suffix += 1
            prefix_to_try = f"{prefix}_{suffix}"
        loaders[prefix_to_try] = loader
```

**Fact.** When core needs to know *which plugin* registered something, it bypasses `pm.hook.*` and calls each plugin's implementation itself. `get_tools()` does this to tag tools with their plugin name ([`llm/__init__.py` L226–235](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/__init__.py#L226-L235)):

```python
    for plugin in pm.get_plugins():
        current_plugin_name = pm.get_name(plugin)
        hook_caller = pm.hook.register_tools
        plugin_impls = [
            impl for impl in hook_caller.get_hookimpls() if impl.plugin is plugin
        ]
        for impl in plugin_impls:
            impl.function(register=register)
```

---

## 3. Q2 — Discovery, load order, and `LLM_LOAD_PLUGINS`

**Fact.** The entire loader ([`llm/plugins.py` L10–52](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/plugins.py#L10-L52)):

```python
DEFAULT_PLUGINS = (
    "llm.default_plugins.openai_models",
    "llm.default_plugins.default_tools",
)

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

LLM_LOAD_PLUGINS = os.environ.get("LLM_LOAD_PLUGINS", None)

_loaded = False


def load_plugins():
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not hasattr(sys, "_called_from_test") and LLM_LOAD_PLUGINS is None:
        # Only load plugins if not running tests
        pm.load_setuptools_entrypoints("llm")

    # Load any plugins specified in LLM_LOAD_PLUGINS")
    if LLM_LOAD_PLUGINS is not None:
        for package_name in [
            name for name in LLM_LOAD_PLUGINS.split(",") if name.strip()
        ]:
            try:
                distribution = metadata.distribution(package_name)  # Updated call
                llm_entry_points = [
                    ep for ep in distribution.entry_points if ep.group == "llm"
                ]
                for entry_point in llm_entry_points:
                    mod = entry_point.load()
                    pm.register(mod, name=entry_point.name)
                    # Ensure name can be found in plugin_to_distinfo later:
                    pm._plugin_distinfo.append((mod, distribution))  # type: ignore
            except metadata.PackageNotFoundError:
                sys.stderr.write(f"Plugin {package_name} could not be found\n")

    for plugin in DEFAULT_PLUGINS:
        mod = importlib.import_module(plugin)
        pm.register(mod, plugin)
```

How it works, step by step:

| Step | What happens | Notes |
|---|---|---|
| Discovery | `pm.load_setuptools_entrypoints("llm")` scans every installed distribution for entry points in group `llm`, imports each one, and registers the module. | Skipped when `LLM_LOAD_PLUGINS` is set or `sys._called_from_test` exists. |
| Allow-list | If `LLM_LOAD_PLUGINS` is set, each comma-separated **distribution name** (for example `llm-gpt4all`) is looked up with `importlib.metadata` and only its `llm` entry points load. | An unknown name prints `Plugin X could not be found` and continues. `''` loads no third-party plugin. |
| Built-ins | Each module in `DEFAULT_PLUGINS` is imported by path and registered under its module name. | Always runs, including under `LLM_LOAD_PLUGINS=''` and in tests. |
| Idempotence | The `_loaded` flag makes `load_plugins()` safe to call from every public getter (`get_models_with_aliases`, `get_tools`, and so on). | |

Details worth knowing:
- **Fact.** `LLM_LOAD_PLUGINS` is read **once, at import time** of `llm.plugins` (module-level `os.environ.get`). Changing the environment variable after import has no effect.
- **Fact.** The allow-list path appends to the **private** attribute `pm._plugin_distinfo` so that `llm plugins` can still show the package name and version. That is a dependency on pluggy internals.
- **Fact.** The CLI loads plugins at **import of `llm.cli`** ([`llm/cli.py` L4246–4248](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/cli.py#L4246-L4248)):

  ```python
  load_plugins()

  pm.hook.register_commands(cli=cli)
  ```

  So every plugin module is imported before any command runs, including `llm --help`.

**Load order versus call order (verified by running).**
- **Fact (pluggy behavior).** pluggy calls hook implementations in **last-registered-first (LIFO)** order, unless an implementation is marked `tryfirst`/`trylast`. Observed: registering an external plugin *after* the built-ins made `pm.hook.register_tools(...)` call it first: `['ext_tool', 'llm_version', 'llm_time']`.
- **Inference from that plus the loader.** In normal runs `llm` registers entry-point plugins first and built-ins **last**, so built-in implementations run first in hooks that core fires through `pm.hook.*` (models, embedding models, template and fragment loaders). For the loaders, "first registration keeps the bare prefix" (Section 2) then means a built-in would keep the bare prefix. Today no built-in registers a loader, and duplicate model IDs were not examined.
- **Fact.** `get_tools()` does **not** use pluggy's call order. It walks `pm.get_plugins()`, which returns a Python **`set`** (checked: `type(pm.get_plugins())` → `<class 'set'>`). **So the order in which plugins register tools, and therefore which duplicate tool name gets a suffix, is not defined.** That is a latent pitfall, not a guarantee.
- **Fact.** No hookspec or hookimpl in `llm/` uses `tryfirst`, `trylast`, `firstresult` or `wrapper` (grep over `llm/` found none). Pluggy's ordering rules: [pluggy docs, "Call time order"](https://pluggy.readthedocs.io/en/stable/#call-time-order).

---

## 4. Q3 — Built-in plugins: same hooks, different discovery path

**Fact.** Built-ins live in [`llm/default_plugins/`](https://github.com/simonw/llm/tree/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/default_plugins): an empty `__init__.py`, `openai_models.py`, and `default_tools.py`. They were moved there on 2023-07-01 (commit `1b3f14f`, "Move default plugins into llm/default_plugins").

**Fact.** The smallest built-in, in full ([`llm/default_plugins/default_tools.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/default_plugins/default_tools.py)):

```python
import llm
from llm.tools import llm_time, llm_version


@llm.hookimpl
def register_tools(register):
    register(llm_version)
    register(llm_time)
```

**Fact.** The large built-in uses the identical decorator a third-party plugin uses ([`openai_models.py` L144–145](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/default_plugins/openai_models.py#L144-L145) and [L474–475](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/default_plugins/openai_models.py#L474-L475)):

```python
@hookimpl
def register_models(register): ...


@hookimpl
def register_embedding_models(register): ...
```

**The exact mechanism, in three parts.**

| Aspect | Built-in plugin | Third-party plugin |
|---|---|---|
| Code shape | A module with `@llm.hookimpl` functions | Identical |
| How it is found | Listed by module path in `DEFAULT_PLUGINS` in `llm/plugins.py` | Entry point in group `llm` |
| How it is registered | `importlib.import_module(path)` then `pm.register(mod, path)` | `pm.load_setuptools_entrypoints("llm")` |
| Disabled by `LLM_LOAD_PLUGINS=''` | **No** | Yes |
| Loaded in tests | **Yes** | No (`sys._called_from_test`) |
| Shown by `llm plugins` | Only with `--all` (filtered by name prefix `llm.default_plugins.`) | Yes, with package name and version |

**Fact.** The listing filter ([`llm/__init__.py` L96–113](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/__init__.py#L96-L113)):

```python
def get_plugins(all=False):
    plugins = []
    plugin_to_distinfo = dict(pm.list_plugin_distinfo())
    for plugin in pm.get_plugins():
        if not all and plugin.__name__.startswith("llm.default_plugins."):
            continue
        plugin_info = {
            "name": plugin.__name__,
            "hooks": [h.name for h in pm.get_hookcallers(plugin)],
        }
        distinfo = plugin_to_distinfo.get(plugin)
        if distinfo:
            plugin_info["version"] = distinfo.version
            plugin_info["name"] = (
                getattr(distinfo, "name", None) or distinfo.project_name
            )
        plugins.append(plugin_info)
    return plugins
```

**Trade-off T6 inherits (Inference).** Built-ins prove the *hook interface* (same decorator, same signatures, same objects). They do **not** prove the *discovery path*: entry-point packaging, `LLM_LOAD_PLUGINS`, and listing metadata are exercised only by third-party plugins. Open issues show the cost of this choice: built-ins cannot be turned off (#671 "Add ability to unregister / not load default OpenAI plugin", #922 "Make it possible to disable the openai plugin", both open), and releasing a built-in fix needs a full `llm` release (#335 "Extract OpenAI support out of core and into a plugin", open).

**A known alternative (Inference, not used by `llm`).** A package can declare entry points that point at its *own* modules, for example `[project.entry-points.llm] openai = "llm.default_plugins.openai_models"`. Then built-ins travel the exact third-party discovery path and can be disabled the same way. The costs: the `''` escape hatch then removes built-ins too, and a broken packaging install loses them. For T6 the exact copy was chosen (Q-E in [design 0006](../design/0006-lost-sessions-plugin-design.md)).

---

## 5. Q4 — Plugin CLI surface: `llm plugins`, `llm install`, commands, models, options

**`llm plugins`** — **Fact** ([`llm/cli.py` L3284–3294](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/cli.py#L3284-L3294)):

```python
@cli.command(name="plugins")
@click.option("--all", help="Include built-in default plugins", is_flag=True)
@click.option(
    "hooks", "--hook", help="Filter for plugins that implement this hook", multiple=True
)
def plugins_list(all, hooks):
    "List installed plugins"
    plugins = get_plugins(all)
    hooks = set(hooks)
    if hooks:
        plugins = [plugin for plugin in plugins if hooks.intersection(plugin["hooks"])]
    click.echo(json.dumps(plugins, indent=2))
```

- Output is a JSON list of `{"name", "hooks", "version"}`. `--all` came from #259 ("as seen in Datasette"); `--hook` came from #1047.

**`llm install` / `llm uninstall`** — **Fact** ([`llm/cli.py` L3331–3355](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/cli.py#L3331-L3355)): both rewrite `sys.argv` and run pip in-process, so the package lands in the interpreter `llm` runs from:

```python
    args = ["pip", "install"]
    ...  # --upgrade, --editable PATH, --force-reinstall, --no-cache-dir, --pre
    args += list(packages)
    sys.argv = args
    run_module("pip", run_name="__main__")
```

- **Fact.** `pip` is listed in `[project] dependencies` (`pyproject.toml` line 40). **Inference:** the reason is that `run_module("pip")` needs pip importable inside `pipx`/`uv tool` environments, which do not always include it.
- **Fact.** `llm install -e path/to/plugin` is the documented development loop ([tutorial](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html)).

**Adding commands** — **Fact.** `register_commands(cli)` receives the root click group; the plugin decorates new commands onto it. From [`tests/test_plugins.py` L17–50](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/tests/test_plugins.py#L17-L50):

```python
    class HelloWorldPlugin:
        __name__ = "HelloWorldPlugin"

        @hookimpl
        def register_commands(self, cli):
            @cli.command(name="hello-world")
            def hello_world():
                "Print hello world"
                click.echo("Hello world!")
```

**Adding models** — **Fact.** `register_models(register)` calls `register(Model(), async_model=None, aliases=(...))` (Section 2). Docs: [plugin hooks](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html).

**Adding options** — **Fact.** Options are not a hook. A model declares a nested Pydantic class, and core discovers and validates it; `llm models --options` documents it. From the tutorial (`docs/plugins/tutorial-model-plugin.md`, "Adding options"), abridged (the `delay` field and its validator are omitted):

```python
class Options(llm.Options):
    length: int | None = Field(description="Number of words to generate", default=None)

    @field_validator("length")
    def validate_length(cls, length):
        if length is None:
            return None
        if length < 2:
            raise ValueError("length must be >= 2")
        return length
```

**Inference.** This is the same "behavior lives on the registered object" principle: per-object options are a class attribute, not a hookspec.

---

## 6. Q5 — Testing: core isolation and plugin tests

**Core suite isolation — Fact.**
1. `tests/conftest.py` sets the sentinel before collection ([L14–18](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/tests/conftest.py#L14-L18)): `sys._called_from_test = True`. This stops entry-point loading, so a developer's installed plugins cannot leak into tests. It was added for #626 ("Plugins incorrectly loaded during test runs": an installed `llm-ollama` made HTTP calls during tests; fixed 2024-11-13, commit `330e171`).
2. The same sentinel is injected for `cog` doc generation in CI and the `Justfile`: `-p "import sys, os; sys._called_from_test=True; os.environ['LLM_USER_PATH'] = '/tmp'"` (`.github/workflows/test.yml` L33, `Justfile` L15, L28).
3. `LLM_USER_PATH` is pointed at a temporary directory with `monkeypatch.setenv` (`conftest.py` L74), so tests never touch the real config.

**Test-local plugins — Fact.** Fixtures define a plugin as a class with a `__name__`, register it, and always unregister it ([`conftest.py` L243–279](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/tests/conftest.py#L243-L279)):

```python
@pytest.fixture(autouse=True)
def register_echo_model():
    class EchoModelPlugin:
        __name__ = "EchoModelPlugin"

        @llm.hookimpl
        def register_models(self, register):
            register(llm_echo.Echo(), llm_echo.EchoAsync())

    pm.register(EchoModelPlugin(), name="undo-EchoModelPlugin")
    try:
        yield
    finally:
        pm.unregister(name="undo-EchoModelPlugin")
```

- **Fact.** `register_commands` is the exception: commands attach to the click group at import, so `test_register_commands` calls `importlib.reload(cli)` after registering and again after unregistering (`tests/test_plugins.py` L17–50).

**Discovery is tested end to end, outside pytest — Fact.** `tests/test-llm-load-plugins.sh` installs real plugins (`llm-cluster`, `llm-mistral`) and asserts the `LLM_LOAD_PLUGINS` allow-list and empty-list behavior via `llm plugins | jq`. CI runs it as a separate step (`.github/workflows/test.yml` L50–54).

**How third-party plugins test themselves — Fact.**
- The cookiecutter's test only proves the module imports: `def test_plugin_is_installed(): import llm_<name>`.
- Real plugins test through `llm`'s public API with the plugin installed in the test environment (entry point active). From [`simonw/llm-echo` `tests/test_echo.py`](https://github.com/simonw/llm-echo/blob/main/tests/test_echo.py): `model = llm.get_model("echo"); response = model.prompt("prompt", system="system")`.
- **Inference.** Plugins do *not* set `sys._called_from_test`, so other installed plugins can load during a plugin's test run. A clean per-plugin virtual environment (the template's CI) is what isolates them.

---

## 7. Q6 — Packaging: `llm-<name>` and the cookiecutter template

**Fact.** Minimum `pyproject.toml` from the tutorial (`docs/plugins/tutorial-model-plugin.md`):

```toml
[project]
name = "llm-markov"
version = "0.1"

[project.entry-points.llm]
markov = "llm_markov"
```

- Distribution name: `llm-<name>` (hyphen). Module: `llm_<name>` (underscore). Entry-point group: `llm`. Entry-point *name* (`markov`) is the pluggy registration name.

**Fact.** Template: [`simonw/llm-plugin`](https://github.com/simonw/llm-plugin), "A cookiecutter template for building plugins for LLM", run as `cookiecutter gh:simonw/llm-plugin`. `cookiecutter.json`:

```json
{
  "plugin_name": "",
  "description": "",
  "hyphenated": "{{ '-'.join(cookiecutter['plugin_name'].lower().split()).replace('_', '-') }}",
  "underscored": "{{ cookiecutter.hyphenated.replace('-', '_') }}",
  "github_username": "",
  "author_name": ""
}
```

Generated tree: `llm-<hyphenated>/` with `llm_<underscored>.py`, `pyproject.toml` (depends on `llm`, entry point `<underscored> = "llm_<underscored>"`, `dev = ["pytest"]` dependency group), `tests/test_<underscored>.py`, `.github/workflows/test.yml` and `publish.yml`. The template repo tests itself (`tests/test_cookiecutter_template.py`).

**Fact.** Discoverability is a curated docs page, [plugin directory](https://llm.datasette.io/en/stable/plugins/directory.html). #577 "plugin discoverability is bad" is open.

---

## 8. Q7 — Pitfalls and trade-offs from issues

| # | Pitfall (Fact) | Resolution as read | Lesson for T6 (Proposal) |
|---|---|---|---|
| #256 | A broken plugin in development "prevents `llm uninstall` from working", because every plugin imports at CLI start. | Closed 2023-09 by adding `LLM_LOAD_PLUGINS` (copied from Datasette #2164). | Ship the env-var escape hatch from day one. |
| #732, #949 | Installed plugins slowed `llm --help` from 1.3 s to 10.7 s. Profiling found heavy top-level imports (`torch` via `llm-sentence-transformers`, `llm-mlx`). | Closed. The plugins were fixed to import lazily, and the docs gained "[Tip: lazily load expensive dependencies](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html#tip-lazily-load-expensive-dependencies)". | Require lazy imports in plugin docs; keep plugin module import cheap. |
| #922, #671 | Built-in OpenAI plugin adds "hundreds of milliseconds" and cannot be disabled; a replacement plugin cannot take over its model names. | Open. | Considered; T6 keeps built-ins always on so the escape hatch still leaves a working tool (Q-E). |
| #335 | Built-in OpenAI code can only ship with a core release. | Open. | Keep built-ins small, or accept the coupling knowingly. |
| #575, #733, #870, #1113 | `uv tool upgrade llm` rebuilds the tool environment and silently drops plugins added with `llm install`, because `uv` does not know about them. | #575, #733, #1113 open (#870 closed). Workarounds: `uv tool install --with llm-anthropic --with llm-gemini llm` (#575 thread), or upgrade with `llm install -U llm` (#1113). Simon proposed recording installs in `user_dir()/plugins.txt` plus a sync command; third-party [`llm-uv-tool`](https://github.com/joshuadavidthomas/llm-uv-tool) exists. | Decided for T6: `install`/`uninstall` drive `uv tool install` and never run `pip` (Q-C2 in [design 0006](../design/0006-lost-sessions-plugin-design.md)). |
| #315 | Homebrew's Python 3.12 had no PyTorch, so PyTorch-based plugins could not install. | Closed (resolution comments not read). | Packaging channel constrains plugins; prefer `uv tool`. |
| #626 | Installed plugins leaked into the test suite. | Closed by `sys._called_from_test`. | Copy the idea as an explicit test-mode switch (design TS-1). |
| #1032 | `register(fn, name=...)` ignored `name`. | Closed (bug fix). | Test every `register` keyword. |
| #114 | No supported way to register plugins at runtime from the Python API. | Open. | Expose a public `register_plugin(obj)` helper instead of telling users to touch `pm`. |
| — | `pm._plugin_distinfo` is a private pluggy attribute (Section 3). | Still in code. | Avoid private pluggy API. |

---

## 9. Mapping for T6 `lost-sessions` — moved

The `lost-sessions` mapping that used to be here is now its own document, with every decision from 2026-11-12 folded in: **[design 0006](../design/0006-lost-sessions-plugin-design.md)**. It holds the decision log (Q-A to Q-I, Q-C2), hookspecs, Pydantic models, plugin contracts, CLI, the "identical behavior" contract, the copied-versus-deviation table, the test plan, and the T6 work items.

---

## 10. What transfers to a Rust CLI (`brot`, T3) — options only, no decision

**Context (Fact).** T3 defers "extensibility for object types via callbacks/plugins" to this research. Rust has no runtime equivalent of Python entry points: there is no standard way for an installed package to announce itself to an already-compiled binary.

**What transfers regardless of mechanism (Inference).**
- The **registration-bus shape**: one `register_object_types(register)`-style entry, with behavior on a trait (`trait ObjectType { fn list(..); fn check(..); fn delete(..) }`) rather than many hooks.
- **Built-ins implemented through the same trait** as external types.
- An **allow-list environment variable**, a `brot plugins` listing, and a contract test suite run against every implementation.

| Option | How it works | Precedent | Trade-offs |
|---|---|---|---|
| **External binaries on PATH** | `brot` finds `brot-<type>` executables on `PATH` and speaks a JSON protocol over stdin/stdout. | `git` and `cargo` subcommands (`git-foo`, `cargo-foo`) — uncited here, well known. | Any language; crash isolation; independent release. Costs: process start per call, a versioned protocol to maintain, discovery via `PATH` scanning. Closest to `llm`'s "install a package to extend" experience. |
| **Compiled-in features** | Each type is a crate implementing the trait; Cargo features select which are built in; registration via a static list or `inventory`/`linkme`-style distributed slices. | Uncited. | Fast and type-checked. Third parties must rebuild `brot`; no runtime install. Matches `llm`'s *built-ins* only, not its third-party story. |
| **WASM components** | Types compile to WebAssembly components against a WIT interface; `brot` embeds a runtime such as `wasmtime`. | Uncited. | Sandboxed (useful for a *safe-delete* tool), language-neutral, installable at runtime. Costs: a runtime dependency, larger binary, file-system access must be granted explicitly through WASI. |

T3 owns the choice.

---

## 11. Source index

- `simonw/llm` at `8b475ff…`: [`llm/plugins.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/plugins.py), [`llm/hookspecs.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/hookspecs.py), [`llm/__init__.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/__init__.py), [`llm/default_plugins/`](https://github.com/simonw/llm/tree/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/default_plugins), [`llm/cli.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/llm/cli.py), [`tests/conftest.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/tests/conftest.py), [`tests/test_plugins.py`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/tests/test_plugins.py), [`tests/test-llm-load-plugins.sh`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/tests/test-llm-load-plugins.sh), [`.github/workflows/test.yml`](https://github.com/simonw/llm/blob/8b475ffdfc2d33aa86c9518baff3ac94bcea409e/.github/workflows/test.yml).
- Docs (stable): [plugins index](https://llm.datasette.io/en/stable/plugins/), [installing plugins / `LLM_LOAD_PLUGINS`](https://llm.datasette.io/en/stable/plugins/installing-plugins.html), [plugin hooks](https://llm.datasette.io/en/stable/plugins/plugin-hooks.html), [model plugin tutorial](https://llm.datasette.io/en/stable/plugins/tutorial-model-plugin.html), [advanced model plugins](https://llm.datasette.io/en/stable/plugins/advanced-model-plugins.html), [directory](https://llm.datasette.io/en/stable/plugins/directory.html).
- Template: [`simonw/llm-plugin`](https://github.com/simonw/llm-plugin). Example plugin tests: [`simonw/llm-echo`](https://github.com/simonw/llm-echo).
- Issues: [#49](https://github.com/simonw/llm/issues/49), [#53](https://github.com/simonw/llm/issues/53), [#114](https://github.com/simonw/llm/issues/114), [#256](https://github.com/simonw/llm/issues/256), [#259](https://github.com/simonw/llm/issues/259), [#315](https://github.com/simonw/llm/issues/315), [#335](https://github.com/simonw/llm/issues/335), [#575](https://github.com/simonw/llm/issues/575), [#577](https://github.com/simonw/llm/issues/577), [#626](https://github.com/simonw/llm/issues/626), [#671](https://github.com/simonw/llm/issues/671), [#732](https://github.com/simonw/llm/issues/732), [#922](https://github.com/simonw/llm/issues/922), [#949](https://github.com/simonw/llm/issues/949), [#733](https://github.com/simonw/llm/issues/733), [#870](https://github.com/simonw/llm/issues/870), [#1032](https://github.com/simonw/llm/issues/1032), [#1113](https://github.com/simonw/llm/issues/1113), [#1047](https://github.com/simonw/llm/issues/1047).
- [pluggy documentation](https://pluggy.readthedocs.io/en/stable/) (call order, `tryfirst`/`trylast`).
- PyPA [entry points specification](https://packaging.python.org/en/latest/specifications/entry-points/) (group-name rule).
- `lost-sessions` source: `smorin/smorin-bootstrap` `utils/bin/lost-sessions` (read 2026-11-12).
