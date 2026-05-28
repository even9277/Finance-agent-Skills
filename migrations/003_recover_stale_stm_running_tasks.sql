-- 一次性修复脚本（PostgreSQL）
-- 目的：回收历史卡死的 STM running 任务，恢复队列可消费状态。
-- 默认按 180 秒判定 stale，可按需修改 interval。

BEGIN;

WITH stale AS (
    SELECT
        id,
        session_id,
        COALESCE(task_type, 'compaction') AS task_type
    FROM stm_compaction_tasks
    WHERE status = 'running'
      AND started_at IS NOT NULL
      AND started_at < (NOW() - INTERVAL '180 seconds')
    FOR UPDATE
),
recovered AS (
    UPDATE stm_compaction_tasks t
    SET status = 'pending',
        started_at = NULL,
        finished_at = NULL,
        error_msg = 'manual_recovery_stale_running>180s'
    FROM stale s
    WHERE t.id = s.id
    RETURNING s.session_id, s.task_type
)
UPDATE sessions s
SET compression_status = 'queued'
FROM (
    SELECT DISTINCT session_id
    FROM recovered
    WHERE task_type = 'compaction'
      AND session_id IS NOT NULL
) r
WHERE s.id = r.session_id;

COMMIT;
