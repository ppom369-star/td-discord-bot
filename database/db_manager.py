import sqlite3
import os
import sys
import shutil
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

BANGKOK_TZ = timezone(timedelta(hours=7))

def get_bangkok_now() -> datetime:
    return datetime.now(BANGKOK_TZ)

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bot_data.db"))
)

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")) and psycopg is not None)

def configure_sqlite(conn: sqlite3.Connection):
    try:
        conn.execute("PRAGMA journal_mode = MEMORY;")
    except Exception:
        try:
            conn.execute("PRAGMA journal_mode = TRUNCATE;")
        except Exception:
            pass
    try:
        conn.execute("PRAGMA temp_store = 2;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass

class PostgresCursorWrapper:
    ID_TABLES = {"todos", "reminders", "rss_feeds", "memos", "transactions", "stream_trackers", "youtube_subscriptions", "ai_chat_history", "youtube_seen_videos"}

    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None

    def execute(self, query, params=None):
        pg_query = query.replace("?", "%s")
        words = pg_query.strip().split()
        is_insert = len(words) >= 3 and words[0].upper() == "INSERT" and words[1].upper() == "INTO"
        table_name = words[2].strip('"().,;').lower() if is_insert else ""

        needs_returning = is_insert and table_name in self.ID_TABLES and "RETURNING" not in pg_query.upper()
        if needs_returning:
            pg_query = pg_query.rstrip().rstrip(";") + " RETURNING id;"

        if params is not None:
            self._cur.execute(pg_query, params)
        else:
            self._cur.execute(pg_query)

        if needs_returning:
            try:
                row = self._cur.fetchone()
                if row and "id" in row:
                    self.lastrowid = row["id"]
            except Exception:
                pass
        return self

    def executemany(self, query, params_seq):
        pg_query = query.replace("?", "%s")
        self._cur.executemany(pg_query, params_seq)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

_PG_CONN = None

def get_live_postgres_connection():
    global _PG_CONN
    if _PG_CONN is not None:
        try:
            if not _PG_CONN.closed:
                return _PG_CONN
        except Exception:
            pass
    _PG_CONN = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    return _PG_CONN

@contextmanager
def get_connection():
    if USE_POSTGRES:
        conn = get_live_postgres_connection()
        wrapped = PostgresConnectionWrapper(conn)
        try:
            yield wrapped
            wrapped.commit()
        except (psycopg.OperationalError, psycopg.DatabaseError) as err:
            wrapped.rollback()
            global _PG_CONN
            try:
                if _PG_CONN:
                    _PG_CONN.close()
            except Exception:
                pass
            _PG_CONN = None
            print(f"[DB ERROR] Connection reset on PostgreSQL: {err}", file=sys.stderr, flush=True)
            raise
        except Exception as err:
            wrapped.rollback()
            print(f"[DB ERROR] Query failed on PostgreSQL: {err}", file=sys.stderr, flush=True)
            raise
    else:
        conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        configure_sqlite(conn)
        try:
            yield conn
            conn.commit()
        except Exception as err:
            conn.rollback()
            print(f"[DB ERROR] Query failed on {DATABASE_PATH}: {err}", file=sys.stderr, flush=True)
            raise
        finally:
            conn.close()

get_db = get_connection

def get_database_diagnostics() -> dict:
    if USE_POSTGRES:
        write_ok = False
        write_err = None
        counts = {}
        try:
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("CREATE TABLE IF NOT EXISTS _diag_test (id BIGINT PRIMARY KEY);")
                c.execute("INSERT INTO _diag_test VALUES (1) ON CONFLICT (id) DO NOTHING;")
                conn.commit()
                write_ok = True
                for tbl in ["todos", "reminders", "transactions", "pomodoro_sessions", "settings"]:
                    try:
                        c.execute(f"SELECT COUNT(*) FROM {tbl}")
                        res = c.fetchone()
                        if isinstance(res, dict):
                            counts[tbl] = res.get("count") or list(res.values())[0]
                        else:
                            counts[tbl] = res[0]
                    except Exception:
                        counts[tbl] = "N/A"
        except Exception as e:
            write_err = str(e)

        return {
            "path": "Supabase PostgreSQL (Cloud)",
            "size_kb": "Cloud Managed",
            "disk": "Managed Cloud Storage",
            "write_ok": write_ok,
            "write_error": write_err,
            "counts": counts
        }

    db_dir = os.path.dirname(DATABASE_PATH) or "."
    try:
        total, used, free = shutil.disk_usage(db_dir)
        disk_str = f"Free {free / (1024*1024):.1f} MB / Total {total / (1024*1024):.1f} MB"
    except Exception as e:
        disk_str = f"Unknown ({e})"

    db_size = os.path.getsize(DATABASE_PATH) / 1024 if os.path.exists(DATABASE_PATH) else 0

    write_ok = False
    write_err = None
    try:
        with get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS _diag_test (id INTEGER PRIMARY KEY);")
            conn.execute("INSERT OR REPLACE INTO _diag_test VALUES (1);")
            conn.commit()
            write_ok = True
    except Exception as e:
        write_err = str(e)

    counts = {}
    try:
        with get_connection() as conn:
            c = conn.cursor()
            for tbl in ["todos", "reminders", "transactions", "pomodoro_sessions", "settings"]:
                try:
                    c.execute(f"SELECT COUNT(*) FROM {tbl}")
                    counts[tbl] = c.fetchone()[0]
                except Exception:
                    counts[tbl] = "N/A"
    except Exception:
        pass

    return {
        "path": DATABASE_PATH,
        "size_kb": f"{db_size:.1f} KB",
        "disk": disk_str,
        "write_ok": write_ok,
        "write_error": write_err,
        "counts": counts
    }

def init_db():
    if USE_POSTGRES:
        pg_tables = [
            """CREATE TABLE IF NOT EXISTS todos (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS reminders (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                message TEXT NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0
            );""",
            """CREATE TABLE IF NOT EXISTS rss_feeds (
                id BIGSERIAL PRIMARY KEY,
                feed_url TEXT UNIQUE NOT NULL,
                channel_id BIGINT NOT NULL,
                last_entry_id TEXT,
                title TEXT
            );""",
            """CREATE TABLE IF NOT EXISTS memos (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );""",
            """CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                user_id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                mode TEXT NOT NULL,
                end_time TIMESTAMP NOT NULL,
                work_min INTEGER NOT NULL,
                break_min INTEGER NOT NULL,
                cycles_done INTEGER NOT NULL DEFAULT 0,
                target_cycles INTEGER NOT NULL DEFAULT 4
            );""",
            """CREATE TABLE IF NOT EXISTS transactions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                type TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                category TEXT NOT NULL,
                note TEXT,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS stream_trackers (
                id BIGSERIAL PRIMARY KEY,
                platform TEXT NOT NULL DEFAULT 'twitch',
                channel_login TEXT NOT NULL,
                display_name TEXT,
                destination_channel_id BIGINT NOT NULL,
                last_stream_id TEXT,
                is_live INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform, channel_login)
            );""",
            """CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id BIGINT PRIMARY KEY,
                youtube_channel_id TEXT NOT NULL,
                ping_role_id BIGINT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS youtube_subscriptions (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                youtube_channel_id TEXT NOT NULL,
                channel_title TEXT,
                last_video_id TEXT,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, youtube_channel_id)
            );""",
            """CREATE TABLE IF NOT EXISTS ai_chat_history (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );""",
            """CREATE INDEX IF NOT EXISTS idx_ai_chat_user ON ai_chat_history(user_id, created_at);""",
            """CREATE TABLE IF NOT EXISTS youtube_seen_videos (
                id BIGSERIAL PRIMARY KEY,
                subscription_id BIGINT NOT NULL,
                video_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subscription_id, video_id)
            );""",
            """CREATE INDEX IF NOT EXISTS idx_youtube_seen_sub ON youtube_seen_videos(subscription_id, video_id);"""
        ]
        with get_connection() as conn:
            cur = conn.cursor()
            for stmt in pg_tables:
                cur.execute(stmt)
            conn.commit()
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_url TEXT UNIQUE NOT NULL,
                channel_id INTEGER NOT NULL,
                last_entry_id TEXT,
                title TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                user_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                end_time TIMESTAMP NOT NULL,
                work_min INTEGER NOT NULL,
                break_min INTEGER NOT NULL,
                cycles_done INTEGER NOT NULL DEFAULT 0,
                target_cycles INTEGER NOT NULL DEFAULT 4
            )
        """)
        try:
            cursor.execute("ALTER TABLE pomodoro_sessions ADD COLUMN target_cycles INTEGER NOT NULL DEFAULT 4")
        except Exception:
            pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                note TEXT,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stream_trackers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'twitch',
                channel_login TEXT NOT NULL,
                display_name TEXT,
                destination_channel_id INTEGER NOT NULL,
                last_stream_id TEXT,
                is_live INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform, channel_login)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                youtube_channel_id INTEGER NOT NULL,
                ping_role_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS youtube_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                youtube_channel_id TEXT NOT NULL,
                channel_title TEXT,
                last_video_id TEXT,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, youtube_channel_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS youtube_seen_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subscription_id, video_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_seen_sub ON youtube_seen_videos(subscription_id, video_id);")
        cursor.execute("PRAGMA table_info(youtube_subscriptions)")
        cols = [row[1] for row in cursor.fetchall()]
        if "avatar_url" not in cols:
            try:
                cursor.execute("ALTER TABLE youtube_subscriptions ADD COLUMN avatar_url TEXT")
            except Exception:
                pass
        conn.commit()

def add_todo(user_id: int, task: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO todos (user_id, task, status) VALUES (?, ?, 'pending')",
            (user_id, task)
        )
        conn.commit()
        return cursor.lastrowid

def get_todos(user_id: int, status: str = None) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM todos WHERE user_id = ? AND status = ? ORDER BY id DESC",
                (user_id, status)
            )
        else:
            cursor.execute(
                "SELECT * FROM todos WHERE user_id = ? ORDER BY status DESC, id DESC",
                (user_id,)
            )
        return [dict(row) for row in cursor.fetchall()]

def mark_todo_done(todo_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE todos SET status = 'done' WHERE id = ? AND user_id = ?",
            (todo_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def delete_todo(todo_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM todos WHERE id = ? AND user_id = ?",
            (todo_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def add_reminder(user_id: int, channel_id: int, message: str = "", remind_at: datetime = None, due_time: datetime = None) -> int:
    target_time = remind_at or due_time
    if isinstance(message, datetime) and (isinstance(remind_at, str) or isinstance(due_time, str)):
        message, target_time = target_time, message
    if not isinstance(target_time, datetime):
        target_time = get_bangkok_now()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (user_id, channel_id, message, remind_at, is_sent) VALUES (?, ?, ?, ?, 0)",
            (user_id, channel_id, str(message), target_time.isoformat())
        )
        conn.commit()
        return cursor.lastrowid

def get_due_reminders() -> list:
    now_iso = get_bangkok_now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reminders WHERE is_sent = 0 AND remind_at <= ?",
            (now_iso,)
        )
        return [dict(row) for row in cursor.fetchall()]

def mark_reminder_sent(reminder_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reminders SET is_sent = 1 WHERE id = ?",
            (reminder_id,)
        )
        conn.commit()

def get_pending_reminders() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE is_sent = 0 ORDER BY remind_at ASC")
        return [dict(row) for row in cursor.fetchall()]

def add_rss_feed(feed_url: str, channel_id: int, title: str = None) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rss_feeds (feed_url, channel_id, title) VALUES (?, ?, ?)",
            (feed_url, channel_id, title)
        )
        conn.commit()
        return cursor.lastrowid

def get_rss_feeds() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rss_feeds ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]

def update_rss_last_entry(feed_id: int, last_entry_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE rss_feeds SET last_entry_id = ? WHERE id = ?",
            (last_entry_id, feed_id)
        )
        conn.commit()

def delete_rss_feed(feed_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
        conn.commit()
        return cursor.rowcount > 0

def add_memo(user_id: int, title: str, content: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memos (user_id, title, content) VALUES (?, ?, ?)",
            (user_id, title, content)
        )
        conn.commit()
        return cursor.lastrowid

def get_memos(user_id: int) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM memos WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

def delete_memo(memo_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM memos WHERE id = ? AND user_id = ?",
            (memo_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0

_SETTINGS_CACHE: dict[str, str] = {}
_SETTINGS_LOADED = False

def refresh_settings_cache():
    global _SETTINGS_LOADED, _SETTINGS_CACHE
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        _SETTINGS_CACHE = {row["key"]: row["value"] for row in rows}
        _SETTINGS_LOADED = True

def set_setting(key: str, value: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value))
        )
        conn.commit()
    _SETTINGS_CACHE[key] = str(value)

def get_setting(key: str, default: str = None) -> str:
    global _SETTINGS_LOADED
    if not _SETTINGS_LOADED:
        refresh_settings_cache()
    return _SETTINGS_CACHE.get(key, default)

def set_pomodoro_session(user_id: int, channel_id: int, mode: str, end_time: datetime, work_min: int, break_min: int, cycles_done: int = 0, target_cycles: int = 4):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pomodoro_sessions (user_id, channel_id, mode, end_time, work_min, break_min, cycles_done, target_cycles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                mode = excluded.mode,
                end_time = excluded.end_time,
                work_min = excluded.work_min,
                break_min = excluded.break_min,
                cycles_done = excluded.cycles_done,
                target_cycles = excluded.target_cycles
            """,
            (user_id, channel_id, mode, end_time.isoformat(), work_min, break_min, cycles_done, target_cycles)
        )
        conn.commit()

