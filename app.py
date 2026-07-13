import json
import logging
import shutil
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, render_template, request

logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LEGACY_DB_PATH = DATA_DIR / "issues.db"
DATASOURCE_FILE = DATA_DIR / "ci-scan-issues.json"
DASHBOARD_CONFIG_FILE = DATA_DIR / "dashboard-config.json"
PROJECT_CONFIG_FILE = BASE_DIR / "ci-scan-config.json"

app = Flask(__name__)

DEFAULT_DASHBOARD_CONFIG = {
    "view": "all",
    "state": "all",
    "issueIds": "",
    "sortBy": "createdAt",
    "sortDir": "desc",
    "groupBy": "none",
    "showNoteByDefault": False,
    "issueFiltersExpanded": True,
    "dateFiltersExpanded": False,
    "createdFrom": "",
    "createdTo": "",
    "updatedFrom": "",
    "updatedTo": "",
}

DEFAULT_PROJECT_CONFIG = {
    "repo": "dotnet/runtime",
    "titlePrefix": "[ci-scan]",
}


def get_repo_db_path(repo: str) -> Path:
    safe_repo = repo.replace("/", "_")
    return DATA_DIR / f"{safe_repo}_issues.db"


def get_connection(repo: str | None = None) -> sqlite3.Connection:
    project_config = load_project_config() if repo is None else {"repo": repo}
    conn = sqlite3.connect(get_repo_db_path(project_config["repo"]))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(repo: str | None = None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    project_config = load_project_config() if repo is None else {"repo": repo}
    db_path = get_repo_db_path(project_config["repo"])
    if (
        project_config["repo"] == DEFAULT_PROJECT_CONFIG["repo"]
        and LEGACY_DB_PATH.exists()
        and not db_path.exists()
    ):
        shutil.copy2(LEGACY_DB_PATH, db_path)
    with get_connection(project_config["repo"]) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS issues (
                id            INTEGER PRIMARY KEY,
                number        INTEGER NOT NULL,
                title         TEXT    NOT NULL,
                state         TEXT    NOT NULL,
                url           TEXT    NOT NULL,
                created_at    TEXT    NOT NULL,
                updated_at    TEXT    NOT NULL,
                analyzed_done INTEGER NOT NULL DEFAULT 0,
                note          TEXT    NOT NULL DEFAULT '',
                source_repo   TEXT    NOT NULL DEFAULT 'dotnet/runtime',
                title_prefix  TEXT    NOT NULL DEFAULT '[ci-scan]'
            )
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(issues)").fetchall()
        }
        if "source_repo" not in columns:
            conn.execute(
                "ALTER TABLE issues ADD COLUMN source_repo TEXT NOT NULL DEFAULT 'dotnet/runtime'"
            )
        if "title_prefix" not in columns:
            conn.execute(
                "ALTER TABLE issues ADD COLUMN title_prefix TEXT NOT NULL DEFAULT '[ci-scan]'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_issues_analyzed_done ON issues(analyzed_done)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_state ON issues(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_source ON issues(source_repo, title_prefix)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_created_at ON issues(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_updated_at ON issues(updated_at)")


def normalize_project_config(raw: dict) -> dict:
    normalized = dict(DEFAULT_PROJECT_CONFIG)

    repo = raw.get("repo", normalized["repo"])
    if isinstance(repo, str):
        repo = repo.strip()
        parts = repo.split("/")
        if (
            len(parts) == 2
            and all(part for part in parts)
            and all(part.replace("-", "").replace("_", "").replace(".", "").isalnum() for part in parts)
        ):
            normalized["repo"] = repo

    title_prefix = raw.get("titlePrefix", normalized["titlePrefix"])
    if isinstance(title_prefix, str) and title_prefix.strip():
        normalized["titlePrefix"] = title_prefix.strip()

    return normalized


