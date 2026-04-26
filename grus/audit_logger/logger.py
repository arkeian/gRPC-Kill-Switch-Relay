import logging
import queue
import sqlite3
import threading

log = logging.getLogger(__name__)

DB_PATH = 'data/audit.db'

_SENTINEL = object()


class AuditLogger:

    def __init__(self, db_path=DB_PATH):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._subscribers = []
        self._sub_lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.execute('''
                CREATE TABLE IF NOT EXISTS audit (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    flag_name     TEXT    NOT NULL,
                    old_value     INTEGER NOT NULL,
                    new_value     INTEGER NOT NULL,
                    changed_by    TEXT    NOT NULL,
                    changed_at    INTEGER NOT NULL,
                    reason        TEXT    NOT NULL,
                    policy_result TEXT    NOT NULL
                )
            ''')
            self._conn.commit()

    def log_change(self, record):
        with self._lock:
            self._conn.execute(
                '''INSERT INTO audit
                   (flag_name, old_value, new_value, changed_by,
                    changed_at, reason, policy_result)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    record.flag_name,
                    int(record.old_value),
                    int(record.new_value),
                    record.changed_by,
                    record.changed_at,
                    record.reason,
                    record.policy_result,
                ),
            )
            self._conn.commit()
        log.info("Logged change: flag='%s' %s->%s by '%s'",
                 record.flag_name, record.old_value, record.new_value, record.changed_by)
        self._notify_subscribers(record)

    def _notify_subscribers(self, record):
        with self._sub_lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(record)

    def get_history(self, flag_name='', limit=0):
        query = 'SELECT flag_name, old_value, new_value, changed_by, changed_at, reason, policy_result FROM audit'
        params = []

        if flag_name:
            query += ' WHERE flag_name = ?'
            params.append(flag_name)

        query += ' ORDER BY changed_at DESC'

        if limit > 0:
            query += ' LIMIT ?'
            params.append(limit)

        with self._lock:
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            {
                'flag_name':     row[0],
                'old_value':     bool(row[1]),
                'new_value':     bool(row[2]),
                'changed_by':    row[3],
                'changed_at':    row[4],
                'reason':        row[5],
                'policy_result': row[6],
            }
            for row in rows
        ]

    def add_subscriber(self, q):
        with self._sub_lock:
            self._subscribers.append(q)
        log.info("StreamHistory subscriber added (total: %d)", len(self._subscribers))

    def remove_subscriber(self, q):
        with self._sub_lock:
            self._subscribers.remove(q)
        log.info("StreamHistory subscriber removed (total: %d)", len(self._subscribers))

    def shutdown(self):
        with self._sub_lock:
            for q in self._subscribers:
                q.put(_SENTINEL)
