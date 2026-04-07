import logging
import sqlite3
import threading
import time

from generated import killswitch_pb2

log = logging.getLogger(__name__)

DB_PATH = 'data/flags.db'


class FlagStore:

    def __init__(self, db_path=DB_PATH):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.execute('''
                CREATE TABLE IF NOT EXISTS flags (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    UNIQUE NOT NULL,
                    enabled     INTEGER NOT NULL,
                    description TEXT    NOT NULL DEFAULT '',
                    updated_at  INTEGER NOT NULL,
                    updated_by  TEXT    NOT NULL
                )
            ''')
            self._conn.commit()

    def _get_row(self, name):
        cursor = self._conn.execute(
            'SELECT name, enabled, description, updated_at, updated_by FROM flags WHERE name = ?',
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {'name': row[0], 'enabled': bool(row[1]), 'description': row[2],
                'updated_at': row[3], 'updated_by': row[4]}

    def _list_rows(self):
        cursor = self._conn.execute(
            'SELECT name, enabled, description FROM flags ORDER BY name'
        )
        return [{'name': r[0], 'enabled': bool(r[1]), 'description': r[2]}
                for r in cursor.fetchall()]

    def set_flag(self, request, policy_stub, broadcaster_stub, audit_stub):
        proposed = request.flag
        changed_by = request.changed_by
        reason = request.reason or ''
        now = int(time.time())

        with self._lock:
            current_row = self._get_row(proposed.name)
            all_rows = self._list_rows()

        old_enabled = current_row['enabled'] if current_row else False
        delete_requested = not proposed.enabled and 'delete' in reason.lower()

        if delete_requested and current_row is None:
            return False, f"Flag '{proposed.name}' not found"

        current_flag_proto = killswitch_pb2.Flag(
            name=proposed.name,
            enabled=old_enabled,
            description=current_row['description'] if current_row else '',
        )
        context_flags = [
            killswitch_pb2.Flag(name=r['name'], enabled=r['enabled'], description=r['description'])
            for r in all_rows
        ]
        policy_req = killswitch_pb2.PolicyRequest(
            current_flag=current_flag_proto,
            proposed_change=proposed,
            changed_by=changed_by,
            context_flags=context_flags,
        )

        try:
            policy_resp = policy_stub.ValidateChange(policy_req)
        except Exception as e:
            log.error("PolicyEvaluator call failed for flag='%s': %s", proposed.name, e)
            return False, f"Policy check unavailable: {e}"

        if not policy_resp.approved:
            log.info("SetFlag denied: flag='%s' reason='%s'", proposed.name, policy_resp.denial_reason)
            return False, policy_resp.denial_reason

        if delete_requested:
            with self._lock:
                self._conn.execute('DELETE FROM flags WHERE name = ?', (proposed.name,))
                self._conn.commit()
            log.info("Deleted: flag='%s' by='%s'", proposed.name, changed_by)
            change_type = 'DELETED'
        else:
            with self._lock:
                self._conn.execute(
                    '''INSERT INTO flags (name, enabled, description, updated_at, updated_by)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(name) DO UPDATE SET
                           enabled     = excluded.enabled,
                           description = excluded.description,
                           updated_at  = excluded.updated_at,
                           updated_by  = excluded.updated_by''',
                    (proposed.name, int(proposed.enabled), proposed.description, now, changed_by),
                )
                self._conn.commit()
            log.info("Persisted: flag='%s' enabled=%s by='%s'", proposed.name, proposed.enabled, changed_by)
            change_type = 'ENABLED' if proposed.enabled else 'DISABLED'

        flag_update = killswitch_pb2.FlagUpdate(
            flag=proposed,
            changed_by=changed_by,
            timestamp=now,
            change_type=change_type,
        )
        try:
            broadcaster_stub.NotifyChange(flag_update)
        except Exception as e:
            log.warning("Broadcaster notification failed for flag='%s': %s", proposed.name, e)

        audit_record = killswitch_pb2.AuditRecord(
            flag_name=proposed.name,
            old_value=old_enabled,
            new_value=False,
            changed_by=changed_by,
            changed_at=now,
            reason=reason,
            policy_result='approved',
        )
        try:
            audit_stub.LogChange(audit_record)
        except Exception as e:
            log.warning("AuditLogger call failed for flag='%s': %s", proposed.name, e)

        return True, "ok"

    def get_flag(self, name):
        with self._lock:
            return self._get_row(name)

    def list_flags(self):
        with self._lock:
            return self._list_rows()
