from __future__ import annotations

import unittest

from browse.daemon import BrowseDaemon, LocatorRecipe, ManagedPage


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

    def evaluate(self, script):
        if "document.activeElement" in script and "activeScopeId" not in script:
            return self.focused
        return self.inspect_snapshot

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
        self.page.focused = {"role": "button", "name": "Save"}

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


if __name__ == "__main__":
    unittest.main()
