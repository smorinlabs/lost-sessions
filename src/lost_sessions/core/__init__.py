# Copyright (c) 2025, Steve Morin
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""Reusable library layer (the "core").

This package holds pure business logic and data models with no CLI or
presentation concerns. Both the CLI (``lost_sessions.cli``) and the
future web service (``lost_sessions.web``) import from here; ``core``
never imports from them. Keeping side-effect-free logic in one place is what
makes a single result object renderable as human text, JSON, or Markdown.
"""

from lost_sessions.core.config import (
    Config,
    get_config_dir,
    get_default_config_path,
    load_config,
    set_config_value,
)
from lost_sessions.core.diagnostics import run_diagnostics
from lost_sessions.core.errors import (
    APIError,
    AuthError,
    ConfigError,
    ExitCode,
    PyError,
)
from lost_sessions.core.models import (
    CLIResult,
    ConfigPath,
    ConfigValue,
    DoctorCheck,
    DoctorReport,
    Project,
    ProjectList,
)
from lost_sessions.core.settings import (
    LoggingSettings,
    OutputSettings,
    Settings,
    parse_key,
    writable_keys,
)

__all__ = [
    "APIError",
    "AuthError",
    "CLIResult",
    "Config",
    "ConfigError",
    "ConfigPath",
    "ConfigValue",
    "DoctorCheck",
    "DoctorReport",
    "ExitCode",
    "LoggingSettings",
    "OutputSettings",
    "Project",
    "ProjectList",
    "PyError",
    "Settings",
    "get_config_dir",
    "get_default_config_path",
    "load_config",
    "parse_key",
    "run_diagnostics",
    "set_config_value",
    "writable_keys",
]
