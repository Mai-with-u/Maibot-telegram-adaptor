"""Exercise the polling store with real SQLite connections, independently of GC timing."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import sqlite3

from storage import AdapterStore


class StoreConnectionTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = AdapterStore(Path(tmp.name) / "telegram.sqlite3")
        connect = sqlite3.connect
        self.opened = []

        def retain_connection(path):
            db = connect(path)
            self.opened.append(db)
            self.addCleanup(db.close)
            return db

        self.enterContext(patch("storage.sqlite3.connect", side_effect=retain_connection))
        self.store._initialize()
        self.store._save_offset("bot", 17)

    def test_poll_reads_release_connections_without_waiting_for_gc(self):
        for _ in range(8):
            self.assertEqual(self.store._offset("bot"), 17)
        for db in self.opened:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                db.execute("SELECT 1")

    def test_failed_update_and_cursor_remain_atomic_on_error(self):
        with closing(sqlite3.connect(self.store.path)) as setup, setup:
            setup.execute(
                "CREATE TRIGGER fail_cursor BEFORE INSERT ON cursors "
                "BEGIN SELECT RAISE(ABORT, 'cursor write failed'); END"
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "cursor write failed"):
            self.store._save_failed_update("bot", {"update_id": 17}, "test", "")
        failed_connection = self.opened[-1]
        self.assertIsNone(self.store._failed_update("bot", 17))
        self.assertEqual(self.store._offset("bot"), 17)
        with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
            failed_connection.execute("SELECT 1")