def load_project_config() -> dict:
    if not PROJECT_CONFIG_FILE.exists():
        return dict(DEFAULT_PROJECT_CONFIG)

    raw = PROJECT_CONFIG_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return dict(DEFAULT_PROJECT_CONFIG)

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("project config must be a JSON object")

    return normalize_project_config(data)


def save_project_config(config: dict) -> None:
    PROJECT_CONFIG_FILE.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )


def init_project_config() -> None:
    if not PROJECT_CONFIG_FILE.exists():
        save_project_config(dict(DEFAULT_PROJECT_CONFIG))


def get_auto_analysis_note(row: dict) -> str:
    if row.get("state") != "closed":
        return ""

    close_reason = str(row.get("stateReason") or "").lower()
    if close_reason == "completed":
        return "completed"
    if close_reason in {"duplicate", "duplicated"}:
        return "duplicated"
    if close_reason == "not_planned":
        return "Closed as not planned"

    return ""


def fetch_github_ci_scan_issues(project_config: dict) -> list[dict]:
    repo = project_config["repo"]
    title_prefix = project_config["titlePrefix"]
    query = f'repo:{repo} is:issue in:title "{title_prefix}"'
    page = 1
    per_page = 100
    by_id: dict[int, dict] = {}

    while True:
        params = urllib.parse.urlencode(
            {"q": query, "per_page": per_page, "page": page}
        )
        req = urllib.request.Request(
            f"https://api.github.com/search/issues?{params}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "ci-scan-dashboard",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        items = payload.get("items")
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if not isinstance(title, str) or not title.startswith(title_prefix):
                continue
            issue_id = item.get("id")
            number = item.get("number")
            if not isinstance(issue_id, int) or not isinstance(number, int):
                continue

            by_id[issue_id] = {
                "id": issue_id,
                "number": number,
                "title": title,
                "state": item.get("state", ""),
                "url": item.get("html_url", ""),
                "createdAt": item.get("created_at", ""),
                "updatedAt": item.get("updated_at", ""),
                "stateReason": item.get("state_reason", ""),
            }

        if len(items) < per_page:
            break
        page += 1

    return sorted(by_id.values(), key=lambda row: row["number"], reverse=True)


def save_datasource(rows: list[dict]) -> None:
    DATASOURCE_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def normalize_dashboard_config(raw: dict) -> dict:
    normalized = dict(DEFAULT_DASHBOARD_CONFIG)

    def _pick(key: str, allowed: set) -> object:
        val = raw.get(key)
        return val if val in allowed else normalized[key]

    normalized["view"] = _pick("view", {"all", "analyzed", "pending"})
    normalized["state"] = _pick("state", {"all", "open", "closed"})
    normalized["sortBy"] = _pick("sortBy", {"createdAt", "updatedAt"})
    normalized["sortDir"] = _pick("sortDir", {"asc", "desc"})
    normalized["groupBy"] = _pick("groupBy", {"none", "status", "createdAt"})
    normalized["showNoteByDefault"] = bool(raw.get("showNoteByDefault", normalized["showNoteByDefault"]))
    normalized["issueFiltersExpanded"] = bool(raw.get("issueFiltersExpanded", normalized["issueFiltersExpanded"]))
    normalized["dateFiltersExpanded"] = bool(raw.get("dateFiltersExpanded", normalized["dateFiltersExpanded"]))

    for key in ["issueIds", "createdFrom", "createdTo", "updatedFrom", "updatedTo"]:
        value = raw.get(key, normalized[key])
        normalized[key] = value if isinstance(value, str) else ""

    return normalized


def parse_issue_numbers(raw: str | None) -> list[int]:
    if not raw:
        return []

    issue_numbers: list[int] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        if not value.isdecimal():
            raise ValueError("issue IDs must be numbers separated by commas")
        issue_numbers.append(int(value))

    return issue_numbers


def load_dashboard_config() -> dict:
    if not DASHBOARD_CONFIG_FILE.exists():
        return dict(DEFAULT_DASHBOARD_CONFIG)

    raw = DASHBOARD_CONFIG_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return dict(DEFAULT_DASHBOARD_CONFIG)

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("dashboard config must be a JSON object")

    return normalize_dashboard_config(data)


def save_dashboard_config(config: dict) -> None:
    DASHBOARD_CONFIG_FILE.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )


