"""The SessionManager plugin contract (design 0006, Section 6.2).

A session manager is a terminal app that can restore sessions by itself
(Herdr) or open them on request (Rex). This module holds the part core uses
to decide what is lost; opening and destinations join it with the managers'
`open` support.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC


class SessionManager(ABC):
    """Restores or opens agent sessions (Herdr, Rex, ...)."""

    name: str  # "herdr": the CLI flag (`open --herdr`) and the menu action
    display_name: str  # "Herdr": shown in labels and messages
    # Whether restored_ids() can be non-empty: the manager reopens sessions by
    # itself after a reboot, so `list` reports sessions "not in" it.
    restores: bool = False

    def restored_ids(self, boot: dt.datetime) -> dict[str, str]:
        """Session IDs this manager will restore by itself, mapped to a label
        such as "work / tab". Managers that never restore return {}."""
        return {}