def get_pomodoro_session(user_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pomodoro_sessions WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_due_pomodoro_sessions() -> list:
    now_iso = get_bangkok_now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pomodoro_sessions WHERE end_time <= ?", (now_iso,))
        return [dict(row) for row in cursor.fetchall()]

def delete_pomodoro_session(user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pomodoro_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0

def get_all_active_pomodoro_sessions() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pomodoro_sessions")
        return [dict(row) for row in cursor.fetchall()]

def add_transaction(user_id: int, trans_type: str, amount: float, category: str, note: str = "") -> int:
    now = get_bangkok_now()
    today_str = now.strftime("%Y-%m-%d")
    created_at_str = now.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO transactions (user_id, type, amount, category, note, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, trans_type, amount, category, note, today_str, created_at_str)
        )
        conn.commit()
        return cursor.lastrowid

def get_daily_transactions(user_id: int, date_str: str) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM transactions
            WHERE user_id = ? AND date = ?
            ORDER BY id ASC
            """,
            (user_id, date_str)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_transactions(user_id: int, limit: int = 5) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM transactions
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_month_summary(user_id: int, year_month: str = None) -> dict:
    now = get_bangkok_now()
    if not year_month:
        year_month = now.strftime("%Y-%m")
    today_str = now.strftime("%Y-%m-%d")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT type, category, SUM(amount) as total
            FROM transactions
            WHERE user_id = ? AND date LIKE ?
            GROUP BY type, category
            """,
            (user_id, f"{year_month}%")
        )
        rows = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT SUM(amount) as today_expense, COUNT(id) as today_count
            FROM transactions
            WHERE user_id = ? AND date = ? AND type = 'expense'
            """,
            (user_id, today_str)
        )
        today_row = cursor.fetchone()
        today_expense = float(today_row["today_expense"] or 0.0) if today_row else 0.0
        today_count = int(today_row["today_count"] or 0) if today_row else 0

    total_income = 0.0
    total_expense = 0.0
    categories = {}

    for r in rows:
        if r["type"] == "income":
            total_income += float(r["total"] or 0.0)
        else:
            total_expense += float(r["total"] or 0.0)
            cat_name = r["category"]
            categories[cat_name] = categories.get(cat_name, 0.0) + float(r["total"] or 0.0)

    balance = total_income - total_expense
    return {
        "year_month": year_month,
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": balance,
        "today_expense": today_expense,
        "today_count": today_count,
        "categories": categories
    }

def delete_transaction(trans_id: int, user_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE id = ? AND user_id = ?", (trans_id, user_id))
        row = cursor.fetchone()
        if not row:
            return None
        row_dict = dict(row)
        cursor.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (trans_id, user_id))
        conn.commit()
        return row_dict

def delete_last_transaction(user_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        last = cursor.fetchone()
        if not last:
            return None
        last_dict = dict(last)
        cursor.execute("DELETE FROM transactions WHERE id = ?", (last_dict["id"],))
        conn.commit()
        return last_dict

def add_stream_tracker(platform: str, channel_login: str, display_name: str, destination_channel_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO stream_trackers (platform, channel_login, display_name, destination_channel_id, is_live)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(platform, channel_login) DO UPDATE SET
                display_name = excluded.display_name,
                destination_channel_id = excluded.destination_channel_id
            """,
            (platform.lower(), channel_login.lower(), display_name, destination_channel_id)
        )
        conn.commit()
        return cursor.lastrowid