def sync_issues() -> int:
    project_config = load_project_config()
    rows = fetch_github_ci_scan_issues(project_config)
    save_datasource(rows)

    with get_connection() as conn:
        for row in rows:
            auto_note = get_auto_analysis_note(row)
            conn.execute(
                """
                INSERT INTO issues (
                    id, number, title, state, url, created_at, updated_at,
                    analyzed_done, note, source_repo, title_prefix
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    number = excluded.number,
                    title = excluded.title,
                    state = excluded.state,
                    url = excluded.url,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    source_repo = excluded.source_repo,
                    title_prefix = excluded.title_prefix,
                    analyzed_done = CASE
                        WHEN excluded.analyzed_done = 1 THEN 1
                        ELSE issues.analyzed_done
                    END,
                    note = CASE
                        WHEN excluded.analyzed_done = 1 THEN excluded.note
                        ELSE issues.note
                    END
                """,
                (
                    row["id"],
                    row["number"],
                    row["title"],
                    row["state"],
                    row["url"],
                    row["createdAt"],
                    row["updatedAt"],
                    1 if auto_note else 0,
                    auto_note,
                    project_config["repo"],
                    project_config["titlePrefix"],
                ),
            )

        total = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM issues
            WHERE source_repo = ? AND title_prefix = ?
            """,
            (project_config["repo"], project_config["titlePrefix"]),
        ).fetchone()["c"]
        return int(total)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/issues")
def get_issues():
    project_config = load_project_config()
    view = request.args.get("view", "all")
    issue_state = request.args.get("state", "all")
    issue_ids = request.args.get("issueIds")
    sort_by = request.args.get("sortBy", "createdAt")
    sort_dir = request.args.get("sortDir", "desc")
    created_from = request.args.get("createdFrom")
    created_to = request.args.get("createdTo")
    updated_from = request.args.get("updatedFrom")
    updated_to = request.args.get("updatedTo")

    clauses: list[str] = ["source_repo = ?", "title_prefix = ?"]
    params: list[str] = [project_config["repo"], project_config["titlePrefix"]]
    try:
        issue_numbers = parse_issue_numbers(issue_ids)
    except ValueError as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400

    if view == "analyzed":
        clauses.append("analyzed_done = 1")
    if view == "pending":
        clauses.append("analyzed_done = 0")
    if issue_state in {"open", "closed"}:
        clauses.append("state = ?")
        params.append(issue_state)
    if issue_numbers:
        clauses.append(f"number IN ({', '.join('?' for _ in issue_numbers)})")
        params.extend(str(n) for n in issue_numbers)
    if created_from:
        clauses.append("datetime(created_at) >= datetime(?)")
        params.append(created_from)
    if created_to:
        clauses.append("datetime(created_at) <= datetime(?)")
        params.append(created_to)
    if updated_from:
        clauses.append("datetime(updated_at) >= datetime(?)")
        params.append(updated_from)
    if updated_to:
        clauses.append("datetime(updated_at) <= datetime(?)")
        params.append(updated_to)

    where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
    col = "updated_at" if sort_by == "updatedAt" else "created_at"
    direction = "ASC" if sort_dir == "asc" else "DESC"
    order_clause = f"ORDER BY datetime({col}) {direction}, number {direction}"

    sql = (
        "SELECT id, number, title, state, url, created_at, updated_at, analyzed_done, note"
        " FROM issues"
        f" {where_clause}"
        f" {order_clause}"
    )

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify(
        [
            {
                "id": r["id"],
                "number": r["number"],
                "title": r["title"],
                "state": r["state"],
                "url": r["url"],
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
                "analyzedDone": bool(r["analyzed_done"]),
                "note": r["note"],
            }
            for r in rows
        ]
    )


@app.get("/api/summary")
def get_summary():
    project_config = load_project_config()
    with get_connection() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN analyzed_done = 1 THEN 1 ELSE 0 END) AS analyzed,
                SUM(CASE WHEN analyzed_done = 0 THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN state = 'open' THEN 1 ELSE 0 END) AS open,
                SUM(CASE WHEN state = 'closed' THEN 1 ELSE 0 END) AS closed,
                SUM(CASE WHEN analyzed_done = 1 AND state = 'open' THEN 1 ELSE 0 END) AS analyzed_open,
                SUM(CASE WHEN analyzed_done = 1 AND state = 'closed' THEN 1 ELSE 0 END) AS analyzed_closed,
                SUM(CASE WHEN analyzed_done = 0 AND state = 'open' THEN 1 ELSE 0 END) AS pending_open,
                SUM(CASE WHEN analyzed_done = 0 AND state = 'closed' THEN 1 ELSE 0 END) AS pending_closed
            FROM issues
            WHERE source_repo = ? AND title_prefix = ?
            """,
            (project_config["repo"], project_config["titlePrefix"]),
        ).fetchone()

    total = int(totals["total"] or 0)
    analyzed = int(totals["analyzed"] or 0)
    return jsonify(
        {
            "total": total,
            "analyzed": analyzed,
            "pending": int(totals["pending"] or 0),
            "open": int(totals["open"] or 0),
            "closed": int(totals["closed"] or 0),
            "analyzedOpen": int(totals["analyzed_open"] or 0),
            "analyzedClosed": int(totals["analyzed_closed"] or 0),
            "pendingOpen": int(totals["pending_open"] or 0),
            "pendingClosed": int(totals["pending_closed"] or 0),
        }
    )


