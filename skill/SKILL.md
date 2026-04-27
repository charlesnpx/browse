---
name: browse
description: "Open localhost or dev pages in a real browser and capture screenshots plus browser logs for UI verification. Use only when the user explicitly asks for browser verification, screenshots, or invokes this skill directly."
argument-hint: "<url> [snapshot options]"
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
   Use a concrete dev-server URL such as `http://localhost:3000`.

2. Make sure the browser session exists.
   If CDP is unavailable or the command fails to connect, tell the user to run:
   ```bash
   browse chrome
   ```
   Then ask them to sign in inside that dedicated browser window if the app needs auth.

3. Use `browse open` for manual inspection when needed:
   ```bash
   browse open http://localhost:3000
   ```

4. Use `browse snapshot` for verification after UI changes instead of claiming visual success without checking:
   ```bash
   browse snapshot http://localhost:3000 --output /tmp/page.png
   ```

5. For interactive flows, apply ordered actions exactly as needed:
   ```bash
   browse snapshot http://localhost:3000/login \
     --output /tmp/login.png \
     --fill 'input[name="email"]' 'dev@example.com' \
     --fill 'input[name="password"]' 'secret' \
     --click 'button[type="submit"]' \
     --wait-for '[data-testid="home"]'
   ```

6. Inspect both outputs before summarizing:
   - the PNG screenshot
   - the adjacent `.log` file with console errors, page errors, and failed requests

## Notes

- `browse` uses a dedicated browser profile for session continuity.
- If login expires, have the user re-open the `browse` browser window and sign in again there.

