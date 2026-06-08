"""
Unit tests for event_logger.

    python -m unittest discover tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import event_logger as el


class TestSafeLevel(unittest.TestCase):
    def test_synonym(self):
        self.assertEqual(el._safe_level("WARNING"), "WARN")

    def test_passthrough(self):
        self.assertEqual(el._safe_level("ERROR"), "ERROR")
        self.assertEqual(el._safe_level("alert"), "ALERT")

    def test_invalid_to_info(self):
        # a stray label that isn't a level → coerced to INFO (index stays clean)
        self.assertEqual(el._safe_level("SUPPLIER_X"), "INFO")

    def test_deduce_from_text(self):
        self.assertEqual(el._safe_level("got an EXCEPTION"), "ERROR")

    def test_none(self):
        self.assertEqual(el._safe_level(None), "INFO")


class TestLogAndRead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        el.configure(Path(self.tmp) / "events.db")

    def test_write_and_read(self):
        el.log_event("svc", "started")
        el.log_event("svc", "alarm", level="ALERT", details={"x": 1})
        rows = el.read_events()
        self.assertEqual(len(rows), 2)
        by_event = {r["event"]: r for r in rows}
        self.assertEqual(by_event["alarm"]["level"], "ALERT")
        self.assertEqual(by_event["alarm"]["details"], {"x": 1})
        self.assertEqual(by_event["started"]["automation"], "svc")

    def test_dedup_identical_records(self):
        rec = {"ts": "2026-01-01T00:00:00", "automation": "a",
               "level": "INFO", "event": "e", "message": "e"}
        el.append_record(dict(rec))
        el.append_record(dict(rec))   # same id → ignored
        self.assertEqual(len(el.read_events()), 1)

    def test_limit(self):
        for i in range(5):
            el.log_event("svc", f"e{i}")
        self.assertEqual(len(el.read_events(limit=3)), 3)


if __name__ == "__main__":
    unittest.main()
