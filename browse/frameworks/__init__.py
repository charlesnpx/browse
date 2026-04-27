"""Framework plugin registry.

The daemon imports `framework_config()` to aggregate selector hints from all
registered plugins into a single dict for JS. Plugins are registered here at
import time; the daemon stays oblivious to which frameworks are loaded.
"""

from __future__ import annotations

from browse.frameworks.interface import (
    FrameworkHints,
    FrameworkPlugin,
    make_plugin,
)
from browse.frameworks.mui import MUI_V4_PLUGIN


_PLUGINS: list[FrameworkPlugin] = [MUI_V4_PLUGIN]


def active_plugins() -> list[FrameworkPlugin]:
    return list(_PLUGINS)


def register_plugin(plugin: FrameworkPlugin) -> None:
    _PLUGINS.append(plugin)


def reset_plugins(plugins: list[FrameworkPlugin] | None = None) -> None:
    """Replace the active plugin list. Primarily for tests."""
    global _PLUGINS
    _PLUGINS = list(plugins) if plugins is not None else [MUI_V4_PLUGIN]


def framework_config() -> dict[str, list[str]]:
    """Aggregate all registered plugins' hints into a single dict for JS.

    The JS in `daemon.py` reads only these keys; it never sees framework names.
    """
    overlays: list[str] = []
    day_roots: list[str] = []
    year_views: list[str] = []
    month_views: list[str] = []
    for plugin in _PLUGINS:
        h = plugin.hints()
        overlays.extend(h.overlay_selectors)
        day_roots.extend(h.day_picker_root_selectors)
        year_views.extend(h.year_view_selectors)
        month_views.extend(h.month_view_selectors)
    return {
        "overlaySelectors": overlays,
        "dayPickerRootSelectors": day_roots,
        "yearViewSelectors": year_views,
        "monthViewSelectors": month_views,
    }


__all__ = [
    "FrameworkHints",
    "FrameworkPlugin",
    "MUI_V4_PLUGIN",
    "active_plugins",
    "framework_config",
    "make_plugin",
    "register_plugin",
    "reset_plugins",
]
