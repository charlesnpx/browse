---
name: browse
description: Use this skill only when the user explicitly asks for browser verification, screenshots, or directly invokes the skill. It drives localhost or dev pages in a real browser through daemon-backed inspect/action loops.
---

# Browse

Use this skill only for explicit browser verification.

## Workflow

1. Identify the exact URL to open, usually a localhost or staging page.
2. Ensure the browser+daemon supervisor is running. `browse chrome` is both the visible browser and the daemon — there is no separate `browse session start`. Check status first; only start if missing:
   ```bash
   browse session status || BROWSE_CHROME_CHANNEL=chrome browse chrome --background
   ```
   `BROWSE_CHROME_CHANNEL=chrome` is required on macOS — Playwright's bundled Chromium is unsigned and AMFI kills it on launch. `--background` detaches the supervisor and returns once the daemon socket is responsive (or fails fast with a log path).

   If the app needs auth, instruct the user to sign in inside the visible Chrome window after the supervisor starts.
3. Use `browse inspect` first. Choose `target_id`s from the semantic JSON output.
5. Prefer short loops: inspect → action → inspect.
6. Use primitives for clear single-step actions:
   - `browse click <target_id>`
   - `browse type <target_id> "..."`
   - `browse press Enter`
   - `browse wait --target <target_id>`
7. Use composites for hostile widgets:
   - `browse choose <target_id> "Completed"`
   - `browse pick-date <target_id> 2026-04-30`
   - `browse submit`
8. Use `--if-version` when acting on a previously observed state.
9. Use `browse screenshot --output /tmp/page.png` or `browse snapshot --output /tmp/page.png` before claiming visual success.
10. Inspect the JSON response and any written screenshot before reporting results.

## Notes

- `browse chrome` (with `BROWSE_CHROME_CHANNEL=chrome`) launches the user's installed Google Chrome.app under Playwright control with a dedicated profile at `~/.browse/chrome-profile`. The same process serves the daemon socket — no separate `session start`.
- The user's daily Chrome and `browse`'s Chrome use different `--user-data-dir` so they don't interfere.
- To shut down: `browse session stop` (graceful) or `browse chrome --cleanup` (force-kill any browse-profile Chrome processes).
- If a composite fails, inspect its trace and drop down to primitives at the failed step.
- If the configured base URL is missing or outdated, instruct the user to run `browse config`.

## Native MUI Select fallback

If `browse choose` returns `ok: false` on a button-style MUI v4 `<Select>`, the menu is usually still open. Fall back to keyboard navigation: `browse press ArrowDown` then `browse press Enter`. This works even when the role/name match is ambiguous in the open menu.

## Slow daemon responses

If a CLI call errors with "did not respond within Ns", the daemon may still be running the action. Raise `BROWSE_TIMEOUT=<seconds>` in the environment before retrying — the default is 60s.

## Year-only and month-only date pickers

`browse pick-date` is for day-grid pickers. On a year-only / month-only picker it returns `ok: false` with `failed_at: "open-picker"` and `view: "year"|"month"` — do not retry. Use `browse click` on the year/month cell directly, or `browse type` if the trigger accepts free-form text. `pick-date` also runs a post-action `verify` step that reads the value back and compares to the requested ISO date; treat outer `ok: false` as authoritative.

## Sign-in persistence

Auth survives `browse chrome` restarts only if the dev app uses persistent cookies / localStorage. Run `browse chrome --status` to print profile-dir diagnostics (cookies file size/mtime, Chrome PIDs using the profile).
