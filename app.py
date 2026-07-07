import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "issues.db"
DATASOURCE_FILE = DATA_DIR / "ci-scan-issues.json"
CONFIG_FILE = DATA_DIR / "dashboard-config.json"
REPO_OWNER = "dotnet"
REPO_NAME = "runtime"
TITLE_PREFIX = "[ci-scan]"

app = Flask(__name__)

DEFAULT_DASHBOARD_CONFIG = {
    "view": "all",
    "state": "all",
    "sortBy": "createdAt",
    "sortDir": "desc",
    "groupBy": "none",
    "showNoteByDefault": False,
    "createdFrom": "",
    "createdTo": "",
    "updatedFrom": "",
    "updatedTo": "",
}


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
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
                note          TEXT    NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_issues_analyzed_done ON issues(analyzed_done)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_state ON issues(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_created_at ON issues(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_issues_updated_at ON issues(updated_at)")


def fetch_github_ci_scan_issues() -> list[dict]:
    query = f'repo:{REPO_OWNER}/{REPO_NAME} is:issue in:title "{TITLE_PREFIX}"'
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
            if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
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
                "analyzedDone": False,
                "note": "",
            }

        if len(items) < per_page:
            break
        page += 1

    return sorted(by_id.values(), key=lambda row: row["number"], reverse=True)


def save_datasource(rows: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATASOURCE_FILE.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def normalize_dashboard_config(raw: dict) -> dict:
    normalized = dict(DEFAULT_DASHBOARD_CONFIG)
    normalized["view"] = raw.get("view") if raw.get("view") in {"all", "analyzed", "pending"} else normalized["view"]
    normalized["state"] = raw.get("state") if raw.get("state") in {"all", "open", "closed"} else normalized["state"]
    normalized["sortBy"] = raw.get("sortBy") if raw.get("sortBy") in {"createdAt", "updatedAt"} else normalized["sortBy"]
    normalized["sortDir"] = raw.get("sortDir") if raw.get("sortDir") in {"asc", "desc"} else normalized["sortDir"]
    normalized["groupBy"] = raw.get("groupBy") if raw.get("groupBy") in {"none", "status", "createdAt"} else normalized["groupBy"]
    normalized["showNoteByDefault"] = bool(raw.get("showNoteByDefault", normalized["showNoteByDefault"]))

    for key in ["createdFrom", "createdTo", "updatedFrom", "updatedTo"]:
        value = raw.get(key, normalized[key])
        normalized[key] = value if isinstance(value, str) else ""

    return normalized


def load_dashboard_config() -> dict:
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_DASHBOARD_CONFIG)

    raw = CONFIG_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return dict(DEFAULT_DASHBOARD_CONFIG)

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("dashboard config must be a JSON object")

    return normalize_dashboard_config(data)


def save_dashboard_config(config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )


def sync_issues() -> int:
    rows = fetch_github_ci_scan_issues()
    save_datasource(rows)

    with get_connection() as conn:
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = row.get("title")
            if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
                continue

            issue_id = row.get("id")
            number = row.get("number")
            state = row.get("state", "")
            url = row.get("url", "")
            updated_at = row.get("updatedAt", "")
            created_at = row.get("createdAt", row.get("created_at", updated_at))
            analyzed_done = 1 if row.get("analyzedDone", False) else 0
            note = row.get("note", "")

            if not isinstance(issue_id, int) or not isinstance(number, int):
                continue

            conn.execute(
                """
                INSERT INTO issues (
                    id, number, title, state, url, created_at, updated_at, analyzed_done, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    number = excluded.number,
                    title = excluded.title,
                    state = excluded.state,
                    url = excluded.url,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    analyzed_done = issues.analyzed_done,
                    note = issues.note
                """,
                (
                    issue_id,
                    number,
                    title,
                    state,
                    url,
                    created_at,
                    updated_at,
                    analyzed_done,
                    note,
                ),
            )

        total = conn.execute("SELECT COUNT(*) AS c FROM issues").fetchone()["c"]
        return int(total)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/issues")
def get_issues():
    view = request.args.get("view", "all")
    issue_state = request.args.get("state", "all")
    sort_by = request.args.get("sortBy", "createdAt")
    sort_dir = request.args.get("sortDir", "desc")
    created_from = request.args.get("createdFrom")
    created_to = request.args.get("createdTo")
    updated_from = request.args.get("updatedFrom")
    updated_to = request.args.get("updatedTo")

    clauses: list[str] = []
    params: list[str] = []
    if view == "analyzed":
        clauses.append("analyzed_done = 1")
    if view == "pending":
        clauses.append("analyzed_done = 0")
    if issue_state in {"open", "closed"}:
        clauses.append("state = ?")
        params.append(issue_state)
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

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    col = "updated_at" if sort_by == "updatedAt" else "created_at"
    direction = "ASC" if sort_dir == "asc" else "DESC"
    order_clause = f"ORDER BY datetime({col}) {direction}, number {direction}"

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, number, title, state, url, created_at, updated_at, analyzed_done, note
            FROM issues
            """
            + where_clause
            + """
            """
            + order_clause
            + """
            """,
            params,
        ).fetchall()

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
    with get_connection() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN analyzed_done = 1 THEN 1 ELSE 0 END) AS analyzed
            FROM issues
            """
        ).fetchone()

    total = int(totals["total"] or 0)
    analyzed = int(totals["analyzed"] or 0)
    return jsonify({"total": total, "analyzed": analyzed})


@app.get("/api/config")
def get_config():
    try:
        config = load_dashboard_config()
    except (json.JSONDecodeError, ValueError) as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400
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
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 400


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


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8000, debug=True)
