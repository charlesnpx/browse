# browse

`browse` is a small Playwright-backed CLI for opening dev pages in a real browser, keeping a dedicated signed-in session alive, and capturing screenshots plus browser logs for UI verification.

Version `0.1.0` is intentionally narrow:
- Python 3.11+
- `argparse`
- Chromium/Chrome launched in a dedicated profile
- CDP attachment for all browser work
- explicit-use Claude/Codex skills

## Install

```bash
pipx install git+ssh://git@github.com/charlesnpx/browse.git
```

or

```bash
# from a local checkout
pipx install ~/browse
```

Then run:

```bash
browse init
```

`browse init` installs the Playwright Chromium runtime and the bundled Claude/Codex skills. The first browser install downloads Chromium, so it can take a little longer on a clean machine.

## Commands

### `browse init`

Recommended first-run setup:

```bash
browse init
```

This is idempotent and internally runs:
- `browse install`
- `browse install-skills`

### `browse chrome`

Launch a visible Chrome/Chromium window with remote debugging enabled and a dedicated profile:

```bash
browse chrome
```

Defaults:
- port: `9222`
- profile dir: `~/.browse/chrome-profile`

Useful flags:

```bash
browse chrome --port 9333
browse chrome --profile-dir ~/tmp/browse-profile
```

This profile is separate from your normal browser profile so auth/session state persists for automation without touching your personal Chrome data.

### `browse open`

Open a page in the running CDP-attached browser:

```bash
browse open http://localhost:3000
```

If CDP is unavailable, `browse` will tell you to run `browse chrome`.

### `browse snapshot`

Capture a screenshot and sidecar log from the running browser:

```bash
browse snapshot http://localhost:3000 --output /tmp/home.png
```

Outputs:
- `/tmp/home.png`
- `/tmp/home.png.log`

The log captures:
- console messages
- page errors
- failed network requests
- action steps and failures

### Action examples

Wait for an element before capturing:

```bash
browse snapshot http://localhost:3000 \
  --output /tmp/dashboard.png \
  --wait-for '[data-testid="dashboard-root"]'
```

Click through UI in order:

```bash
browse snapshot http://localhost:3000 \
  --output /tmp/menu.png \
  --click 'button[aria-label="Open menu"]' \
  --wait-for '[role="menu"]'
```

Fill a form, click submit, then wait:

```bash
browse snapshot http://localhost:3000/login \
  --output /tmp/login.png \
  --fill 'input[name="email"]' 'dev@example.com' \
  --fill 'input[name="password"]' 'secret' \
  --click 'button[type="submit"]' \
  --wait-for '[data-testid="account-home"]'
```

Pause briefly between steps:

```bash
browse snapshot http://localhost:3000 \
  --output /tmp/animated.png \
  --click '.open-panel' \
  --sleep-ms 750
```

## Skills

Install the bundled skills with:

```bash
browse install-skills
```

Installed locations:

### Claude
- `~/.claude/skills/browse/SKILL.md`

### Codex
- `~/.codex/skills/browse/`

The skills are explicit-use only. They are meant for cases where the user directly asks for browser verification, screenshots, or invokes the skill by name.

## Troubleshooting

### Browser executable missing

If `browse chrome` says it cannot find a supported browser binary, install Google Chrome or Chromium in a standard macOS location such as `/Applications`.

### CDP connection refused

If `browse open` or `browse snapshot` cannot connect, start a browser session first:

```bash
browse chrome
```

Then sign in or establish the session in that dedicated window before retrying.

### Login expired

If your app redirects to a login screen or authenticated pages stop loading, re-open the dedicated `browse` browser window and sign in again there:

```bash
browse chrome
```

