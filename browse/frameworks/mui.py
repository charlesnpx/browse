"""MUI v4 framework plugin.

Contributes selectors for the portal-rendered overlays that MUI v4 uses
(Dialog, Popover, Autocomplete, Pickers, Menu) and for the year/month
views inside MUI date pickers, which lack distinguishing ARIA roles.
"""

from __future__ import annotations

from browse.frameworks.interface import FrameworkHints, FrameworkPlugin, make_plugin


MUI_V4_PLUGIN: FrameworkPlugin = make_plugin(
    FrameworkHints(
        name="mui-v4",
        overlay_selectors=(
            ".MuiDialog-root",
            ".MuiPopover-root",
            ".MuiAutocomplete-popper",
            ".MuiPickersPopper-root",
            ".MuiMenu-paper",
        ),
        day_picker_root_selectors=(
            ".MuiPickersPopper-root",
            ".MuiPopover-root",
        ),
        year_view_selectors=(
            ".MuiPickersYearSelection-container",
            ".MuiYearPicker-root",
            ".MuiPickersYear-root",
        ),
        month_view_selectors=(
            ".MuiPickersMonth-root",
            ".MuiMonthPicker-root",
        ),
    )
)
