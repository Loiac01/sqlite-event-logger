# sqlite-event-logger

**Structured event logging to SQLite, in one file.** Zero dependencies · thread-safe · deduplicated · separates business ALERTs from technical ERRORs.

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![tests](https://github.com/Loiac01/sqlite-event-logger/actions/workflows/test.yml/badge.svg)

A queryable event log without a logging framework, a server, or any setup. Drop
`event_logger.py` into your project and you get a thread-safe, deduplicated,
SQLite-backed log you can query with plain SQL.

```python
from event_logger import log_event, read_events

log_event("billing", "invoice_sent", details={"invoice": 42})
log_event("billing", "payment_late", level="ALERT", details={"days_overdue": 5})

for e in read_events():
    print(e["ts"], e["automation"], e["level"], e["event"])
```

> ⭐ If it's useful, a star helps.

## Why

`print()` disappears, log files rot, and a full logging stack is overkill for a
script or a small fleet of automations. This gives you the 20% that matters:

- 🗃️ **SQLite-backed** — query your events with SQL, no extra service.
- 🚦 **ALERT vs ERROR** — a first-class distinction (see below) so a dashboard can
  show real failures without drowning in business noise.
- 🧷 **Deduplicated** — identical events collapse to one row (SHA-1 id + `INSERT OR IGNORE`).
- 🧵 **Thread-safe** — WAL mode + a lock; safe from multiple threads.
- 💥 **Crash hook** — `install_crash_hook()` writes any uncaught exception (and
  thread exceptions) straight to the log — works under `pythonw` too.
- 🪶 **Zero dependencies** — Python 3.8+ standard library only.

## ALERT vs ERROR

The single design decision that makes the log useful:

| Level | Meaning |
|-------|---------|
| `INFO` / `DEBUG` | normal execution / diagnostics |
| `WARN` | a handled anomaly, worth watching |
| **`ALERT`** | a legitimate **business** alert — a threshold exceeded, an SLA breached, an expected-but-bad outcome. **Not a bug.** |
| `ERROR` / `CRITICAL` | a **technical** failure / crash |

Filtering `ALERT` from `ERROR` lets you route "the system is broken" separately
from "the business needs attention".

## Quick start

It's one file — copy `event_logger.py` into your project.

```python
from event_logger import log_event, read_events, configure

configure("events.db")          # optional; defaults to ./events.db (or $EVENT_LOG_DB)

log_event("worker", "started")
log_event("worker", "job_failed", level="ERROR", details={"job": "sync"})

recent = read_events(limit=20)  # list of dicts, oldest first
```

Run the demo:

```bash
python examples/demo.py
```

## API

```python
configure(db_path)                                  # set the SQLite path (before first log)
log_event(automation, event, level="INFO", details=None)
append_record(record) / append_records(records)     # log raw dict record(s)
read_events(limit=0)                                # list[dict], oldest first
install_crash_hook(automation_name)                 # auto-log uncaught exceptions
```

### Schema

```
id | ts | automation | level | event | message | source_file | source_line | source_kind | details(JSON)
```

Query it like any SQLite DB:

```sql
SELECT ts, automation, event FROM events WHERE level = 'ALERT' ORDER BY ts DESC;
```

## Tests

```bash
python -m unittest discover tests
```

## License

MIT — see [LICENSE](LICENSE).

---

Part of a small Windows-automation toolkit · companion project:
[win-keepalive](https://github.com/Loiac01/win-keepalive) (keep Python scripts alive 24/7 on Windows).
