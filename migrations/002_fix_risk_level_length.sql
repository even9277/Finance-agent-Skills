-- Migration 002: 修复 risk_level 字段长度限制
-- 时间: 2026-03-18
-- 说明: 将 risk_level 从 VARCHAR(20) 扩展到 VARCHAR(50)，支持 balanced_conservative 等值

-- 修改 user_invest_profiles 表的 risk_level 字段长度
ALTER TABLE user_invest_profiles 
  ALTER COLUMN risk_level TYPE VARCHAR(50);

-- 验证
SELECT column_name, data_type, character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'user_invest_profiles' 
  AND column_name = 'risk_level';
