---
name: browse
description: "Open localhost or dev pages in a real browser and drive them through short inspect/action loops for UI verification. Use only when the user explicitly asks for browser verification, screenshots, or invokes this skill directly."
argument-hint: "[url]"
---

# /browse

Use this skill only for explicit browser verification work.

## When to use

- The user explicitly asks for a browser screenshot
- The user explicitly asks to verify UI changes in a real browser
- The user explicitly invokes `/browse`

Do not auto-trigger this skill for ordinary coding or debugging.

## Workflow

1. Confirm the target URL.
   Use a concrete dev-server URL such as `http://localhost:3000`. If the saved base URL is correct, `browse open` and `browse snapshot` can omit it.

2. Make sure the visible browser session exists.
   `browse chrome` is both the visible browser AND the daemon — there's no separate `browse session start` step. If the daemon isn't running, start it detached:
   ```bash
   BROWSE_CHROME_CHANNEL=chrome browse chrome --background
   ```
   This launches the user's installed Google Chrome.app under Playwright's control, opens a window, and serves the daemon socket — all in one detached background process. `--background` returns once the daemon is responsive (or fails fast with a log path on error).

   `BROWSE_CHROME_CHANNEL=chrome` uses the user's installed Chrome.app, which is required on recent macOS — Playwright's bundled Chromium is unsigned and AMFI kills it with SIGTRAP before launch.

   To check if a session is already up: `browse session status` (returns ok if a supervisor is running, error otherwise). Don't relaunch if it's already up — the same profile dir can't be opened twice. If auth is needed, have the user open the visible window and sign in there once.

3. Always work in short observe/act loops:
   ```bash
   browse inspect
   browse click <target_id>
   browse inspect
   ```

4. Prefer composites for hostile widgets:
   ```bash
   browse choose <target_id> "Completed"
   browse pick-date <target_id> 2026-04-30
   browse submit
   ```

5. Use `--if-version` when the page may have changed between observation and action.

6. Use `browse screenshot --output /tmp/page.png` or `browse snapshot --output /tmp/page.png` before summarizing results.

7. Inspect both outputs before reporting:
   - the JSON command responses
   - the screenshot file if one was written

## Notes

- `browse chrome` launches the user's installed Google Chrome.app (when `BROWSE_CHROME_CHANNEL=chrome`) under Playwright's control with a dedicated profile at `~/.browse/chrome-profile`. Same process serves the daemon socket — no separate `session start` needed.
- The user's daily Chrome and `browse`'s Chrome use different `--user-data-dir` so they don't interfere.
- If login expires, have the user open the visible Chrome window and sign in again. Auth state lives in the dedicated profile dir and persists across `browse chrome` restarts (for cookies/localStorage that aren't session-only).
- If a composite fails, read its trace (`steps_executed`, `failed_at`, `scope_at_failure`, `inspect_snapshot`) and fall back to primitives.
- To shut down: `browse session stop` (graceful — closes Chrome and exits the supervisor) or `browse chrome --cleanup` (force-kills any browse-profile Chrome processes).

## Native MUI Select fallback

If `browse choose` returns `ok: false` on a button-style MUI v4 `<Select>`, the menu is usually still open. The reliable fallback is keyboard navigation:

```bash
browse press ArrowDown
browse press Enter
```

`browse choose` already routes button-style triggers to a click-the-option flow scoped to the active overlay, but tightly-styled custom dropdowns can still miss. The keyboard fallback works regardless.

## Slow daemon responses

If a long action causes the CLI to error with "did not respond within Ns", the daemon may still be running the command. Set `BROWSE_TIMEOUT=120` (or higher) in the environment to wait longer before giving up.

## Year-only and month-only date pickers

`browse pick-date` is for day-grid pickers. If the date trigger opens a year-only or month-only picker (no 7-column day grid), `pick-date` returns `ok: false` with `failed_at: "open-picker"` and `view: "year"|"month"` in the trace. Don't retry `pick-date` — instead use:

- `browse inspect` to find the year/month cell and `browse click` it directly, or
- `browse type <id> 2026` (or similar) if the trigger accepts free-form text.

`pick-date` also runs a post-action verification step: after committing a date, it reads the trigger value back and compares to the requested ISO date. If they differ, the trace includes `{step: "verify", ok: false, expected, actual}` and outer `ok` is `false`. Trust the verify step; do not assume `pick-day` succeeded just because it returned without error.

## Sign-in persistence

Auth survives across `browse chrome` restarts only if the dev app uses persistent cookies / localStorage. Apps that use session cookies will require re-signing in after a full Chrome quit. To inspect profile state: `browse chrome --status` prints the profile dir, the cookies-file size and mtime, and any Chrome PIDs currently using the profile.
