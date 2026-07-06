import sqlite3
import time
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "proctoring.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                duration_seconds INTEGER NOT NULL,
                expires_at REAL NOT NULL,
                is_active INTEGER DEFAULT 1,
                questions TEXT
            )
        """)
        # Schema migration: Add questions column if table already exists without it
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN questions TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()

def create_session_db(session_id: str, duration_seconds: int):
    created_at = time.time()
    expires_at = created_at + duration_seconds
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, created_at, duration_seconds, expires_at, is_active) VALUES (?, ?, ?, ?, 1)",
            (session_id, created_at, duration_seconds, expires_at)
        )
        conn.commit()

def is_session_active(session_id: str) -> bool:
    now = time.time()
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT is_active, expires_at FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row:
                return row["is_active"] == 1 and row["expires_at"] > now
    except Exception as e:
        print(f"Error checking session status: {e}")
    return False

def get_session_duration(session_id: str) -> int:
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT duration_seconds FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row:
                return row["duration_seconds"]
    except Exception as e:
        print(f"Error getting session duration: {e}")
    return 3600

def get_session_questions(session_id: str) -> str:
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT questions FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row:
                return row["questions"]
    except Exception as e:
        print(f"Error getting session questions: {e}")
    return None

def save_session_questions(session_id: str, questions_json: str):
    try:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE sessions SET questions = ? WHERE session_id = ?",
                (questions_json, session_id)
            )
            conn.commit()
    except Exception as e:
        print(f"Error saving session questions: {e}")

def get_active_sessions_list():
    now = time.time()
    try:
        with get_db_connection() as conn:
            # Auto-delete expired sessions on query
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            conn.commit()
            
            rows = conn.execute(
                "SELECT session_id, created_at, duration_seconds, expires_at FROM sessions ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error fetching active sessions list: {e}")
        return []

def deactivate_session_db(session_id: str):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
    except Exception as e:
        print(f"Error deleting session: {e}")
