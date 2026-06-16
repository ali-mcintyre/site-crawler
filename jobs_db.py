"""
jobs_db.py
==========
Lightweight SQLite persistence for crawl jobs so job history and
status survive server restarts. Excel output is saved to disk
(results/<job_id>.xlsx) rather than kept in memory.
"""

import json
import os
import sqlite3
import threading
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                mode TEXT,
                url TEXT,
                filename TEXT,
                status TEXT,
                progress INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                log TEXT DEFAULT '[]',
                error TEXT,
                excel TEXT,
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.commit()


def create_job(job_id: str, mode: str, url: str, filename: str):
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO jobs (id, mode, url, filename, status, progress, total,
                                  log, error, excel, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'Queued', 0, 0, '[]', NULL, NULL, ?, ?)""",
            (job_id, mode, url, filename, now, now),
        )
        conn.commit()


def update_job(job_id: str, **fields):
    """Update arbitrary columns, e.g. update_job(id, status='Crawling', progress=5)."""
    if not fields:
        return
    if "log" in fields and not isinstance(fields["log"], str):
        fields["log"] = json.dumps(fields["log"])
    fields["updated_at"] = time.time()

    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with _lock, _connect() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)
        conn.commit()


def save_excel(job_id: str, excel_bytes: bytes, filename: str) -> str:
    """save excel bytes."""
    # path = os.path.join(RESULTS_DIR, f"{job_id}.xlsx")
    # with open(path, "wb") as f:
    #     f.write(excel_bytes)
    update_job(job_id, excel=excel_bytes, filename=filename)
    # return path


def get_job(job_id: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["log"] = json.loads(job["log"] or "[]")
    return job


def show_jobs(status_in: list[str] = None) -> list[dict]:
    """List jobs, optionally filtered by status, newest first."""
    with _lock, _connect() as conn:
        if status_in:
            placeholders = ",".join("?" * len(status_in))
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at DESC",
                status_in,
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        job["log"] = json.loads(job["log"] or "[]")
        jobs.append(job)
    return jobs


def delete_job(job_id: str):
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def mark_interrupted_jobs_on_startup():
    """Any job left 'queued'/'crawling'/etc. from a previous process is now dead."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE jobs SET status = 'interrupted', updated_at = ?
               WHERE status NOT IN ('Done', 'Error', 'Stopped', 'Interrupted')""",
            (time.time(),),
        )
        conn.commit()