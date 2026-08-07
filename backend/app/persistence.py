from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from campus_p2.contracts.p2 import P2ExamAnalysis


class P2SQLiteStore:
    """Small durable store for the local P2 demo service."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS exams (
                    exam_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    structure_json TEXT,
                    analysis_json TEXT,
                    warnings_json TEXT NOT NULL,
                    jobs_json TEXT,
                    p1_parse_json TEXT,
                    lesson_plans_json TEXT,
                    practice_packs_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exam_files (
                    file_id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    content BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS diagnostics (
                    diagnostic_id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "exams", "practice_packs_json", "TEXT")

    def load_all(self) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
        exams: dict[str, dict] = {}
        files: dict[str, dict] = {}
        diagnostics: dict[str, dict] = {}
        with self._connect() as conn:
            for row in conn.execute("SELECT * FROM exams"):
                analysis_payload = _loads(row["analysis_json"], None)
                exam = {
                    "exam_id": row["exam_id"],
                    "status": row["status"],
                    "payload": _loads(row["payload_json"], {}),
                    "files": _loads(row["files_json"], {}),
                    "analysis": P2ExamAnalysis.model_validate(analysis_payload) if analysis_payload else None,
                    "structure": _loads(row["structure_json"], None),
                    "warnings": _loads(row["warnings_json"], []),
                    "jobs": _loads(row["jobs_json"], []),
                    "p1_parse": _loads(row["p1_parse_json"], None),
                    "lesson_plans": _loads(row["lesson_plans_json"], {}),
                    "practice_packs": _loads(row["practice_packs_json"], []),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                exams[row["exam_id"]] = exam

            for row in conn.execute("SELECT * FROM exam_files"):
                files[row["file_id"]] = {
                    "exam_id": row["exam_id"],
                    "file_type": row["file_type"],
                    "metadata": _loads(row["metadata_json"], {}),
                    "content": bytes(row["content"]),
                    "created_at": row["created_at"],
                }

            for row in conn.execute("SELECT * FROM diagnostics"):
                diagnostics[row["diagnostic_id"]] = {
                    "exam_id": row["exam_id"],
                    "request": _loads(row["request_json"], {}),
                    "created_at": row["created_at"],
                }
        return exams, files, diagnostics

    def save_exam(self, exam: dict) -> None:
        now = _now()
        created_at = exam.get("created_at") or now
        exam["created_at"] = created_at
        exam["updated_at"] = now
        analysis = exam.get("analysis")
        analysis_payload = analysis.model_dump(mode="json") if isinstance(analysis, P2ExamAnalysis) else analysis
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO exams (
                    exam_id, status, payload_json, files_json, structure_json, analysis_json,
                    warnings_json, jobs_json, p1_parse_json, lesson_plans_json,
                    practice_packs_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exam_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    files_json=excluded.files_json,
                    structure_json=excluded.structure_json,
                    analysis_json=excluded.analysis_json,
                    warnings_json=excluded.warnings_json,
                    jobs_json=excluded.jobs_json,
                    p1_parse_json=excluded.p1_parse_json,
                    lesson_plans_json=excluded.lesson_plans_json,
                    practice_packs_json=excluded.practice_packs_json,
                    updated_at=excluded.updated_at
                """,
                (
                    exam["exam_id"],
                    exam.get("status", "draft"),
                    _dumps(exam.get("payload", {})),
                    _dumps(exam.get("files", {})),
                    _dumps(exam.get("structure")),
                    _dumps(analysis_payload),
                    _dumps(exam.get("warnings", [])),
                    _dumps(exam.get("jobs", [])),
                    _dumps(exam.get("p1_parse")),
                    _dumps(exam.get("lesson_plans", {})),
                    _dumps(exam.get("practice_packs", [])),
                    created_at,
                    now,
                ),
            )
        self.record_event("exam_saved", "exam", exam["exam_id"], {"status": exam.get("status", "draft")})

    def save_file(self, file_record: dict) -> None:
        metadata = file_record["metadata"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO exam_files (file_id, exam_id, file_type, metadata_json, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    metadata_json=excluded.metadata_json,
                    content=excluded.content
                """,
                (
                    metadata["file_id"],
                    file_record["exam_id"],
                    file_record["file_type"],
                    _dumps(metadata),
                    file_record["content"],
                    file_record.get("created_at") or _now(),
                ),
            )
        self.record_event(
            "file_saved",
            "file",
            metadata["file_id"],
            {"exam_id": file_record["exam_id"], "file_type": file_record["file_type"]},
        )

    def save_diagnostic(self, diagnostic_id: str, diagnostic: dict) -> None:
        created_at = diagnostic.get("created_at") or _now()
        diagnostic["created_at"] = created_at
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO diagnostics (diagnostic_id, exam_id, request_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(diagnostic_id) DO UPDATE SET request_json=excluded.request_json
                """,
                (
                    diagnostic_id,
                    diagnostic["exam_id"],
                    _dumps(diagnostic.get("request", {})),
                    created_at,
                ),
            )
        self.record_event("diagnostic_saved", "diagnostic", diagnostic_id, {"exam_id": diagnostic["exam_id"]})

    def delete_exam(self, exam_id: str, *, file_ids: list[str] | None = None, diagnostic_ids: list[str] | None = None) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM exams WHERE exam_id = ?", (exam_id,))
            if file_ids:
                placeholders = ",".join("?" for _ in file_ids)
                conn.execute(f"DELETE FROM exam_files WHERE file_id IN ({placeholders})", tuple(file_ids))
            conn.execute("DELETE FROM diagnostics WHERE exam_id = ?", (exam_id,))

    def record_event(self, event: str, resource_type: str, resource_id: str, payload: dict | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (event, resource_type, resource_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event, resource_type, resource_id, _dumps(payload or {}), _now()),
            )

    def list_events(
        self,
        *,
        limit: int = 50,
        event: str = "",
        resource_type: str = "",
        resource_id: str = "",
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        clauses = []
        params: list[Any] = []
        if event:
            clauses.append("event = ?")
            params.append(event)
        if resource_type:
            clauses.append("resource_type = ?")
            params.append(resource_type)
        if resource_id:
            clauses.append("resource_id = ?")
            params.append(resource_id)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, event, resource_type, resource_id, payload_json, created_at
                FROM audit_logs
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event": row["event"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "payload": _loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def now(self) -> str:
        return _now()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
