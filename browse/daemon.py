from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from browse.browser import (
    BrowseError,
    DEFAULT_CDP_HOST,
    DEFAULT_PORT,
    DEFAULT_VIEWPORT,
    BrowserLaunchConfig,
    connect_over_cdp,
)
from browse.frameworks import framework_config
from browse.protocol import DaemonResponse, json_safe, session_socket_path

DEFAULT_IDLE_TIMEOUT_SECONDS = 900

INSPECT_JS = r"""
(opts) => {
  const MAX_ITEMS = 120;
  const INCLUDE_OFFSCREEN = !!(opts && opts.includeOffscreen);
  const baseScopeSelectors = [
    '[role="dialog"]',
    '[role="listbox"]',
    '[role="menu"]',
    '[role="grid"]',
    '[role="tree"]',
  ];
  const extraOverlay = (opts && Array.isArray(opts.overlaySelectors)) ? opts.overlaySelectors : [];
  const scopeSelectors = baseScopeSelectors.concat(extraOverlay);
  const interactiveSelectors = [
    'button',
    'a[href]',
    'input',
    'textarea',
    'select',
    '[role]',
    '[tabindex]',
    '[contenteditable="true"]',
  ];

  const cssEscape = (value) => {
    if (globalThis.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  };

  const isVisible = (el) => {
    if (!el || !(el instanceof Element)) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    if (!INCLUDE_OFFSCREEN) {
      if (rect.bottom <= 0 || rect.right <= 0) return false;
      if (rect.top >= window.innerHeight || rect.left >= window.innerWidth) return false;
    }
    return true;
  };

  const isEnabled = (el) => !el.matches(':disabled,[disabled],[aria-disabled="true"]');

  const implicitRole = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (['email', 'number', 'password', 'search', 'tel', 'text', 'url', 'date'].includes(type)) return 'textbox';
    }
    return '';
  };

  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();

  const labelText = (id) => {
    const found = document.getElementById(id);
    return found ? textOf(found) : '';
  };

  const isDisabledOption = (el) => {
    if (!el || !el.matches) return false;
    return el.matches('[aria-disabled="true"],[disabled],:disabled');
  };

  const optionContainerLabel = (el) => {
    const optionEls = Array.from(el.querySelectorAll('[role="option"],[role="menuitem"]'))
      .filter((opt) => !isDisabledOption(opt));
    if (!optionEls.length) return '';
    const names = optionEls.map((opt) => textOf(opt)).filter(Boolean);
    let joined = names.join(' ');
    if (joined.length > 80) joined = joined.slice(0, 77) + '...';
    return joined;
  };

  const accessibleName = (el) => {
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel.trim();
    const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map(labelText).filter(Boolean);
      if (parts.length) return parts.join(' ');
    }
    if (el.id) {
      const label = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
      if (label) return textOf(label);
    }
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) {
      const parentLabel = el.closest('label');
      if (parentLabel) return textOf(parentLabel);
      if (el.placeholder) return el.placeholder.trim();
      if (el.value && ['button', 'submit', 'reset'].includes((el.type || '').toLowerCase())) return el.value.trim();
    }
    const title = el.getAttribute('title');
    if (title) return title.trim();
    if (el.matches && el.matches('[role="listbox"],[role="menu"],[role="presentation"]')) {
      const optionLabel = optionContainerLabel(el);
      if (optionLabel) return optionLabel;
    }
    const fallback = textOf(el);
    return fallback.length > 80 ? fallback.slice(0, 77) + '...' : fallback;
  };

  const cssPath = (el) => {
    if (el.id) return `#${cssEscape(el.id)}`;
    const segments = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) {
        segments.unshift(tag);
        break;
      }
      const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
      const index = siblings.indexOf(node) + 1;
      segments.unshift(`${tag}:nth-of-type(${index})`);
      node = parent;
    }
    segments.unshift('body');
    return segments.join(' > ');
  };

  const scopeName = (el, index) => {
    const role = implicitRole(el) || el.getAttribute('role') || 'group';
    const name = accessibleName(el);
    if (name) return `${role}: ${name}`;
    return `${role || 'scope'} ${index + 1}`;
  };

  const scopeNodes = Array.from(document.querySelectorAll(scopeSelectors.join(',')))
    .filter(isVisible)
    .map((el, index) => {
      const rect = el.getBoundingClientRect();
      return {
        id: `scope-${index + 1}`,
        label: scopeName(el, index),
        selector: cssPath(el),
        role: implicitRole(el) || el.getAttribute('role') || 'scope',
        rect: {top: rect.top, left: rect.left, width: rect.width, height: rect.height},
        zIndex: parseInt(getComputedStyle(el).zIndex || '0', 10) || 0,
        el,
      };
    })
    .sort((a, b) => (b.zIndex - a.zIndex) || (b.rect.width * b.rect.height - a.rect.width * a.rect.height));

  const ownerScope = (el) => {
    for (const scope of scopeNodes) {
      if (scope.el === el) continue;
      if (scope.el.contains(el)) return scope;
    }
    return null;
  };

  const uniqueNodes = [];
  const seen = new Set();
  Array.from(document.querySelectorAll(interactiveSelectors.join(','))).forEach((el) => {
    if (!(el instanceof Element) || seen.has(el) || !isVisible(el)) return;
    const role = implicitRole(el);
    if (!role && !el.hasAttribute('tabindex') && el.getAttribute('contenteditable') !== 'true') return;
    seen.add(el);
    uniqueNodes.push(el);
  });

  const focused = document.activeElement instanceof Element ? cssPath(document.activeElement) : null;

  const items = uniqueNodes.slice(0, MAX_ITEMS).map((el) => {
    const rect = el.getBoundingClientRect();
    const scope = ownerScope(el);
    const role = implicitRole(el) || el.getAttribute('role') || 'generic';
    const name = accessibleName(el);
    const text = textOf(el);
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type') || null;
    return {
      selector: cssPath(el),
      scopeId: scope ? scope.id : 'page',
      scopeLabel: scope ? scope.label : 'page',
      role,
      name,
      text,
      tag,
      type,
      visible: true,
      enabled: isEnabled(el),
      expanded: el.getAttribute('aria-expanded'),
      selected: el.getAttribute('aria-selected'),
      checked: el.getAttribute('aria-checked') || (el instanceof HTMLInputElement ? String(el.checked) : null),
      value: (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) ? el.value : null,
      focused: focused === cssPath(el),
      bounding: {
        top: Math.round(rect.top),
        left: Math.round(rect.left),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    };
  });

  return {
    activeScopeId: scopeNodes.length ? scopeNodes[0].id : 'page',
    activeScopeLabel: scopeNodes.length ? scopeNodes[0].label : 'page',
    scopes: scopeNodes.map(({el, ...rest}) => rest),
    items,
    focusedSelector: focused,
    title: document.title,
  };
}
"""

