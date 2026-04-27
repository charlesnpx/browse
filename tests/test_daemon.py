from __future__ import annotations

import unittest
from unittest import mock

from browse.daemon import (
    BrowseDaemon,
    LocatorRecipe,
    ManagedPage,
    SIGNATURE_JS,
    INSPECT_JS,
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
        self.assertEqual(response["trace"]["failed_at"], "open")
        self.assertIn("Completed", response["message"])


if __name__ == "__main__":
    unittest.main()