@app.get("/api/config")
def get_config():
    try:
        config = load_dashboard_config()
    except (json.JSONDecodeError, ValueError) as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400
    return jsonify({"ok": True, "config": config})


@app.get("/api/project-config")
def get_project_config():
    try:
        config = load_project_config()
    except (json.JSONDecodeError, ValueError) as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400
    return jsonify({"ok": True, "config": config})


@app.post("/api/project-config")
def post_project_config():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "project config payload must be an object"}), 400

    config = normalize_project_config(payload)
    save_project_config(config)
    init_db(config["repo"])
    return jsonify({"ok": True, "config": config})


@app.post("/api/config")
def post_config():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "config payload must be an object"}), 400

    config = normalize_dashboard_config(payload)
    save_dashboard_config(config)
    return jsonify({"ok": True, "config": config})


@app.post("/api/sync")
def post_sync():
    try:
        count = sync_issues()
        return jsonify({"ok": True, "count": count})
    except urllib.error.HTTPError as ex:
        logger.exception("GitHub API error during sync")
        return jsonify({"ok": False, "error": f"GitHub API error {ex.code}: {ex.reason}"}), 502
    except urllib.error.URLError as ex:
        logger.exception("Network error during sync")
        return jsonify({"ok": False, "error": f"Network error: {ex.reason}"}), 502
    except Exception as ex:
        logger.exception("Unexpected error during sync")
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.post("/api/issues/<int:issue_id>/analysis")
def post_analysis(issue_id: int):
    payload = request.get_json(silent=True) or {}
    analyzed_done = 1 if payload.get("analyzedDone", False) else 0
    note = payload.get("note", "")
    if not isinstance(note, str):
        return jsonify({"ok": False, "error": "note must be a string"}), 400

    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE issues
            SET analyzed_done = ?, note = ?
            WHERE id = ?
            """,
            (analyzed_done, note.strip(), issue_id),
        )
        if cur.rowcount == 0:
            return jsonify({"ok": False, "error": "issue not found"}), 404

    return jsonify({"ok": True})


init_project_config()
init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