FOCUSED_JS = r"""
() => {
  const el = document.activeElement;
  if (!el || !(el instanceof Element)) return null;
  const role = el.getAttribute('role') || el.tagName.toLowerCase();
  const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.textContent || '';
  return { role, name: name.trim().slice(0, 80) };
}
"""

SIGNATURE_JS = r"""
(opts) => {
  const baseScopeSelectors = [
    '[role="dialog"]',
    '[role="listbox"]',
    '[role="menu"]',
    '[role="grid"]',
    '[role="tree"]',
  ];
  const extraOverlay = (opts && Array.isArray(opts.overlaySelectors)) ? opts.overlaySelectors : [];
  const scopeSelectors = baseScopeSelectors.concat(extraOverlay);
  const isVisible = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const cssEscape = (value) => {
    if (globalThis.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  };
  const cssPath = (el) => {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return `#${cssEscape(el.id)}`;
    const segments = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) { segments.unshift(tag); break; }
      const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      const index = siblings.indexOf(node) + 1;
      segments.unshift(`${tag}:nth-of-type(${index})`);
      node = parent;
    }
    segments.unshift('body');
    return segments.join(' > ');
  };
  const scopeNodes = Array.from(document.querySelectorAll(scopeSelectors.join(','))).filter(isVisible);
  let topScopeLabel = 'page';
  if (scopeNodes.length) {
    let topMost = scopeNodes[0];
    let topZ = parseInt(getComputedStyle(topMost).zIndex || '0', 10) || 0;
    for (const candidate of scopeNodes) {
      const z = parseInt(getComputedStyle(candidate).zIndex || '0', 10) || 0;
      if (z > topZ) { topMost = candidate; topZ = z; }
    }
    const role = topMost.getAttribute('role') || topMost.tagName.toLowerCase();
    const name = topMost.getAttribute('aria-label') || (topMost.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    topScopeLabel = name ? `${role}: ${name}` : role;
  }
  const focusedEl = document.activeElement instanceof Element ? document.activeElement : null;
  return {
    url: location.href,
    activeScopeLabel: topScopeLabel,
    scopeCount: scopeNodes.length,
    focusedSelector: focusedEl ? cssPath(focusedEl) : null,
  };
}
"""

ELEMENT_STATE_JS = r"""
(element) => {
  const attr = (name) => element.getAttribute(name);
  return {
    visible: true,
    enabled: !element.matches(':disabled,[disabled],[aria-disabled="true"]'),
    expanded: attr('aria-expanded'),
    selected: attr('aria-selected'),
    checked: attr('aria-checked') ?? (typeof element.checked === 'boolean' ? String(element.checked) : null),
    value: typeof element.value === 'string' ? element.value : null,
    text: (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160),
  };
}
"""

TOP_SCOPE_JS = r"""
(opts) => {
  const baseScopeSelectors = [
    '[role="dialog"]',
    '[role="listbox"]',
    '[role="menu"]',
    '[role="grid"]',
    '[role="tree"]',
  ];
  const extraOverlay = (opts && Array.isArray(opts.overlaySelectors)) ? opts.overlaySelectors : [];
  const scopeSelectors = baseScopeSelectors.concat(extraOverlay);
  const isVisible = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const cssEscape = (value) => {
    if (globalThis.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  };
  const cssPath = (el) => {
    if (el.id) return `#${cssEscape(el.id)}`;
    const segments = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) { segments.unshift(tag); break; }
      const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
      const index = siblings.indexOf(node) + 1;
      segments.unshift(`${tag}:nth-of-type(${index})`);
      node = parent;
    }
    segments.unshift('body');
    return segments.join(' > ');
  };
  const nodes = Array.from(document.querySelectorAll(scopeSelectors.join(','))).filter(isVisible);
  if (!nodes.length) return null;
  let top = nodes[0];
  let topZ = parseInt(getComputedStyle(top).zIndex || '0', 10) || 0;
  for (const n of nodes) {
    const z = parseInt(getComputedStyle(n).zIndex || '0', 10) || 0;
    if (z > topZ) { top = n; topZ = z; }
  }
  return cssPath(top);
}
"""

