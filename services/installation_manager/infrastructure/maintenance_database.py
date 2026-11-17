"""PostgreSQL side of the Compose maintenance contract.

The admission adapter takes FOR SHARE on the same row when preparing and enqueuing.
All maintenance updates and drain checks take the exclusive lock first.
"""

from uuid import UUID

LOCK = """
DO $$ BEGIN
    PERFORM singleton FROM task_admission_control WHERE singleton = 1 FOR UPDATE;
END $$;
"""
TERMINAL = "('SUCCESS', 'ERROR', 'CANCELLED')"
NO_OUTBOX = """
NOT EXISTS (SELECT 1 FROM task_dispatch_outbox AS o WHERE o.task_id = tasks.task_id)
"""


def close_sql(operation_id: UUID) -> str:
    operation = UUID(str(operation_id))
    return f"""
BEGIN;
{LOCK}
UPDATE task_admission_control
SET operation_id = '{operation}'
WHERE singleton = 1 AND operation_id IS NULL;
UPDATE tasks
SET status = 'CANCELLED', message = 'Task was not yet admitted before maintenance',
    finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE status = 'PENDING' AND prepared_by_parent_id IS NULL AND {NO_OUTBOX}
  AND EXISTS (
    SELECT 1 FROM task_admission_control
    WHERE singleton = 1 AND operation_id = '{operation}' AND NOT frozen
  );
SELECT COALESCE(operation_id::text, '') FROM task_admission_control WHERE singleton = 1;
COMMIT;
"""


def drain_sql(operation_id: UUID) -> str:
    operation = UUID(str(operation_id))
    return f"""
BEGIN;
{LOCK}
UPDATE tasks
SET status = 'ERROR', termination_reason = 'WORKER_LOST',
    message = 'Worker lost before admitting the child',
    finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE status = 'PENDING' AND source = 'NODE' AND {NO_OUTBOX}
  AND EXISTS (
    SELECT 1 FROM tasks AS parent WHERE parent.task_id = tasks.prepared_by_parent_id
      AND parent.status = 'ERROR' AND parent.termination_reason = 'WORKER_LOST'
  )
  AND EXISTS (
    SELECT 1 FROM task_admission_control
    WHERE singleton = 1 AND operation_id = '{operation}' AND NOT frozen
  );
UPDATE task_admission_control SET frozen = true
WHERE singleton = 1 AND operation_id = '{operation}'
  AND NOT EXISTS (SELECT 1 FROM tasks WHERE status NOT IN {TERMINAL});
SELECT CASE WHEN frozen THEN 'frozen' ELSE (
    SELECT count(*) FROM tasks WHERE status NOT IN {TERMINAL}
)::text END FROM task_admission_control
WHERE singleton = 1 AND operation_id = '{operation}';
COMMIT;
"""


def reopen_sql(operation_id: UUID) -> str:
    operation = UUID(str(operation_id))
    return f"""
BEGIN;
{LOCK}
UPDATE task_admission_control SET operation_id = NULL
WHERE singleton = 1 AND operation_id = '{operation}' AND NOT frozen;
SELECT 'open' FROM task_admission_control
WHERE singleton = 1 AND operation_id IS NULL AND NOT frozen;
COMMIT;
"""


def frozen_sql(operation_id: UUID) -> str:
    operation = UUID(str(operation_id))
    return f"""
SELECT 'frozen' FROM task_admission_control
WHERE singleton = 1 AND operation_id = '{operation}' AND frozen
  AND NOT EXISTS (SELECT 1 FROM tasks WHERE status NOT IN {TERMINAL});
"""


def open_for_defer_sql(operation_id: UUID) -> str:
    operation = UUID(str(operation_id))
    return f"""
SELECT 'safe' FROM task_admission_control WHERE singleton = 1 AND NOT frozen
  AND (operation_id IS NULL OR operation_id = '{operation}');
"""


def confirm_return_to_source_sql(operation_id: UUID) -> str:
    operation = UUID(str(operation_id))
    return f"""
BEGIN;
{LOCK}
CREATE TABLE IF NOT EXISTS dvt_release_control.pre_migration_returns (
    operation_id uuid PRIMARY KEY
);
WITH opened AS (
    UPDATE task_admission_control SET operation_id = NULL, frozen = false
    WHERE singleton = 1 AND frozen AND operation_id = '{operation}'
      AND NOT EXISTS (SELECT 1 FROM tasks WHERE status NOT IN {TERMINAL})
    RETURNING singleton
)
INSERT INTO dvt_release_control.pre_migration_returns
SELECT '{operation}' FROM opened ON CONFLICT DO NOTHING;
COMMIT;
SELECT 'open' FROM task_admission_control
WHERE singleton = 1 AND operation_id IS NULL AND NOT frozen
  AND EXISTS (SELECT 1 FROM dvt_release_control.pre_migration_returns
              WHERE operation_id = '{operation}');
"""


DATABASE_PROFILE = """
SELECT CASE WHEN
    NOT EXISTS (SELECT 1 FROM pg_tablespace WHERE spcname NOT IN ('pg_default', 'pg_global'))
    AND NOT EXISTS (SELECT 1 FROM pg_prepared_xacts)
    AND NOT EXISTS (SELECT 1 FROM pg_subscription)
    AND current_database() NOT IN ('template0', 'template1')
    AND NOT EXISTS (
        SELECT 1 FROM pg_database
        WHERE datname NOT IN (current_database(), 'postgres', 'template0', 'template1')
    )
    THEN 'local' END
"""
NO_OTHER_CONNECTIONS = """
SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM pg_stat_activity
    WHERE pid <> pg_backend_pid() AND backend_type = 'client backend'
) THEN 'exclusive' END
"""
