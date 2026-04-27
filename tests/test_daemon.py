from __future__ import annotations

import unittest
from unittest import mock

from browse.daemon import (
    BrowseDaemon,
    LocatorRecipe,
    ManagedPage,
    SIGNATURE_JS,
    INSPECT_JS,
    OPTIONS_IN_SCOPE_JS,
    PICKER_VIEW_JS,
    TARGET_KIND_JS,
    TOP_SCOPE_JS,
)


class FakeLocator:
    def __init__(self, *, role: str = "button", name: str = "Save"):
        self.role = role
        self.name = name
        self.clicked = False

    @property
    def first(self):
        return self

    def nth(self, _index):
        return self

    def count(self):
        return 1

    def wait_for(self, **_kwargs):
        return None

    def scroll_into_view_if_needed(self):
        return None

    def is_enabled(self):
        return True

    def bounding_box(self):
        return {"x": 0, "y": 0, "width": 100, "height": 24}

    def evaluate(self, script):
        if "elementFromPoint" in script:
            return False
        return {
            "visible": True,
            "enabled": True,
            "expanded": "true" if self.clicked else "false",
            "selected": None,
            "checked": None,
            "value": None,
            "text": self.name,
        }

    def click(self):
        self.clicked = True


class FakePage:
    def __init__(self):
        self.url = "http://localhost:3000/app/amot/87"
        self._title = "AMOT 87"
        self.events = {}
        self.focused = {"role": "textbox", "name": "Status Date"}
        self.signature_label = "dialog: Edit AMOT"
        self.last_evaluate_script = None
        self.inspect_snapshot = {
            "activeScopeId": "scope-1",
            "activeScopeLabel": "dialog: Edit AMOT",
            "scopes": [
                {
                    "id": "scope-1",
                    "label": "dialog: Edit AMOT",
                    "selector": "body > div:nth-of-type(2)",
                    "role": "dialog",
                    "rect": {"top": 10, "left": 10, "width": 600, "height": 400},
                    "zIndex": 1300,
                }
            ],
            "items": [
                {
                    "selector": "#status-date",
                    "scopeId": "scope-1",
                    "scopeLabel": "dialog: Edit AMOT",
                    "role": "textbox",
                    "name": "Status Date",
                    "text": "",
                    "tag": "input",
                    "type": "text",
                    "visible": True,
                    "enabled": True,
                    "expanded": None,
                    "selected": None,
                    "checked": None,
                    "value": "",
                    "focused": True,
                    "bounding": {"top": 100, "left": 120, "width": 240, "height": 36},
                },
                {
                    "selector": "#save-button",
                    "scopeId": "scope-1",
                    "scopeLabel": "dialog: Edit AMOT",
                    "role": "button",
                    "name": "Save",
                    "text": "Save",
                    "tag": "button",
                    "type": None,
                    "visible": True,
                    "enabled": True,
                    "expanded": "false",
                    "selected": None,
                    "checked": None,
                    "value": None,
                    "focused": False,
                    "bounding": {"top": 320, "left": 480, "width": 80, "height": 32},
                },
            ],
            "focusedSelector": "#status-date",
            "title": self._title,
        }
        self.locator_instance = FakeLocator()

    def on(self, name, handler):
        self.events[name] = handler

    def evaluate(self, script, *args):
        self.last_evaluate_script = script
        self.last_evaluate_args = args
        if script is SIGNATURE_JS:
            return {
                "url": self.url,
                "activeScopeLabel": self.signature_label,
                "scopeCount": 1 if self.signature_label != "page" else 0,
                "focusedSelector": self.focused.get("selector") if isinstance(self.focused, dict) else None,
            }
        if script is TOP_SCOPE_JS:
            return "body > div:nth-of-type(2)"
        if script is INSPECT_JS:
            return self.inspect_snapshot
        if script is PICKER_VIEW_JS:
            return getattr(self, "picker_view_response", {"ok": True, "view": "day", "cells": 35})
        if script is OPTIONS_IN_SCOPE_JS:
            return getattr(self, "options_in_scope_response", [])
        if "activeElement" in script:
            return self.focused
        return self.inspect_snapshot

    def wait_for_timeout(self, _ms):
        return None

    def title(self):
        return self._title

    def locator(self, _selector):
        return self.locator_instance

    def get_by_role(self, role, name=None, exact=None):
        del exact
        if role == "button" and name == "Save":
            return self.locator_instance
        return FakeLocator(role=role, name=name or role)


