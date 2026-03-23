-- PostgreSQL 初始化脚本
-- 创建 pgvector 扩展（Mem0 Phase 3 依赖）

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 确认扩展创建成功
DO $$
BEGIN
    RAISE NOTICE 'pgvector extension: %', (SELECT extversion FROM pg_extension WHERE extname = 'vector');
END $$;