TARGET_KIND_JS = r"""
(element) => {
  if (!element) return { kind: 'unknown' };
  const tag = element.tagName ? element.tagName.toLowerCase() : '';
  const role = element.getAttribute ? element.getAttribute('role') : null;
  const isInput = tag === 'input' || tag === 'textarea';
  const hasInputChild = element.querySelector ? !!element.querySelector('input, textarea') : false;
  return {
    tag,
    role,
    isInput,
    hasInputChild,
    ariaHasPopup: element.getAttribute ? element.getAttribute('aria-haspopup') : null,
  };
}
"""

PICKER_VIEW_JS = r"""
(opts) => {
  const baseRoots = ['[role="dialog"]'];
  const extraRoots = (opts && Array.isArray(opts.dayPickerRootSelectors)) ? opts.dayPickerRootSelectors : [];
  const yearViews = (opts && Array.isArray(opts.yearViewSelectors)) ? opts.yearViewSelectors : [];
  const monthViews = (opts && Array.isArray(opts.monthViewSelectors)) ? opts.monthViewSelectors : [];
  const rootSelector = baseRoots.concat(extraRoots).join(',');
  const popover = rootSelector ? document.querySelector(rootSelector) : null;
  if (!popover) return { ok: false, reason: 'no-popover' };
  const grid = popover.querySelector('[role="grid"]');
  if (grid) {
    const cells = Array.from(grid.querySelectorAll('[role="gridcell"]'));
    if (!cells.length) return { ok: false, view: 'unknown', reason: 'empty-grid' };
    const firstTop = Math.round(cells[0].getBoundingClientRect().top);
    const firstRow = cells.filter((c) => Math.abs(Math.round(c.getBoundingClientRect().top) - firstTop) < 3);
    return { ok: firstRow.length === 7, view: firstRow.length === 7 ? 'day' : 'unknown', cells: cells.length, columns: firstRow.length };
  }
  if (yearViews.length && popover.querySelector(yearViews.join(','))) {
    return { ok: false, view: 'year', reason: 'year-only-picker' };
  }
  if (monthViews.length && popover.querySelector(monthViews.join(','))) {
    return { ok: false, view: 'month', reason: 'month-only-picker' };
  }
  return { ok: false, view: 'unknown', reason: 'no-grid' };
}
"""

OPTIONS_IN_SCOPE_JS = r"""
(scopeSelector) => {
  const root = scopeSelector ? document.querySelector(scopeSelector) : document;
  if (!root) return [];
  const els = Array.from(root.querySelectorAll('[role="option"],[role="menuitem"]'));
  return els.map((el) => ({
    text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(),
    name: el.getAttribute('aria-label') || '',
    disabled: el.matches('[aria-disabled="true"],[disabled],:disabled'),
  }));
}
"""

IS_OBSTRUCTED_JS = r"""
(element) => {
  const rect = element.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const top = document.elementFromPoint(x, y);
  return Boolean(top && top !== element && !element.contains(top));
}
"""


