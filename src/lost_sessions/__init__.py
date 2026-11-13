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

"""lost-sessions: recover agent sessions that a reboot dropped."""

from importlib import metadata

__version__ = metadata.version("lost_sessions")

# The public API for plugin authors (design 0006, Section 3).
from lost_sessions.agents import AgentTool, ScanContext
from lost_sessions.hookspecs import hookimpl
from lost_sessions.managers import (
    Destination,
    Destinations,
    Plan,
    SessionManager,
    Step,
)
from lost_sessions.models import ScanResult, Session, SourceStatus

__all__ = [
    "AgentTool",
    "Destination",
    "Destinations",
    "Plan",
    "ScanContext",
    "ScanResult",
    "Session",
    "SessionManager",
    "SourceStatus",
    "Step",
    "__version__",
    "hookimpl",
]