class FakeContext:
    def __init__(self, page):
        self.pages = [page]


class FakeBrowser:
    def __init__(self, page):
        self.contexts = [FakeContext(page)]


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.page = FakePage()
        self.daemon = BrowseDaemon(port=9222)
        self.daemon.browser = FakeBrowser(self.page)
        self.daemon.refresh_pages(auto_select=True)

    def test_inspect_groups_items_and_registers_target_ids(self):
        response = self.daemon.handle("inspect", {})

        self.assertTrue(response["ok"])
        self.assertEqual(response["command"], "inspect")
        self.assertEqual(response["active_scope"], "dialog: Edit AMOT")
        self.assertEqual(len(response["groups"]), 1)
        item = response["groups"][0]["items"][0]
        self.assertIn("target_id", item)
        self.assertTrue(self.daemon.target_registry)

    def test_assert_version_detects_external_state_change(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)
        managed.state_version = 2
        self.page.signature_label = "popover: date picker"

        with self.assertRaisesRegex(Exception, "Re-run `browse inspect`"):
            self.daemon._assert_version(managed, 2)

    def test_click_returns_state_delta_and_bumps_version(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)
        self.daemon.target_registry[(managed.page_id, "target-1")] = LocatorRecipe(
            target_id="target-1",
            page_id=managed.page_id,
            scope_id="scope-1",
            scope_label="dialog: Edit AMOT",
            scope_selector=None,
            selector="#save-button",
            role="button",
            name="Save",
            text="Save",
            index=1,
        )

        response = self.daemon.handle("click", {"target_id": "target-1", "if_version": 0})

        self.assertTrue(response["ok"])
        self.assertEqual(response["before"]["expanded"], "false")
        self.assertEqual(response["after"]["expanded"], "true")
        self.assertEqual(response["state_version"], 1)

    def test_signature_uses_lightweight_script_not_full_inspect(self):
        managed = next(iter(self.daemon.pages.values()))
        signature = self.daemon._signature_for_page(managed)
        self.assertIn("activeScopeLabel", signature)
        self.assertIn("scopeCount", signature)
        self.assertIs(self.page.last_evaluate_script, SIGNATURE_JS)

    def test_bump_after_action_does_not_re_inspect(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = "stale"
        managed.state_version = 4

        self.page.last_evaluate_script = "marker"
        self.daemon._bump_after_action(managed)

        self.assertEqual(managed.state_version, 5)
        self.assertIsNone(managed.last_signature)
        self.assertEqual(self.page.last_evaluate_script, "marker")

    def test_choose_button_style_clicks_option_in_active_overlay(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)
        button = FakeLocator(role="button", name="Not Completed")
        button.kind_payload = {"tag": "div", "isInput": False, "hasInputChild": False}
        self.daemon.target_registry[(managed.page_id, "select-trigger")] = LocatorRecipe(
            target_id="select-trigger",
            page_id=managed.page_id,
            scope_id="page",
            scope_label="page",
            scope_selector=None,
            selector="#status-select",
            role="button",
            name="Not Completed",
            text="Not Completed",
            index=1,
        )

        scope_base = mock.Mock()
        completed_option = mock.Mock()
        completed_option.count.return_value = 1
        completed_option.first = completed_option
        scope_base.first = scope_base
        scope_base.get_by_role.return_value = completed_option

        with mock.patch.object(self.daemon, "_resolve_recipe", return_value=button):
            with mock.patch.object(self.daemon, "_classify_target", return_value={"isInput": False, "hasInputChild": False}):
                with mock.patch.object(self.daemon, "_find_option_in_active_scope", return_value=completed_option) as find_option:
                    response = self.daemon.handle("choose", {"target_id": "select-trigger", "text": "Completed"})

        self.assertTrue(response["ok"])
        self.assertTrue(button.clicked)
        find_option.assert_called_once_with(managed, "Completed")
        completed_option.click.assert_called_once_with()
        steps = response["trace"]["steps_executed"]
        self.assertEqual([s["step"] for s in steps], ["open", "select-option"])

    def test_choose_returns_outer_ok_false_when_no_option_matches(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)
        button = FakeLocator(role="button", name="Not Completed")
        self.daemon.target_registry[(managed.page_id, "select-trigger")] = LocatorRecipe(
            target_id="select-trigger",
            page_id=managed.page_id,
            scope_id="page",
            scope_label="page",
            scope_selector=None,
            selector="#status-select",
            role="button",
            name="Not Completed",
            text="Not Completed",
            index=1,
        )

        with mock.patch.object(self.daemon, "_resolve_recipe", return_value=button):
            with mock.patch.object(self.daemon, "_classify_target", return_value={"isInput": False, "hasInputChild": False}):
                with mock.patch.object(self.daemon, "_find_option_in_active_scope", return_value=None):
                    response = self.daemon.handle("choose", {"target_id": "select-trigger", "text": "Completed"})

        self.assertFalse(response["ok"])
        self.assertFalse(response["trace"]["ok"])
        self.assertEqual(response["trace"]["failed_at"], "select-option")
        steps = response["trace"]["steps_executed"]
        select_steps = [s for s in steps if s["step"] == "select-option"]
        self.assertTrue(select_steps)
        self.assertFalse(select_steps[-1]["ok"])
        self.assertIn("Completed", response["message"])

    def test_choose_error_lists_available_options_from_active_scope(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)
        button = FakeLocator(role="button", name="-- None --")
        self.daemon.target_registry[(managed.page_id, "select-trigger")] = LocatorRecipe(
            target_id="select-trigger",
            page_id=managed.page_id,
            scope_id="page",
            scope_label="page",
            scope_selector=None,
            selector="#status-select",
            role="button",
            name="-- None --",
            text="-- None --",
            index=1,
        )
        self.page.options_in_scope_response = [
            {"text": "-- None --", "name": "", "disabled": False},
            {"text": "Draft", "name": "", "disabled": True},
            {"text": "Section Manager Review", "name": "", "disabled": False},
            {"text": "Ready for EPIC", "name": "", "disabled": False},
        ]

        with mock.patch.object(self.daemon, "_resolve_recipe", return_value=button):
            with mock.patch.object(self.daemon, "_classify_target", return_value={"isInput": False, "hasInputChild": False}):
                with mock.patch.object(self.daemon, "_find_option_in_active_scope", return_value=None):
                    response = self.daemon.handle("choose", {"target_id": "select-trigger", "text": "Draft Section Manager Review"})

        self.assertFalse(response["ok"])
        self.assertIn("Section Manager Review", response["message"])
        self.assertIn("Ready for EPIC", response["message"])
        steps = response["trace"]["steps_executed"]
        no_match = [s for s in steps if s["step"] == "select-option" and s["ok"] is False]
        self.assertTrue(no_match)
        self.assertIn("Section Manager Review", no_match[-1]["available"])
        self.assertIn("Draft", no_match[-1]["disabled_options"])

    def test_pick_date_fails_loud_when_picker_is_year_only(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)
        date_button = FakeLocator(role="button", name="change date")
        self.daemon.target_registry[(managed.page_id, "year-cell")] = LocatorRecipe(
            target_id="year-cell",
            page_id=managed.page_id,
            scope_id="page",
            scope_label="page",
            scope_selector=None,
            selector="#year-cell",
            role="button",
            name="change date",
            text="change date",
            index=1,
        )
        self.page.picker_view_response = {"ok": False, "view": "year", "reason": "year-only-picker"}

        with mock.patch.object(self.daemon, "_resolve_recipe", return_value=date_button):
            response = self.daemon.handle("pick-date", {"target_id": "year-cell", "iso_date": "2026-04-30"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["trace"]["failed_at"], "open-picker")
        steps = response["trace"]["steps_executed"]
        self.assertEqual(steps[0]["step"], "open-picker")
        self.assertFalse(steps[0]["ok"])
        self.assertEqual(steps[0]["view"], "year")
        self.assertIn("year-only", response["message"])

    def test_pick_date_verify_step_catches_value_mismatch(self):
        managed = next(iter(self.daemon.pages.values()))
        managed.last_signature = self.daemon._signature_for_page(managed)

        class StubInput:
            def __init__(self, value):
                self._value = value

            def wait_for(self, **_kwargs):
                return None

            def scroll_into_view_if_needed(self):
                return None

            def is_enabled(self):
                return True

            def bounding_box(self):
                return {"x": 0, "y": 0, "width": 100, "height": 24}

            def evaluate(self, script):
                if "elementFromPoint" in script:
                    return False
                return {"visible": True, "enabled": True, "expanded": None, "selected": None, "checked": None, "value": self._value, "text": self._value}

            def click(self):
                return None

            def input_value(self):
                return self._value

            def inner_text(self):
                return self._value

            @property
            def first(self):
                return self

            def nth(self, _i):
                return self

            def count(self):
                return 1

        stub = StubInput(value="1930-04-30")
        self.daemon.target_registry[(managed.page_id, "date-input")] = LocatorRecipe(
            target_id="date-input",
            page_id=managed.page_id,
            scope_id="page",
            scope_label="page",
            scope_selector=None,
            selector="#date-input",
            role="textbox",
            name="Status Date",
            text="",
            index=1,
        )
        self.page.picker_view_response = {"ok": True, "view": "day", "cells": 35}

        with mock.patch.object(self.daemon, "_resolve_recipe", return_value=stub):
            with mock.patch.object(self.page, "get_by_role", return_value=stub):
                response = self.daemon.handle("pick-date", {"target_id": "date-input", "iso_date": "2026-04-30"})

        self.assertFalse(response["ok"])
        self.assertEqual(response["trace"]["failed_at"], "verify")
        verify = [s for s in response["trace"]["steps_executed"] if s["step"] == "verify"]
        self.assertTrue(verify)
        self.assertFalse(verify[-1]["ok"])
        self.assertEqual(verify[-1]["expected"], "2026-04-30")
        self.assertEqual(verify[-1]["actual"], "1930-04-30")


class FrameworkPluginTest(unittest.TestCase):
    def test_framework_config_aggregates_registered_plugin_hints(self):
        from browse.frameworks import (
            FrameworkHints,
            framework_config,
            make_plugin,
            register_plugin,
            reset_plugins,
        )

        try:
            radix_plugin = make_plugin(
                FrameworkHints(
                    name="radix",
                    overlay_selectors=("[data-radix-popper-content-wrapper]",),
                )
            )
            register_plugin(radix_plugin)
            config = framework_config()
            self.assertIn(".MuiPickersPopper-root", config["overlaySelectors"])
            self.assertIn("[data-radix-popper-content-wrapper]", config["overlaySelectors"])
            self.assertIn(".MuiPickersYearSelection-container", config["yearViewSelectors"])
        finally:
            reset_plugins()

    def test_daemon_inspect_passes_framework_overlay_selectors(self):
        from browse.frameworks import framework_config

        page = FakePage()
        daemon = BrowseDaemon(port=9222)
        daemon.browser = FakeBrowser(page)
        daemon.refresh_pages(auto_select=True)
        managed = next(iter(daemon.pages.values()))

        daemon._inspect_dom(managed)
        self.assertIs(page.last_evaluate_script, INSPECT_JS)
        opts = page.last_evaluate_args[0]
        config = framework_config()
        for selector in config["overlaySelectors"]:
            self.assertIn(selector, opts["overlaySelectors"])
        self.assertFalse(opts["includeOffscreen"])


if __name__ == "__main__":
    unittest.main()
