---
name: browse
description: Use this skill only when the user explicitly asks for browser verification, screenshots, or directly invokes the skill. It drives localhost or dev pages in a real browser through daemon-backed inspect/action loops.
---

# Browse

Use this skill only for explicit browser verification.

## Workflow

1. Identify the exact URL to open, usually a localhost or staging page.
2. If the visible browser session is missing, instruct the user to run `browse chrome` and sign in there if needed.
3. Start or reuse the daemon session with `browse session start`.
4. Use `browse inspect` first. Choose `target_id`s from the semantic JSON output.
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

- `browse` prefers the user’s installed Chrome/Chromium binary and a dedicated `browse` profile.
- If a composite fails, inspect its trace and drop down to primitives at the failed step.
- If the configured base URL is missing or outdated, instruct the user to run `browse config`.
