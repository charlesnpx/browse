# browse

`browse` is a Playwright-backed CLI for real-browser UI verification. It attaches to a visible Chrome/Chromium session over CDP, keeps auth in a dedicated persistent profile, and now supports daemon-backed inspect/act loops for complex forms.

Version `0.2.0` centers on:
- Python 3.11+
- Playwright as the automation library
- your installed Chrome/Chromium binary as the browser engine
- a dedicated `browse` profile for auth/session continuity
- a long-lived session daemon with JSON-first action commands
- explicit-use Claude/Codex skills

## Install

```bash
pipx install git+https://github.com/charlesnpx/browse.git
```

or from a local checkout:

```bash
pipx install ~/WebstormProjects/browse
```

Then run:

```bash
browse init
```

`browse init`:
- verifies Playwright importability
- verifies a system Chrome/Chromium binary is discoverable
- installs bundled Claude/Codex skills
- runs first-time interactive config if needed

By default, `browse` does **not** install Playwright's bundled Chromium. If you do not have Chrome/Chromium installed in a standard location, use the explicit fallback:

```bash
browse install --bundled-chromium
```

## Recommended workflow

1. Launch the dedicated browser session:

```bash
browse chrome
```

2. Sign in there if your app requires authentication.

3. Start or reuse the daemon session:

```bash
browse session start
```

4. Drive the page in short observe/act loops:

```bash
browse inspect
browse click <target_id>
browse inspect
browse choose <target_id> "Completed"
browse pick-date <target_id> 2026-04-30
browse submit
browse screenshot --output /tmp/final.png
```

The new daemon-backed commands emit JSON by default so agents can parse them reliably.

## Commands

### Bootstrap

```bash
browse init
browse config
browse chrome
browse session start
browse session status
browse session stop
```

Saved config lives at `~/.browse/config.json` and stores:
- `base_url`
- `chrome_port`
- `chrome_profile_dir`

### Inspect and act

```bash
browse inspect
browse pages
browse select-page page-2
browse click <target_id>
browse type <target_id> "hello"
browse press Enter
browse wait --target <target_id>
browse wait --url-contains /review
browse wait --milliseconds 500
browse choose <target_id> "Application X"
browse pick-date <target_id> 2026-04-30
browse submit
browse console --limit 25
browse url
browse back
browse screenshot --output /tmp/page.png
```

### Convenience wrappers

These now run through the same daemon/session model:

```bash
browse open
browse open http://localhost:3000/app/investment-management/amots/87
browse snapshot --output /tmp/page.png
browse snapshot http://localhost:3000/app/investment-management/amots/87 --output /tmp/page.png
```

## Output contract

Daemon-backed commands return JSON with fields like:
- `ok`
- `command`
- `page_id`
- `state_version`
- command-specific payload

`browse inspect` returns grouped actionable nodes, each with a `target_id` plus semantic metadata such as role, accessible name, and state.

Mutating commands accept `--if-version <n>` to guard against stale UI state:

```bash
browse inspect
browse click target-123 --if-version 4
```

If the human changes the page in the meantime, the daemon returns a structured stale-state error instead of acting on an old assumption.

## Complex widget support

`browse` v0.2 includes a small composite layer for hostile UI widgets:
- `choose` for combobox/autocomplete flows
- `pick-date` for date fields and pickers
- `submit` for primary dialog/page actions

Composite failures are transparent: the JSON response includes the executed steps, the failure point, the active scope, and an inspect snapshot so the agent can recover with primitives.

## Skills

Install the bundled skills with:

```bash
browse install-skills
```

Installed locations:
- Claude: `~/.claude/skills/browse/SKILL.md`
- Codex: `~/.codex/skills/browse/`

The skills are explicit-use only. They are for direct browser verification requests, not general coding.

## Troubleshooting

### Browser executable missing

Install Google Chrome or Chromium in a standard macOS location such as `/Applications`, then rerun:

```bash
browse install
```

Or use the fallback:

```bash
browse install --bundled-chromium
```

### CDP connection refused

If the daemon cannot connect, start the browser first:

```bash
browse chrome
browse session start
```

### Invalid or missing config

```bash
browse config
```

### Login expired

Re-open the dedicated `browse` browser window and sign in again there:

```bash
browse chrome
```

### Chrome restarted

A daemon session does not survive Chrome restart. Start Chrome again, then restart the daemon session:

```bash
browse chrome
browse session start
```
