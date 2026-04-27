"""Framework plugin interface.

The daemon JS (inspect, signature, top-scope, picker-view) is intentionally
framework-neutral — it knows about W3C/ARIA roles only. Real apps use UI
libraries that don't always carry the right roles (portal-rendered listboxes
without `aria-controls`, picker views without distinct ARIA shapes, etc.).
Plugins contribute *selector hints* that the JS treats as additive matchers
on top of the role-based defaults.

A plugin contributes data, not behavior. The JS in `daemon.py` reads these
hints from a config object passed into every `evaluate(...)` call. Adding a
new framework = registering a plugin with extra selectors. The daemon never
imports a framework name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FrameworkHints:
    name: str = "generic"
    overlay_selectors: tuple[str, ...] = ()
    """Extra CSS for portal/overlay roots beyond W3C-role scope selectors
    (`[role="dialog"]`, `[role="listbox"]`, `[role="menu"]`, `[role="grid"]`,
    `[role="tree"]`)."""

    day_picker_root_selectors: tuple[str, ...] = ()
    """Selectors that match an open day-picker popover root (the picker may
    or may not also have `[role="dialog"]`)."""

    year_view_selectors: tuple[str, ...] = ()
    """Selectors that, when found inside a picker root, mean the picker is
    showing a year-only / decade view (no day grid)."""

    month_view_selectors: tuple[str, ...] = ()
    """Same idea for month-only views."""


class FrameworkPlugin(Protocol):
    @property
    def name(self) -> str: ...
    def hints(self) -> FrameworkHints: ...


@dataclass(frozen=True)
class _StaticPlugin:
    _hints: FrameworkHints

    @property
    def name(self) -> str:
        return self._hints.name

    def hints(self) -> FrameworkHints:
        return self._hints


def make_plugin(hints: FrameworkHints) -> FrameworkPlugin:
    return _StaticPlugin(hints)
