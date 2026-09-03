# BookMyShow Telegram Watcher — GitHub Actions architecture

## Architecture

- `bot.py` runs on Render and handles Telegram commands/UI.
- `bms_api.py` contains the existing BookMyShow request/parser logic.
- `data/watches.json` is the persistent watch database.
- `data/watcher_state.json` stores polling state/statistics.
- `github_checker.py` runs in GitHub Actions and is the only component that polls BookMyShow.
- Telegram alerts are sent directly from GitHub Actions using the same bot token.

The first check after a watch is created only initializes its state. It does not send an alert for shows that were already available when monitoring began.

## Render environment variables

Set these on the Render bot service:

- `TELEGRAM_BOT_TOKEN` — your existing Telegram bot token
- `GITHUB_REPO` — repository in `owner/repository` form
- `GITHUB_TOKEN` — a GitHub token with permission to read/write repository contents
- Optional: `GITHUB_BRANCH` (default `main`)
- Optional: `GITHUB_WATCHES_PATH` (default `data/watches.json`)
- Optional: `GITHUB_STATE_PATH` (default `data/watcher_state.json`)
- `PORT` is supplied by Render

Do not put the GitHub token or Telegram token in the repository.

## GitHub Actions secret

In the repository, add:

- `TELEGRAM_BOT_TOKEN`

The workflow uses the built-in `GITHUB_TOKEN` to commit `data/watcher_state.json`, so no personal GitHub token is needed inside Actions.

Also ensure repository Actions have permission to write contents. The workflow declares:

```yaml
permissions:
  contents: write
```

## Render start command

```bash
python bot.py
```

## GitHub Actions

`.github/workflows/bms-watcher.yml` runs approximately every five minutes and can also be started manually with **Run workflow**.

GitHub scheduled workflows are not guaranteed to start at exactly `:00`, `:05`, `:10`, etc.; occasional delays are normal.

## Commands

Existing bot commands remain available, including `/start`, `/watches`, `/stop`, and `/cancel`.

Watches are persistent after an alert. Stop one explicitly with:

```text
/stop WATCH_ID
```
