# CI Scan Dashboard (Python)

Local Flask dashboard for tracking `[ci-scan]` GitHub issues from `dotnet/runtime`.

## Features

- Sync `[ci-scan]` issues from GitHub into a local SQLite database.
- Configure the source GitHub repository and issue title prefix from the dashboard.
- Automatically mark issues closed as completed, duplicated, or not planned as analyzed with matching notes during sync.
- View issue title, state, created/updated timestamps, analysis status, and notes.
- Mark each issue as analyzed or pending.
- Add and save per-issue analysis notes locally.
- Collapse or expand issue notes, with pending issues expanded by default.
- Filter issues by:
  - analysis state: all, analyzed only, pending only
  - GitHub issue state: all, open, closed
  - one or more issue IDs, separated by commas
  - created date range
  - updated date range
- Sort by `createdAt` or `updatedAt`, newest or oldest first.
- Group visible issues by status or created date.
- Remember the last dashboard filters and display settings in local JSON config.
- Use an eye-friendly dark theme for long review sessions.

## Run

1. `cd ~\svc-ci-scan-dashboard`
2. `uv sync`
3. `uv run python app.py`
4. Open `http://127.0.0.1:8000`

## Local Data

- `data\<owner>_<repo>_issues.db` stores synced issue metadata, analysis status, and notes for each configured repo, for example `data\dotnet_runtime_issues.db`.
- `data\ci-scan-issues.json` stores the latest raw issue snapshot from GitHub sync.
- `data\dashboard-config.json` stores the last-used dashboard filters and display settings.
- `ci-scan-config.json` stores the configured GitHub repository and issue title prefix.

## Notes

- GitHub is the source for issue metadata.
- Local SQLite is the source for analysis status and notes.
- Local JSON config is the source for dashboard preferences.
- Root JSON config is the source for the GitHub repository and title prefix.
