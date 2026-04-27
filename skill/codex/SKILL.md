---
name: browse
description: Use this skill only when the user explicitly asks for browser verification, screenshots, or directly invokes the skill. It opens localhost or dev pages in a real browser and captures screenshots plus browser logs for UI verification.
---

# Browse

Use this skill only for explicit browser verification.

## Workflow

1. Identify the exact URL to open, usually a localhost or staging page.
2. If CDP is unavailable, instruct the user to run `browse chrome` and sign in there if needed.
3. Use `browse open <url>` when you need a visible page without capturing output.
4. Use `browse snapshot <url> --output /tmp/page.png` after UI changes instead of claiming visual success without checking.
5. For interactive steps, pass `--click`, `--fill`, `--wait-for`, and `--sleep-ms` in the exact order needed.
6. Inspect both `/tmp/page.png` and `/tmp/page.png.log` before reporting what happened.

## Examples

```bash
browse open http://localhost:3000
```

```bash
browse snapshot http://localhost:3000 --output /tmp/home.png
```

```bash
browse snapshot http://localhost:3000/login \
  --output /tmp/login.png \
  --fill 'input[name="email"]' 'dev@example.com' \
  --fill 'input[name="password"]' 'secret' \
  --click 'button[type="submit"]' \
  --wait-for '[data-testid="home"]'
```