class DaemonProtocolError(BrowseError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload = {"code": self.code, "message": str(self)}
        payload.update(json_safe(self.details))
        return payload


@dataclass
class LocatorRecipe:
    target_id: str
    page_id: str
    scope_id: str
    scope_label: str
    scope_selector: str | None
    selector: str
    role: str
    name: str
    text: str
    index: int


@dataclass
class ManagedPage:
    page_id: str
    page: Any
    console_log: list[dict[str, Any]] = field(default_factory=list)
    state_version: int = 0
    last_signature: str | None = None


class BrowseDaemon:
    def __init__(self, port: int, idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS):
        self.port = port
        self.idle_timeout_seconds = idle_timeout_seconds
        self.socket_path = session_socket_path(port)
        self.manager = None
        self.browser = None
        self.pages: dict[int, ManagedPage] = {}
        self.selected_page_id: str | None = None
        self.target_registry: dict[tuple[str, str], LocatorRecipe] = {}
        self.last_activity = time.time()
        self.pid = os.getpid()
        self.should_stop = False

    def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.manager, self.browser = connect_over_cdp(self.port)
        self.refresh_pages(auto_select=True)

    def close(self) -> None:
        try:
            if self.manager is not None:
                self.manager.__exit__(None, None, None)
        finally:
            self.manager = None
            self.browser = None
            if self.socket_path.exists():
                self.socket_path.unlink()

    def refresh_pages(self, *, auto_select: bool = False) -> None:
        if self.browser is None:
            raise DaemonProtocolError("browser_disconnected", "The browse session is not attached to Chrome anymore.")
        seen: set[int] = set()
        flattened: list[Any] = []
        for context in self.browser.contexts:
            for page in context.pages:
                flattened.append(page)
                key = id(page)
                seen.add(key)
                if key not in self.pages:
                    managed = ManagedPage(page_id=f"page-{len(self.pages) + 1}", page=page)
                    self.pages[key] = managed
                    self._attach_page_listeners(managed)
        for key in list(self.pages.keys()):
            if key not in seen:
                managed = self.pages.pop(key)
                self.target_registry = {
                    registry_key: recipe
                    for registry_key, recipe in self.target_registry.items()
                    if recipe.page_id != managed.page_id
                }
                if self.selected_page_id == managed.page_id:
                    self.selected_page_id = None
        if auto_select and flattened:
            self.selected_page_id = self.pages[id(flattened[-1])].page_id
        elif self.selected_page_id is None and flattened:
            self.selected_page_id = self.pages[id(flattened[-1])].page_id

    def _attach_page_listeners(self, managed: ManagedPage) -> None:
        page = managed.page
        page.on("console", lambda msg, managed=managed: self._append_console_entry(managed, {"type": f"console:{msg.type}", "message": msg.text}))
        page.on("pageerror", lambda exc, managed=managed: self._append_console_entry(managed, {"type": "pageerror", "message": str(exc)}))
        page.on(
            "requestfailed",
            lambda request, managed=managed: self._append_console_entry(
                managed,
                {
                    "type": "requestfailed",
                    "message": f"{request.method} {request.url} -> {request.failure.error_text if request.failure else 'unknown error'}",
                },
            ),
        )

    @staticmethod
    def _append_console_entry(managed: ManagedPage, entry: dict[str, Any]) -> None:
        managed.console_log.append(entry)
        if len(managed.console_log) > 200:
            del managed.console_log[:-200]

    def _selected_page(self) -> ManagedPage:
        self.refresh_pages()
        for managed in self.pages.values():
            if managed.page_id == self.selected_page_id:
                return managed
        raise DaemonProtocolError("no_page", "No active page is selected. Open a tab in the attached Chrome window first.")

    def _framework_opts(self, **extras: Any) -> dict[str, Any]:
        opts = dict(framework_config())
        opts.update(extras)
        return opts

    def _inspect_dom(self, managed: ManagedPage, include_offscreen: bool = False) -> dict[str, Any]:
        snapshot = managed.page.evaluate(
            INSPECT_JS,
            self._framework_opts(includeOffscreen=include_offscreen),
        )
        return snapshot

    def _signature_for_page(self, managed: ManagedPage) -> str:
        try:
            snapshot = managed.page.evaluate(SIGNATURE_JS, self._framework_opts())
        except Exception:
            snapshot = {
                "url": managed.page.url,
                "activeScopeLabel": "page",
                "scopeCount": 0,
                "focusedSelector": None,
            }
        return json.dumps(snapshot, sort_keys=True)

    def _sync_state_version(self, managed: ManagedPage) -> None:
        signature = self._signature_for_page(managed)
        if managed.last_signature is None:
            managed.last_signature = signature
            return
        if signature != managed.last_signature:
            managed.state_version += 1
            managed.last_signature = signature

    def _assert_version(self, managed: ManagedPage, expected: int | None) -> None:
        self._sync_state_version(managed)
        if expected is not None and managed.state_version != expected:
            raise DaemonProtocolError(
                "stale_state",
                "The page changed since the last observation. Re-run `browse inspect`.",
                observed_state_version=managed.state_version,
                page_id=managed.page_id,
            )

    def _make_response(self, command: str, managed: ManagedPage | None, payload: dict[str, Any] | None = None, message: str | None = None, ok: bool = True) -> dict[str, Any]:
        return DaemonResponse(
            ok=ok,
            command=command,
            page_id=managed.page_id if managed is not None else None,
            state_version=managed.state_version if managed is not None else None,
            message=message,
            payload=json_safe(payload or {}),
        ).to_dict()

    def _page_title(self, managed: ManagedPage) -> str:
        try:
            return managed.page.title()
        except Exception:
            return ""

    def _page_list(self) -> list[dict[str, Any]]:
        self.refresh_pages()
        items = []
        for managed in self.pages.values():
            items.append(
                {
                    "page_id": managed.page_id,
                    "url": managed.page.url,
                    "title": self._page_title(managed),
                    "selected": managed.page_id == self.selected_page_id,
                    "state_version": managed.state_version,
                }
            )
        return items

    def _resolve_recipe(self, managed: ManagedPage, target_id: str):
        recipe = self.target_registry.get((managed.page_id, target_id))
        if recipe is None:
            raise DaemonProtocolError(
                "unknown_target",
                f"Unknown target_id `{target_id}` for page {managed.page_id}. Re-run `browse inspect`.",
                page_id=managed.page_id,
            )
        page = managed.page
        bases = []
        if recipe.scope_selector:
            bases.append(page.locator(recipe.scope_selector).first)
        bases.append(page)

        semantic_matches = []
        for base in bases:
            try:
                if recipe.role and recipe.name:
                    locator = base.get_by_role(recipe.role, name=recipe.name)
                    count = locator.count()
                    if count:
                        semantic_matches.append((locator, count))
                        if count >= recipe.index:
                            return locator.nth(recipe.index - 1)
                        return locator.first
            except Exception:
                continue

        css_bases = [page.locator(recipe.scope_selector).first] if recipe.scope_selector else []
        css_bases.append(page)
        for base in css_bases:
            locator = base.locator(recipe.selector)
            try:
                count = locator.count()
            except Exception:
                continue
            if count:
                return locator.first

        raise DaemonProtocolError(
            "target_not_found",
            f"target_id `{target_id}` is no longer present. Re-run `browse inspect`.",
            recipe=json_safe(recipe),
        )

    def _ensure_actionable(self, locator) -> tuple[dict[str, Any], dict[str, Any]]:
        locator.wait_for(state="visible")
        locator.scroll_into_view_if_needed()
        try:
            enabled = locator.is_enabled()
        except Exception:
            enabled = True
        if not enabled:
            raise DaemonProtocolError("disabled", "Target exists but is disabled.")
        first_box = locator.bounding_box()
        if first_box is None:
            raise DaemonProtocolError("not_visible", "Target is not visible enough to interact with.")
        time.sleep(0.1)
        second_box = locator.bounding_box() or first_box
        if any(abs((first_box.get(key) or 0) - (second_box.get(key) or 0)) > 1 for key in ("x", "y", "width", "height")):
            time.sleep(0.1)
        obstructed = locator.evaluate(IS_OBSTRUCTED_JS)
        if obstructed:
            raise DaemonProtocolError("obstructed", "Target is covered by another element or overlay.")
        before = locator.evaluate(ELEMENT_STATE_JS)
        return before, second_box

    def _after_state(self, locator) -> dict[str, Any]:
        return locator.evaluate(ELEMENT_STATE_JS)

    def _bump_after_action(self, managed: ManagedPage) -> None:
        managed.state_version += 1
        managed.last_signature = None

    def handle(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        self.last_activity = time.time()
        if command == "status":
            self.refresh_pages(auto_select=True)
            managed = None
            if self.selected_page_id is not None:
                try:
                    managed = self._selected_page()
                    self._sync_state_version(managed)
                except DaemonProtocolError:
                    managed = None
            return self._make_response(
                command,
                managed,
                payload={
                    "pid": self.pid,
                    "port": self.port,
                    "socket_path": str(self.socket_path),
                    "selected_page_id": self.selected_page_id,
                    "pages": self._page_list(),
                    "idle_timeout_seconds": self.idle_timeout_seconds,
                },
            )
        if command == "stop":
            managed = None
            if self.selected_page_id is not None:
                try:
                    managed = self._selected_page()
                except DaemonProtocolError:
                    managed = None
            self.should_stop = True
            return self._make_response(command, managed, payload={"stopped": True})
        if command == "pages":
            managed = self._selected_page()
            self._sync_state_version(managed)
            return self._make_response(command, managed, payload={"pages": self._page_list()})
        if command == "select-page":
            page_id = params["page_id"]
            self.refresh_pages()
            for managed in self.pages.values():
                if managed.page_id == page_id:
                    self.selected_page_id = page_id
                    managed.state_version += 1
                    managed.last_signature = self._signature_for_page(managed)
                    return self._make_response(command, managed, payload={"selected": page_id})
            raise DaemonProtocolError("unknown_page", f"Unknown page_id `{page_id}`.")
        if command == "open":
            managed = self._selected_page()
            self._assert_version(managed, params.get("if_version"))
            managed.page.goto(params["url"], wait_until="networkidle")
            self._bump_after_action(managed)
            return self._make_response(command, managed, payload={"url": managed.page.url, "title": self._page_title(managed)})
        if command == "inspect":
            managed = self._selected_page()
            self._sync_state_version(managed)
            snapshot = self._inspect_dom(managed, include_offscreen=bool(params.get("include_offscreen")))
            self.target_registry = {
                key: recipe for key, recipe in self.target_registry.items() if recipe.page_id != managed.page_id
            }
            scope_counts: dict[tuple[str, str, str], int] = {}
            groups: dict[str, dict[str, Any]] = {"page": {"scope_id": "page", "label": "page", "items": []}}
            for scope in snapshot.get("scopes", []):
                groups[scope["id"]] = {"scope_id": scope["id"], "label": scope["label"], "items": []}
            for item in snapshot.get("items", []):
                scope_id = item.get("scopeId") or "page"
                key = (scope_id, item.get("role") or "", item.get("name") or item.get("text") or item.get("selector"))
                scope_counts[key] = scope_counts.get(key, 0) + 1
                target_id = uuid.uuid4().hex[:10]
                scope_label = item.get("scopeLabel") or groups.get(scope_id, {"label": "page"})["label"]
                scope_selector = None
                if scope_id != "page":
                    scope_info = next((scope for scope in snapshot.get("scopes", []) if scope["id"] == scope_id), None)
                    scope_selector = scope_info.get("selector") if scope_info else None
                recipe = LocatorRecipe(
                    target_id=target_id,
                    page_id=managed.page_id,
                    scope_id=scope_id,
                    scope_label=scope_label,
                    scope_selector=scope_selector,
                    selector=item["selector"],
                    role=item.get("role") or "",
                    name=item.get("name") or "",
                    text=item.get("text") or "",
                    index=scope_counts[key],
                )
                self.target_registry[(managed.page_id, target_id)] = recipe
                item_payload = dict(item)
                item_payload["target_id"] = target_id
                groups.setdefault(scope_id, {"scope_id": scope_id, "label": scope_label, "items": []})["items"].append(item_payload)
            ordered_groups = []
            active_scope_id = snapshot.get("activeScopeId") or "page"
            for scope_id in [active_scope_id] + [scope["id"] for scope in snapshot.get("scopes", []) if scope["id"] != active_scope_id] + ["page"]:
                group = groups.get(scope_id)
                if group and group not in ordered_groups and group["items"]:
                    ordered_groups.append(group)
            return self._make_response(
                command,
                managed,
                payload={
                    "active_scope": snapshot.get("activeScopeLabel") or "page",
                    "groups": ordered_groups,
                    "url": managed.page.url,
                    "title": snapshot.get("title") or self._page_title(managed),
                },
            )
        if command in {"click", "type", "press", "wait", "screenshot", "console", "url", "back", "choose", "pick-date", "submit"}:
            managed = self._selected_page()
            self._assert_version(managed, params.get("if_version"))
            handler = getattr(self, f"_cmd_{command.replace('-', '_')}")
            return handler(managed, params)
        raise DaemonProtocolError("unknown_command", f"Unsupported daemon command `{command}`.")

    def _cmd_click(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        locator = self._resolve_recipe(managed, params["target_id"])
        before, _box = self._ensure_actionable(locator)
        locator.click()
        after = self._after_state(locator)
        self._bump_after_action(managed)
        return self._make_response(command="click", managed=managed, payload={"before": before, "after": after})

    def _cmd_type(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        locator = self._resolve_recipe(managed, params["target_id"])
        before, _box = self._ensure_actionable(locator)
        try:
            locator.fill(params["text"])
        except Exception:
            locator.click()
            locator.press_sequentially(params["text"])
        after = self._after_state(locator)
        self._bump_after_action(managed)
        return self._make_response(command="type", managed=managed, payload={"before": before, "after": after})

    def _cmd_press(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        managed.page.keyboard.press(params["key"])
        self._bump_after_action(managed)
        return self._make_response(command="press", managed=managed, payload={"key": params["key"]})

    def _cmd_wait(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("milliseconds") is not None:
            managed.page.wait_for_timeout(int(params["milliseconds"]))
        elif params.get("target_id"):
            locator = self._resolve_recipe(managed, params["target_id"])
            locator.wait_for(state="visible")
        elif params.get("url_contains"):
            managed.page.wait_for_url(f"**{params['url_contains']}**")
        else:
            raise DaemonProtocolError("invalid_wait", "Provide --target, --url-contains, or --milliseconds for `browse wait`.")
        self._sync_state_version(managed)
        return self._make_response(command="wait", managed=managed, payload={"waited": True})

    def _cmd_screenshot(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        output = Path(params["output"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        managed.page.screenshot(path=str(output), full_page=bool(params.get("full_page", True)))
        self._sync_state_version(managed)
        return self._make_response(command="screenshot", managed=managed, payload={"output": str(output)})

    def _cmd_console(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit") or 50)
        self._sync_state_version(managed)
        return self._make_response(command="console", managed=managed, payload={"entries": managed.console_log[-limit:]})

    def _cmd_url(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        self._sync_state_version(managed)
        return self._make_response(command="url", managed=managed, payload={"url": managed.page.url, "title": self._page_title(managed)})

    def _cmd_back(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        managed.page.go_back(wait_until="networkidle")
        self._bump_after_action(managed)
        return self._make_response(command="back", managed=managed, payload={"url": managed.page.url})

    def _cmd_choose(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        target_id = params["target_id"]
        text = params["text"]
        steps: list[dict[str, Any]] = []
        current_step = "resolve-target"
        try:
            locator = self._resolve_recipe(managed, target_id)
            self._ensure_actionable(locator)
            kind = self._classify_target(locator)
            current_step = "open"
            locator.click()
            steps.append({"step": "open", "ok": True, "kind": kind})

            if kind.get("isInput") or kind.get("hasInputChild"):
                current_step = "enter-text"
                self._enter_text_into(locator, kind, text)
                steps.append({"step": "enter-text", "ok": True, "text": text})

            current_step = "select-option"
            managed.page.wait_for_timeout(120)
            option = self._find_option_in_active_scope(managed, text)
            if option is None:
                available = self._available_options_in_scope(managed)
                visible = [opt for opt in available if not opt.get("disabled")]
                disabled = [opt for opt in available if opt.get("disabled")]
                steps.append(
                    {
                        "step": "select-option",
                        "ok": False,
                        "reason": "no-match",
                        "available": [opt.get("text") for opt in visible[:20]],
                        "disabled_options": [opt.get("text") for opt in disabled[:10]],
                    }
                )
                preview = ", ".join(opt.get("text") or "" for opt in visible[:10] if opt.get("text"))
                if not preview:
                    preview = "(no enabled options found)"
                raise DaemonProtocolError(
                    "option_not_found",
                    f"No option matched `{text}` in the active overlay. Available: {preview}. "
                    "If the menu is open, `browse press ArrowDown` then `browse press Enter` is a reliable fallback.",
                )
            option.click()
            steps.append({"step": "select-option", "ok": True})

            self._bump_after_action(managed)
            return self._make_response(
                command="choose",
                managed=managed,
                payload={"trace": {"ok": True, "steps_executed": steps}},
            )
        except DaemonProtocolError as exc:
            if not steps or steps[-1].get("step") != current_step or steps[-1].get("ok") is True:
                if current_step != "select-option" or not any(
                    s.get("step") == "select-option" and s.get("ok") is False for s in steps
                ):
                    steps.append({"step": current_step, "ok": False, "reason": exc.code})
            snapshot = self._inspect_dom(managed)
            return self._make_response(
                command="choose",
                managed=managed,
                ok=False,
                payload={
                    "trace": {
                        "ok": False,
                        "steps_executed": steps,
                        "failed_at": current_step,
                        "scope_at_failure": snapshot.get("activeScopeLabel") or "page",
                        "inspect_snapshot": snapshot,
                    }
                },
                message=str(exc),
            )

    def _available_options_in_scope(self, managed: ManagedPage) -> list[dict[str, Any]]:
        page = managed.page
        try:
            scope_selector = page.evaluate(TOP_SCOPE_JS, self._framework_opts())
        except Exception:
            scope_selector = None
        try:
            options = page.evaluate(OPTIONS_IN_SCOPE_JS, scope_selector)
        except Exception:
            return []
        if not isinstance(options, list):
            return []
        return [opt for opt in options if isinstance(opt, dict)]

    def _classify_target(self, locator) -> dict[str, Any]:
        try:
            kind = locator.evaluate(TARGET_KIND_JS)
        except Exception:
            return {"kind": "unknown"}
        return kind or {"kind": "unknown"}

    def _enter_text_into(self, locator, kind: dict[str, Any], text: str) -> None:
        try:
            locator.fill(text)
            return
        except Exception:
            pass
        try:
            locator.press_sequentially(text)
        except Exception:
            locator.type(text)

    def _find_option_in_active_scope(self, managed: ManagedPage, text: str):
        page = managed.page
        try:
            scope_selector = page.evaluate(TOP_SCOPE_JS, self._framework_opts())
        except Exception:
            scope_selector = None

        enabled_filter = ':not([aria-disabled="true"]):not([disabled])'
        option_selector = (
            f'[role="option"]{enabled_filter}, [role="menuitem"]{enabled_filter}'
        )

        bases = []
        if scope_selector:
            bases.append(page.locator(scope_selector).first)
        bases.append(page)

        target_lower = text.strip().lower()

        for base in bases:
            try:
                option_locator = base.locator(option_selector)
                count = option_locator.count()
            except Exception:
                count = 0
            if count:
                exact_index = -1
                substring_index = -1
                for i in range(count):
                    try:
                        candidate_text = (option_locator.nth(i).inner_text() or "").strip()
                    except Exception:
                        continue
                    if not candidate_text:
                        continue
                    if candidate_text == text:
                        return option_locator.nth(i)
                    candidate_lower = candidate_text.lower()
                    if exact_index == -1 and candidate_lower == target_lower:
                        exact_index = i
                    elif substring_index == -1 and target_lower and target_lower in candidate_lower:
                        substring_index = i
                if exact_index >= 0:
                    return option_locator.nth(exact_index)
                if substring_index >= 0:
                    return option_locator.nth(substring_index)

            try:
                exact_match = base.get_by_role("option", name=text, exact=True)
                if exact_match.count():
                    return exact_match.first
            except Exception:
                pass
            try:
                fuzzy_match = base.get_by_role("option", name=text, exact=False)
                if fuzzy_match.count():
                    return fuzzy_match.first
            except Exception:
                pass
            try:
                text_match = base.get_by_text(text, exact=True)
                if text_match.count():
                    return text_match.first
            except Exception:
                pass
        return None

    def _cmd_pick_date(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        target_id = params["target_id"]
        iso_date = params["iso_date"]
        steps: list[dict[str, Any]] = []
        current_step = "resolve-target"
        try:
            parsed = date.fromisoformat(iso_date)
            locator = self._resolve_recipe(managed, target_id)
            self._ensure_actionable(locator)
            current_step = "open-picker"
            locator.click()
            managed.page.wait_for_timeout(150)
            try:
                view_info = managed.page.evaluate(PICKER_VIEW_JS, self._framework_opts())
            except Exception:
                view_info = {"ok": False, "view": "unknown", "reason": "evaluate-failed"}
            view_info = view_info or {"ok": False, "view": "unknown"}
            if not view_info.get("ok"):
                steps.append({"step": "open-picker", "ok": False, **view_info})
                view = view_info.get("view") or "unknown"
                reason = view_info.get("reason") or "no-day-grid"
                raise DaemonProtocolError(
                    "not_day_picker",
                    f"Picker opened but is not a day grid (view={view}, reason={reason}). "
                    "For year-only pickers, use `browse click` on the year directly. "
                    "For free-form date inputs, use `browse type <id> YYYY-MM-DD`.",
                )
            steps.append({"step": "open-picker", "ok": True, "view": view_info.get("view"), "cells": view_info.get("cells")})

            current_step = "pick-day"
            day_name = str(parsed.day)
            day_locator = managed.page.get_by_role("gridcell", name=day_name, exact=True)
            if day_locator.count() == 0:
                day_locator = managed.page.get_by_role("button", name=day_name, exact=True)
            if day_locator.count() == 0:
                raise DaemonProtocolError("date_day_not_found", f"Could not find day cell `{day_name}` in the day grid.")
            day_locator.first.click()
            steps.append({"step": "pick-day", "ok": True, "day": day_name})

            current_step = "confirm"
            ok_button = managed.page.get_by_role("button", name="OK")
            if ok_button.count():
                ok_button.first.click()
                steps.append({"step": "confirm", "ok": True})

            current_step = "verify"
            verify_step = self._verify_date_value(managed, target_id, parsed, iso_date)
            steps.append(verify_step)
            if verify_step.get("ok") is False:
                raise DaemonProtocolError(
                    "value_mismatch",
                    f"Picker committed `{verify_step.get('actual')}` but expected `{iso_date}`. "
                    "The picker may not be a standard day-grid picker.",
                )

            self._bump_after_action(managed)
            return self._make_response(command="pick-date", managed=managed, payload={"trace": {"ok": True, "steps_executed": steps}})
        except DaemonProtocolError as exc:
            if not steps or steps[-1].get("step") != current_step or steps[-1].get("ok") is True:
                steps.append({"step": current_step, "ok": False, "reason": exc.code})
            snapshot = self._inspect_dom(managed)
            return self._make_response(
                command="pick-date",
                managed=managed,
                ok=False,
                payload={
                    "trace": {
                        "ok": False,
                        "steps_executed": steps,
                        "failed_at": current_step,
                        "scope_at_failure": snapshot.get("activeScopeLabel") or "page",
                        "inspect_snapshot": snapshot,
                    }
                },
                message=str(exc),
            )

    def _verify_date_value(self, managed: ManagedPage, target_id: str, parsed: date, iso_date: str) -> dict[str, Any]:
        try:
            locator = self._resolve_recipe(managed, target_id)
            try:
                actual = (locator.input_value() or "").strip()
            except Exception:
                actual = ""
            if not actual:
                try:
                    actual = (locator.inner_text() or "").strip()
                except Exception:
                    actual = ""
        except Exception:
            return {"step": "verify", "ok": None, "reason": "verify-skipped"}

        if not actual:
            return {"step": "verify", "ok": None, "reason": "no-readable-value"}

        year_str = str(parsed.year)
        if iso_date in actual or actual in iso_date:
            return {"step": "verify", "ok": True, "actual": actual}
        normalized = actual.replace("/", "-").replace(".", "-")
        if year_str in normalized and f"{parsed.month:02d}" in normalized and f"{parsed.day:02d}" in normalized:
            return {"step": "verify", "ok": True, "actual": actual}
        return {"step": "verify", "ok": False, "expected": iso_date, "actual": actual}

    def _cmd_submit(self, managed: ManagedPage, params: dict[str, Any]) -> dict[str, Any]:
        names = ["save", "submit", "ok", "apply", "done", "update"]
        candidates = []
        for name in names:
            locator = managed.page.get_by_role("button", name=name, exact=False)
            if locator.count():
                candidates.append(locator.first)
        if not candidates:
            raise DaemonProtocolError("submit_not_found", "Could not find a primary submit/save button in the current scope.")
        locator = candidates[0]
        before, _box = self._ensure_actionable(locator)
        locator.click()
        self._bump_after_action(managed)
        return self._make_response(command="submit", managed=managed, payload={"before": before})


class BrowseDaemonServer:
    def __init__(self, daemon: BrowseDaemon):
        self.daemon = daemon

    def serve_forever(self) -> None:
        self.daemon.start()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.daemon.socket_path))
        server.listen()
        server.settimeout(1.0)
        try:
            while not self.daemon.should_stop:
                if time.time() - self.daemon.last_activity > self.daemon.idle_timeout_seconds:
                    break
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    request: dict[str, Any] = {"command": "unknown", "params": {}}
                    try:
                        raw = self._read_line(conn)
                        request = json.loads(raw)
                        response = self.daemon.handle(request["command"], request.get("params") or {})
                    except DaemonProtocolError as exc:
                        response = DaemonResponse(ok=False, command=request.get("command", "unknown"), error=exc.to_payload()).to_dict()
                    except Exception as exc:  # pragma: no cover - defensive runtime path
                        response = DaemonResponse(ok=False, command=request.get("command", "unknown"), error={"code": "internal_error", "message": str(exc)}).to_dict()
                    conn.sendall((json.dumps(json_safe(response)) + "\n").encode("utf-8"))
        finally:
            server.close()
            self.daemon.close()

    @staticmethod
    def _read_line(conn: socket.socket) -> str:
        chunks: list[bytes] = []
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        if not chunks:
            raise DaemonProtocolError("empty_request", "Daemon received an empty request.")
        return b"".join(chunks).decode("utf-8").splitlines()[0]


def launch_daemon_process(port: int, idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS) -> subprocess.Popen[Any]:
    socket_path = session_socket_path(port)
    if socket_path.exists():
        socket_path.unlink()
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "browse.daemon",
            "serve",
            "--port",
            str(port),
            "--idle-timeout-seconds",
            str(idle_timeout_seconds),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_daemon(port: int, timeout_seconds: float = 5.0) -> None:
    from browse.protocol import send_request

    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            send_request(port, "status", {})
            return
        except Exception as exc:  # pragma: no cover - timing dependent
            last_error = exc
            time.sleep(0.1)
    raise BrowseError(f"The browse session did not become ready on port {port}: {last_error}")


def ensure_daemon_running(port: int, idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS) -> dict[str, Any]:
    from browse.protocol import send_request

    try:
        return send_request(port, "status", {})
    except BrowseError:
        process = launch_daemon_process(port, idle_timeout_seconds=idle_timeout_seconds)
        wait_for_daemon(port)
        response = send_request(port, "status", {})
        response.setdefault("started_pid", process.pid)
        return response


def build_daemon_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m browse.daemon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_parser.add_argument("--idle-timeout-seconds", type=int, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_daemon_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        daemon = BrowseDaemon(args.port, idle_timeout_seconds=args.idle_timeout_seconds)
        server = BrowseDaemonServer(daemon)
        server.serve_forever()
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