def get_stream_trackers(platform: str = "twitch") -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stream_trackers WHERE platform = ? ORDER BY id ASC", (platform.lower(),))
        return [dict(row) for row in cursor.fetchall()]

def get_stream_tracker_by_login(channel_login: str, platform: str = "twitch") -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stream_trackers WHERE platform = ? AND channel_login = ?", (platform.lower(), channel_login.lower()))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_stream_tracker_status(tracker_id: int, is_live: int, last_stream_id: str = None):
    with get_connection() as conn:
        cursor = conn.cursor()
        if last_stream_id is not None:
            cursor.execute(
                "UPDATE stream_trackers SET is_live = ?, last_stream_id = ? WHERE id = ?",
                (is_live, last_stream_id, tracker_id)
            )
        else:
            cursor.execute(
                "UPDATE stream_trackers SET is_live = ? WHERE id = ?",
                (is_live, tracker_id)
            )
        conn.commit()

def delete_stream_tracker(channel_login: str, platform: str = "twitch") -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stream_trackers WHERE platform = ? AND channel_login = ?", (platform.lower(), channel_login.lower()))
        conn.commit()
        return cursor.rowcount > 0

def set_guild_youtube_channel(guild_id: int, channel_id: int, ping_role_id: int = None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO guild_settings (guild_id, youtube_channel_id, ping_role_id, is_active)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET
                youtube_channel_id = excluded.youtube_channel_id,
                ping_role_id = excluded.ping_role_id,
                is_active = 1
        """, (guild_id, channel_id, ping_role_id))
        conn.commit()

def get_guild_settings(guild_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def add_youtube_subscription(guild_id: int, youtube_channel_id: str, channel_title: str, last_video_id: str = None, avatar_url: str = None) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO youtube_subscriptions (guild_id, youtube_channel_id, channel_title, last_video_id, avatar_url)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, youtube_channel_id) DO UPDATE SET
                channel_title = excluded.channel_title,
                last_video_id = COALESCE(excluded.last_video_id, youtube_subscriptions.last_video_id),
                avatar_url = COALESCE(excluded.avatar_url, youtube_subscriptions.avatar_url)
        """, (guild_id, youtube_channel_id.strip(), channel_title, last_video_id, avatar_url))
        conn.commit()
        return cursor.lastrowid

