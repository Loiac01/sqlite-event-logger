"""
event_logger.py — Lightweight structured event logging to SQLite.

Zero dependencies (Python 3.8+ stdlib). One small file. Drop it into a project
and get a queryable, deduplicated, thread-safe event log — no logging framework,
no server, no setup.

Key idea — separate business ALERTs from technical ERRORs:
    INFO     normal execution
    DEBUG    diagnostics
    WARN     a handled anomaly, worth watching
    ALERT    a legitimate *business* alert (not a crash): a threshold exceeded,
             an SLA breached, an expected-but-bad outcome
    ERROR    a technical error / handled exception
    CRITICAL a crash or production impact
Keeping ALERT distinct from ERROR lets a dashboard show real failures without
drowning in business noise.

Quick use:
    from event_logger import log_event, read_events, configure
    configure("events.db")                 # optional; defaults to ./events.db
    log_event("billing", "invoice_sent", details={"id": 42})
    log_event("billing", "payment_late", level="ALERT", details={"days": 5})
    for e in read_events():
        print(e["ts"], e["automation"], e["level"], e["event"])
"""

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

LEVELS_TECHNICAL = {"ERROR", "CRITICAL"}
LEVELS_BUSINESS = {"ALERT"}

_VALID_LEVELS = {"INFO", "DEBUG", "WARN", "ALERT", "ERROR", "CRITICAL"}
_LEVEL_SYNONYMS = {"WARNING": "WARN", "ERR": "ERROR", "CRIT": "CRITICAL",
                   "FATAL": "CRITICAL", "TRACE": "DEBUG", "NOTICE": "INFO"}

# DB path: env override, else ./events.db in the current working directory.
_DB_FILE = Path(os.environ.get("EVENT_LOG_DB") or "events.db")
_LOCK = threading.Lock()
_initialized = False

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    ts          TEXT,
    automation  TEXT,
    level       TEXT,
    event       TEXT,
    message     TEXT,
    source_file TEXT,
    source_line TEXT,
    source_kind TEXT,
    details     TEXT
);
CREATE INDEX IF NOT EXISTS idx_ts         ON events(ts);
CREATE INDEX IF NOT EXISTS idx_level      ON events(level);
CREATE INDEX IF NOT EXISTS idx_automation ON events(automation);
"""


def configure(db_path) -> None:
    """Set the SQLite file path. Call before the first ``log_event()``."""
    global _DB_FILE, _initialized
    _DB_FILE = Path(db_path)
    _initialized = False


def _connect():
    conn = sqlite3.connect(str(_DB_FILE), timeout=15, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_init():
    """Create the DB/table on first use (lazy — no side effects at import)."""
    global _initialized
    if _initialized:
        return
    parent = _DB_FILE.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_DDL)
    _initialized = True


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat()


def _safe_level(level):
    """Normalize/whitelist the level so the indexed column never holds junk."""
    value = str(level or "INFO").upper().strip()
    if not value:
        return "INFO"
    value = _LEVEL_SYNONYMS.get(value, value)
    if value in _VALID_LEVELS:
        return value
    # Unknown value (a phrase passed by mistake, etc.): deduce from text, else INFO.
    if "ERROR" in value or "EXCEPTION" in value or "CRASH" in value or "FATAL" in value:
        return "ERROR"
    if "WARN" in value:
        return "WARN"
    return "INFO"


def _safe_details(details):
    if details is None:
        return {}
    if isinstance(details, dict):
        return details
    return {"text": str(details)}


def _make_event_id(record):
    seed = "|".join([
        str(record.get("ts", "")),
        str(record.get("automation", "")),
        str(record.get("level", "")),
        str(record.get("event", "")),
        str(record.get("message", "")),
        str(record.get("source_file", "")),
        str(record.get("source_line", "")),
    ])
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_record(record):
    rec = dict(record or {})
    rec["ts"] = str(rec.get("ts") or _now_iso())
    rec["automation"] = str(rec.get("automation") or "unknown")
    rec["level"] = _safe_level(rec.get("level"))
    rec["event"] = str(rec.get("event") or "log")
    rec["details"] = _safe_details(rec.get("details"))

    message = rec.get("message")
    if message is None:
        if isinstance(rec["details"], dict) and rec["details"].get("message"):
            message = rec["details"].get("message")
        else:
            message = rec["event"]
    rec["message"] = str(message)

    if not rec.get("id"):
        rec["id"] = _make_event_id(rec)
    return rec


def _insert_records(records):
    rows = [
        (
            rec.get("id", ""),
            rec.get("ts", ""),
            rec.get("automation", ""),
            rec.get("level", ""),
            rec.get("event", ""),
            rec.get("message", ""),
            rec.get("source_file", ""),
            str(rec.get("source_line", "") or ""),
            rec.get("source_kind", ""),
            json.dumps(rec.get("details", {}), ensure_ascii=False),
        )
        for rec in records
    ]
    with _LOCK:
        _ensure_init()
        try:
            with _connect() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", rows
                )
        except Exception:
            pass


def append_records(records):
    """Insert many records (each a dict). Returns the count. Deduplicated by id."""
    if not records:
        return 0
    normalized = [_normalize_record(r) for r in records]
    _insert_records(normalized)
    return len(normalized)


def append_record(record):
    return append_records([record])


def log_event(automation, event, level="INFO", details=None):
    """Log one event. ``automation`` = source/component, ``event`` = what happened."""
    record = _normalize_record({
        "ts": _now_iso(),
        "automation": automation,
        "level": level,
        "event": event,
        "details": _safe_details(details),
        "message": str(event),
    })
    append_record(record)
    return record


def install_crash_hook(automation_name: str) -> None:
    """Install ``sys.excepthook`` and ``threading.excepthook`` so any uncaught
    exception is written straight to the event log (works under pythonw too)."""
    import sys
    import traceback

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            log_event(automation_name, "crash", level="ERROR", details={
                "exception": exc_type.__name__,
                "message": str(exc_value),
                "traceback": tb_str[:2000],
            })
        except Exception:
            pass

    sys.excepthook = _excepthook

    try:
        def _thread_excepthook(args):
            if args.exc_type is None or issubclass(args.exc_type, SystemExit):
                return
            tb_str = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_tb))
            thread_name = getattr(args.thread, "name", "unknown_thread")
            try:
                log_event(automation_name, "thread_crash", level="ERROR", details={
                    "thread": thread_name,
                    "exception": args.exc_type.__name__,
                    "message": str(args.exc_value),
                    "traceback": tb_str[:2000],
                })
            except Exception:
                pass

        threading.excepthook = _thread_excepthook
    except Exception:
        pass


def read_events(limit=0):
    """Return events as a list of dicts, oldest first. ``limit`` 0 = all."""
    try:
        _ensure_init()
        with _connect() as conn:
            if limit and limit > 0:
                rows = conn.execute(
                    "SELECT id,ts,automation,level,event,message,"
                    "source_file,source_line,source_kind,details "
                    "FROM events ORDER BY ts DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = conn.execute(
                    "SELECT id,ts,automation,level,event,message,"
                    "source_file,source_line,source_kind,details "
                    "FROM events ORDER BY ts ASC"
                ).fetchall()

        result = []
        for row in rows:
            rec = {
                "id": row[0], "ts": row[1], "automation": row[2], "level": row[3],
                "event": row[4], "message": row[5], "source_file": row[6],
                "source_line": row[7], "source_kind": row[8],
            }
            try:
                rec["details"] = json.loads(row[9] or "{}")
            except Exception:
                rec["details"] = {}
            result.append(rec)
        return result
    except Exception:
        return []
