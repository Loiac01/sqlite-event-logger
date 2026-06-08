"""
demo.py — 30-second tour of event_logger.

    python examples/demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from event_logger import log_event, read_events, configure

# Optional: choose where the SQLite file lives (default: ./events.db)
configure(Path(__file__).parent / "demo_events.db")

# Log a few events at different levels
log_event("billing", "invoice_sent", details={"invoice": 1042})
log_event("billing", "payment_late", level="ALERT", details={"days_overdue": 5})
log_event("worker", "job_failed", level="ERROR", details={"job": "nightly-sync"})

# install_crash_hook(name) would also capture any uncaught exception as an event.

print("ts                              | automation | level  | event")
print("-" * 70)
for e in read_events():
    print(f"{e['ts']:31}| {e['automation']:10} | {e['level']:6} | {e['event']}")