def update_youtube_avatar(subscription_id: int, avatar_url: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE youtube_subscriptions SET avatar_url = ? WHERE id = ?", (avatar_url, subscription_id))
        conn.commit()

def get_guild_youtube_subscriptions(guild_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM youtube_subscriptions WHERE guild_id = ? ORDER BY id ASC", (guild_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_all_youtube_subscriptions() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, g.youtube_channel_id as alert_channel_id, g.ping_role_id, g.is_active as guild_active
            FROM youtube_subscriptions s
            JOIN guild_settings g ON s.guild_id = g.guild_id
            WHERE g.is_active = 1
            ORDER BY s.id ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

def get_youtube_seen_video_ids(subscription_id: int) -> set[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT video_id FROM youtube_seen_videos WHERE subscription_id = ?",
            (subscription_id,)
        )
        rows = cursor.fetchall()
        result = set()
        for r in rows:
            val = r["video_id"] if isinstance(r, dict) else r[0]
            result.add(val)
        return result

def add_youtube_seen_videos(subscription_id: int, video_ids: list[str]):
    if not video_ids:
        return
    clean_ids = [vid.strip().replace("yt:video:", "") for vid in video_ids if vid and vid.strip()]
    if not clean_ids:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.executemany(
                "INSERT INTO youtube_seen_videos (subscription_id, video_id) VALUES (%s, %s) ON CONFLICT (subscription_id, video_id) DO NOTHING",
                [(subscription_id, vid) for vid in clean_ids]
            )
            cursor.execute(
                """
                DELETE FROM youtube_seen_videos
                WHERE subscription_id = %s
                AND id NOT IN (
                    SELECT id FROM youtube_seen_videos
                    WHERE subscription_id = %s
                    ORDER BY id DESC
                    LIMIT 50
                )
                """,
                (subscription_id, subscription_id)
            )
        else:
            cursor.executemany(
                "INSERT OR IGNORE INTO youtube_seen_videos (subscription_id, video_id) VALUES (?, ?)",
                [(subscription_id, vid) for vid in clean_ids]
            )
            cursor.execute(
                """
                DELETE FROM youtube_seen_videos
                WHERE subscription_id = ?
                AND id NOT IN (
                    SELECT id FROM youtube_seen_videos
                    WHERE subscription_id = ?
                    ORDER BY id DESC
                    LIMIT 50
                )
                """,
                (subscription_id, subscription_id)
            )
        conn.commit()

def update_youtube_last_video(subscription_id: int, last_video_id: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE youtube_subscriptions SET last_video_id = ? WHERE id = ?", (last_video_id, subscription_id))
        clean_id = last_video_id.strip().replace("yt:video:", "") if last_video_id else None
        if clean_id:
            if USE_POSTGRES:
                cursor.execute(
                    "INSERT INTO youtube_seen_videos (subscription_id, video_id) VALUES (%s, %s) ON CONFLICT (subscription_id, video_id) DO NOTHING",
                    (subscription_id, clean_id)
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO youtube_seen_videos (subscription_id, video_id) VALUES (?, ?)",
                    (subscription_id, clean_id)
                )
        conn.commit()

def delete_youtube_subscription(guild_id: int, youtube_channel_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM youtube_subscriptions WHERE guild_id = ? AND (youtube_channel_id = ? OR channel_title = ?)",
            (guild_id, youtube_channel_id.strip(), youtube_channel_id.strip())
        )
        rows = cursor.fetchall()
        for row in rows:
            sid = row["id"] if isinstance(row, dict) else row[0]
            cursor.execute("DELETE FROM youtube_seen_videos WHERE subscription_id = ?", (sid,))
        cursor.execute("DELETE FROM youtube_subscriptions WHERE guild_id = ? AND (youtube_channel_id = ? OR channel_title = ?)", (guild_id, youtube_channel_id.strip(), youtube_channel_id.strip()))
        conn.commit()
        return cursor.rowcount > 0

def add_ai_chat_message(user_id: int, role: str, content: str):
    now_iso = get_bangkok_now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ai_chat_history (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, now_iso)
        )

def get_ai_chat_history(user_id: int, max_messages: int = 10, timeout_minutes: int = 30) -> list[dict]:
    cutoff_time = (get_bangkok_now() - timedelta(minutes=timeout_minutes)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content, created_at
            FROM ai_chat_history
            WHERE user_id = ? AND created_at >= ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, cutoff_time, max_messages))
        rows = cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

def clear_ai_chat_history(user_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_chat_history WHERE user_id = ?", (user_id,))
        return cursor.rowcount


