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
   If the session is not running or CDP is unavailable, have the user run:
   ```bash
   browse chrome
   ```
   Then have them sign in inside that dedicated browser window if the app needs auth.

3. Start or reuse the daemon session:
   ```bash
   browse session start
   ```

4. Always work in short observe/act loops:
   ```bash
   browse inspect
   browse click <target_id>
   browse inspect
   ```

5. Prefer composites for hostile widgets:
   ```bash
   browse choose <target_id> "Completed"
   browse pick-date <target_id> 2026-04-30
   browse submit
   ```

6. Use `--if-version` when the page may have changed between observation and action.

7. Use `browse screenshot --output /tmp/page.png` or `browse snapshot --output /tmp/page.png` before summarizing results.

8. Inspect both outputs before reporting:
   - the JSON command responses
   - the screenshot file if one was written

## Notes

- `browse` uses your installed Chrome/Chromium binary, but keeps auth in a dedicated `browse` profile by default.
- If login expires, have the user reopen the `browse` browser window and sign in again there.
- If a composite fails, read its trace (`steps_executed`, `failed_at`, `scope_at_failure`, `inspect_snapshot`) and fall back to primitives.

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
