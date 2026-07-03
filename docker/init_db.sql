-- ====================================================================
--  BizTools4Openclaw 数据库初始化脚本
--  对应 ORM: infra/db_base.py + infra/db_models.py (SQLAlchemy 2.0)
--  目标数据库: PostgreSQL 16 + pgvector
--  使用方式：
--    1) docker-compose 启动时自动执行（挂载到 /docker-entrypoint-initdb.d/）
--    2) 或手动执行：psql -U postgres -d openclaw_biz -f docker/init_db.sql
--  幂等保证：所有 CREATE TABLE 使用 IF NOT EXISTS；INSERT 使用 ON CONFLICT DO NOTHING
-- ====================================================================

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

-- -------- 1. 扩展 --------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- -------- 2. 表 1: spider_raw_data（原始爬虫数据） --------
CREATE TABLE IF NOT EXISTS spider_raw_data (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL DEFAULT 'default',
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    spider_name VARCHAR(128) NOT NULL,
    source_url VARCHAR(1024) NOT NULL,
    source_id VARCHAR(256),
    raw_payload JSONB NOT NULL DEFAULT '{}',
    raw_text TEXT,
    fetch_status SMALLINT NOT NULL DEFAULT 0,
    fetch_error VARCHAR(512),
    captured_at TIMESTAMP NOT NULL DEFAULT NOW(),
    source_country CHAR(2) DEFAULT 'US'
);

CREATE INDEX IF NOT EXISTS idx_spider_raw_source_id
    ON spider_raw_data (tenant_id, spider_name, source_id);
CREATE INDEX IF NOT EXISTS idx_spider_raw_captured
    ON spider_raw_data (captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_spider_raw_archived_name
    ON spider_raw_data (is_archived, spider_name);

-- -------- 3. 表 2: business_opportunities（结构化商机） --------
CREATE TABLE IF NOT EXISTS business_opportunities (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL DEFAULT 'default',
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    raw_id BIGINT,
    source VARCHAR(128),
    title VARCHAR(512) NOT NULL,
    description TEXT,
    business_type VARCHAR(64),
    contact_name VARCHAR(256),
    contact_phone VARCHAR(256),      -- 应用层加密存储
    contact_email VARCHAR(256),      -- 应用层加密存储
    contact_wechat VARCHAR(256),     -- 应用层加密存储
    company_name VARCHAR(512),
    industry VARCHAR(128),
    city VARCHAR(128),
    country CHAR(2),
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    priority SMALLINT DEFAULT 50,
    score NUMERIC(5, 2),
    budget_currency CHAR(3) DEFAULT 'USD',
    budget_min NUMERIC(18, 2),
    budget_max NUMERIC(18, 2),
    source_first_seen TIMESTAMP DEFAULT NOW(),
    deduplication_hash VARCHAR(128),
    extra_metadata JSONB DEFAULT '{}',
    embedding vector(768)             -- 向量化描述（可选，供 pgvector 语义检索）
);

CREATE INDEX IF NOT EXISTS idx_opp_tenant_status
    ON business_opportunities (tenant_id, status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_opp_tenant_created
    ON business_opportunities (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opp_dedup_hash
    ON business_opportunities (deduplication_hash);
CREATE INDEX IF NOT EXISTS idx_opp_industry_city
    ON business_opportunities (industry, city);
CREATE INDEX IF NOT EXISTS idx_opp_embedding
    ON business_opportunities USING hnsw (embedding vector_cosine_ops);

-- -------- 4. 表 3: sales_tasks（销售任务与跟进记录） --------
CREATE TABLE IF NOT EXISTS sales_tasks (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL DEFAULT 'default',
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    opportunity_id BIGINT NOT NULL,
    assignee VARCHAR(128),
    task_type VARCHAR(64) NOT NULL DEFAULT 'follow_up',
    title VARCHAR(512) NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    priority SMALLINT DEFAULT 50,
    due_date TIMESTAMP,
    completed_at TIMESTAMP,
    outcome VARCHAR(32),
    notes TEXT,
    channel VARCHAR(32),
    campaign VARCHAR(128),
    extra_metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sales_tenant_status
    ON sales_tasks (tenant_id, status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_sales_opportunity
    ON sales_tasks (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_sales_assignee_due
    ON sales_tasks (assignee, due_date);
CREATE INDEX IF NOT EXISTS idx_sales_created
    ON sales_tasks (created_at DESC);

-- -------- 5. 表 4: system_logs（系统日志与审计记录） --------
CREATE TABLE IF NOT EXISTS system_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    log_level VARCHAR(16) NOT NULL DEFAULT 'info',
    log_type VARCHAR(64) NOT NULL,
    actor VARCHAR(128),
    target_resource VARCHAR(256),
    message TEXT,
    extra JSONB DEFAULT '{}',
    ip_address VARCHAR(64),
    user_agent VARCHAR(1024),
    duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_syslog_tenant_time
    ON system_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_syslog_level_type
    ON system_logs (log_level, log_type);
CREATE INDEX IF NOT EXISTS idx_syslog_actor
    ON system_logs (actor);

-- -------- 6. 触发器：自动更新 updated_at --------
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_timestamp_spider_raw ON spider_raw_data;
CREATE TRIGGER set_timestamp_spider_raw
    BEFORE UPDATE ON spider_raw_data
    FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

DROP TRIGGER IF EXISTS set_timestamp_opp ON business_opportunities;
CREATE TRIGGER set_timestamp_opp
    BEFORE UPDATE ON business_opportunities
    FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

DROP TRIGGER IF EXISTS set_timestamp_sales ON sales_tasks;
CREATE TRIGGER set_timestamp_sales
    BEFORE UPDATE ON sales_tasks
    FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

-- -------- 7. 初始数据：审计系统初始化记录 --------
INSERT INTO system_logs (
    tenant_id, log_level, log_type, actor, target_resource,
    message, extra, ip_address, duration_ms
) VALUES (
    'default', 'info', 'system', 'deployment',
    'database/init', 'T16 docker/init_db.sql 数据库初始化完成',
    '{"deploy_tool":"docker-compose","version":"T16-v1.0"}',
    '127.0.0.1', 0
) ON CONFLICT DO NOTHING;

-- -------- 8. 权限收尾 --------
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO CURRENT_USER;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO CURRENT_USER;

-- ====================================================================
--  初始化完成提示
-- ====================================================================
DO $$
BEGIN
    RAISE NOTICE 'BizTools4Openclaw 数据库初始化完成：4 张核心表已创建';
    RAISE NOTICE '  - spider_raw_data       （原始爬虫数据）';
    RAISE NOTICE '  - business_opportunities（结构化商机）';
    RAISE NOTICE '  - sales_tasks           （销售任务）';
    RAISE NOTICE '  - system_logs           （系统日志/审计）';
    RAISE NOTICE '注意：DB_ENCRYPTION_KEY 必须在 .env 中配置（至少 16 字符，推荐 32）';
END $$;
