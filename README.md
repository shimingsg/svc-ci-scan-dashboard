# CI Scan Dashboard (Python)

## Run

1. `cd D:\mycopilot\ci-scan-dashboard`
2. `uv sync`
3. `uv run python app.py`
4. Open `http://127.0.0.1:8000`

## Notes

- Sync fetches `[ci-scan]` issues directly from GitHub (`dotnet/runtime`) and writes datasource JSON to `data\ci-scan-issues.json`.
- Analysis status and notes are saved in local SQLite: `data\issues.db`.
- Dashboard filters/view settings are saved to local JSON config: `data\dashboard-config.json`.
