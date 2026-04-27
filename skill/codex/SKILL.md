---
name: browse
description: Use this skill only when the user explicitly asks for browser verification, screenshots, or directly invokes the skill. It opens localhost or dev pages in a real browser and captures screenshots plus browser logs for UI verification.
---

# Browse

Use this skill only for explicit browser verification.

## Workflow

1. Identify the exact URL to open, usually a localhost or staging page. If the saved base URL should be used, `browse open` and `browse snapshot` can omit the URL.
2. If CDP is unavailable, instruct the user to run `browse chrome` and sign in there if needed.
3. If the configured base URL is missing or outdated, instruct the user to run `browse config`.
4. Use `browse open` when you need a visible page without capturing output.
5. Use `browse snapshot --output /tmp/page.png` after UI changes instead of claiming visual success without checking.
6. For interactive steps, pass `--click`, `--fill`, `--wait-for`, and `--sleep-ms` in the exact order needed.
7. Inspect both `/tmp/page.png` and `/tmp/page.png.log` before reporting what happened.

## Examples

```bash
browse open
```

```bash
browse snapshot --output /tmp/home.png
```

```bash
browse snapshot http://localhost:3000/login \
  --output /tmp/login.png \
  --fill 'input[name="email"]' 'dev@example.com' \
  --fill 'input[name="password"]' 'secret' \
  --click 'button[type="submit"]' \
  --wait-for '[data-testid="home"]'
```
