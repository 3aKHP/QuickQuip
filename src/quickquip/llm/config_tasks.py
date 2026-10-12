"""Cross-process configuration operation queue with fencing tokens."""

from __future__ import annotations

import json
import time
import uuid

from quickquip.llm.config_store import dumps


def operation(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("payload", "result", "error"):
        result[key] = json.loads(result[key]) if result[key] else None
    return result


class ConfigTaskQueue:
    def __init__(self, store):
        self.store = store

    def get(self, operation_id):
        from quickquip.llm.config_document import ConfigError

        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM config_operations WHERE id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise ConfigError("not_found", "Operation not found")
        result = operation(row)
        result.pop("claim_token", None)
        return result

    def list(self, limit=20):
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM config_operations ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        results = [operation(row) for row in rows]
        for result in results:
            result.pop("claim_token", None)
        return results

    def claim(self, owner, lease_seconds=30, boot_id=None):
        now = time.time()
        with self.store.connect(write=True) as conn:
            if boot_id is not None:
                from quickquip.llm.config_service import ConfigService
                ConfigService._assert_bot_boot(conn, boot_id)
            conn.execute(
                """UPDATE config_operations SET status='failed',stage='unconfirmed',
                error=?,updated_at=? WHERE kind='probe' AND status='running' AND lease_until<?""",
                (
                    dumps(
                        {
                            "code": "probe_result_unconfirmed",
                            "message": "Interrupted probe result is unconfirmed",
                        }
                    ),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """SELECT * FROM config_operations
                WHERE status='queued' OR (status='running' AND lease_until<? AND kind='apply')
                ORDER BY created_at LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            conn.execute(
                """UPDATE config_operations SET status='running',stage='preparing',
                owner=?,claim_token=?,lease_until=?,updated_at=? WHERE id=?""",
                (owner, token, now + lease_seconds, now, row["id"]),
            )
            return operation(
                conn.execute("SELECT * FROM config_operations WHERE id=?", (row["id"],)).fetchone()
            )

    @staticmethod
    def assert_claim(conn, operation_id, token):
        from quickquip.llm.config_document import ConfigError

        row = conn.execute("SELECT * FROM config_operations WHERE id=?", (operation_id,)).fetchone()
        if (
            row is None
            or row["status"] != "running"
            or row["claim_token"] != token
            or row["lease_until"] < time.time()
        ):
            raise ConfigError("stale_claim", "Operation lease is no longer owned")
        return row

    def heartbeat(self, operation_id, token, lease_seconds=30):
        with self.store.connect(write=True) as conn:
            self.assert_claim(conn, operation_id, token)
            conn.execute(
                "UPDATE config_operations SET lease_until=?,updated_at=? WHERE id=?",
                (time.time() + lease_seconds, time.time(), operation_id),
            )
        return True

    def update_stage(self, operation_id, token, stage):
        with self.store.connect(write=True) as conn:
            self.assert_claim(conn, operation_id, token)
            conn.execute(
                "UPDATE config_operations SET stage=?,updated_at=? WHERE id=?",
                (stage, time.time(), operation_id),
            )

    def finish(self, operation_id, token, status="succeeded", result=None, error=None):
        if status not in ("succeeded", "failed"):
            raise ValueError("finish status must be succeeded or failed")
        with self.store.connect(write=True) as conn:
            self.assert_claim(conn, operation_id, token)
            conn.execute(
                """UPDATE config_operations SET status=?,stage='finished',result=?,error=?,
                updated_at=?,lease_until=NULL WHERE id=?""",
                (
                    status,
                    dumps(result or {}),
                    dumps(error) if error else None,
                    time.time(),
                    operation_id,
                ),
            )
        return self.get(operation_id)

    def cancel(self, operation_id):
        from quickquip.llm.config_document import ConfigError

        with self.store.connect(write=True) as conn:
            cursor = conn.execute(
                """UPDATE config_operations SET status='cancelled',
                stage='cancelled',updated_at=? WHERE id=? AND status='queued'""",
                (time.time(), operation_id),
            )
            if not cursor.rowcount:
                raise ConfigError("operation_conflict", "Only queued operations can be cancelled")
        return self.get(operation_id)
